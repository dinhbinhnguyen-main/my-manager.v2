"""Automation Job Runner with proxy pool dynamic concurrency throttling min(available_proxies, threads)."""

import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from src.db.repository import (
    AutomationJobRepository,
    AccountRepository,
    ProxyRepository,
    RedroidRepository,
)
from src.core.models import AutomationJob, JobStatus
from src.core.constants import MAX_CONCURRENT_REDROID_CONTAINERS
from src.redroid.manager import RedroidManager
from src.automation.facebook.router import execute_action
from src.services.redis_tracker import RedisTracker

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, threads: int = 4):
        self.requested_threads = threads
        self.redis_tracker = RedisTracker()

    def run_job_single(self, job: AutomationJob) -> bool:
        """Executes a single automation job, managing proxy acquisition, Redroid lifecycle, and action sequence."""
        account_uid = job.account_uid
        logger.info(f"[Job-{job.id}] Starting execution for account {account_uid}...")

        # 1. Acquire Proxy (Wait up to 90s for an available proxy in the pool)
        proxy = None
        max_wait_sec = 90
        start_wait = time.time()
        last_log = 0
        while time.time() - start_wait < max_wait_sec:
            proxy = ProxyRepository.acquire_available_proxy(account_uid)
            if proxy:
                logger.info(f"[Job-{job.id}] Acquired proxy #{proxy.id} for account {account_uid}")
                break
            now = time.time()
            if now - last_log >= 10:
                elapsed = int(now - start_wait)
                logger.info(f"[Job-{job.id}] Waiting for an available proxy in pool (elapsed {elapsed}s/{max_wait_sec}s)...")
                last_log = now
            time.sleep(3)

        if not proxy:
            msg = f"No available proxy to run job {job.id} for account {account_uid} after waiting {max_wait_sec}s."
            logger.warning(f"[Job-{job.id}] {msg}")
            AutomationJobRepository.update_status(
                job.id, status="failed", result_message=msg
            )
            self.redis_tracker.update_job_state(
                job_id=job.id,
                account_uid=account_uid,
                status="failed",
                message=msg,
            )
            return False

        redroid_mgr = RedroidManager()
        container_id = None
        success = True
        err_msg = ""

        try:
            # 2. Update job status to running in DB & Redis
            AutomationJobRepository.update_status(
                job.id,
                status="running",
                current_step_index=0,
                current_action="initializing_container",
            )
            self.redis_tracker.update_job_state(
                job_id=job.id,
                account_uid=account_uid,
                status="running",
                current_step=0,
                current_action="initializing_container",
                message="Launching Redroid container with proxy...",
            )

            # 3. Provision / Start Redroid Container (reuse existing if stopped)
            inst = RedroidRepository.get_by_account_uid(account_uid)
            if inst and redroid_mgr.get_live_docker_status(inst.container_name) == "stopped":
                redroid_mgr.start_instance(inst.container_name, proxy_url=proxy.url)
                redroid_inst = inst
            elif inst and redroid_mgr.get_live_docker_status(inst.container_name) == "running":
                redroid_inst = inst
            else:
                redroid_inst = redroid_mgr.create_instance(account_uid=account_uid, proxy_url=proxy.url)

            container_id = redroid_inst.container_id

            AutomationJobRepository.update_status(
                job.id, status="running", container_id=container_id
            )

            # 4. Parse action steps
            actions = json.loads(job.actions_json)
            total_steps = len(actions)

            # 5. Execute action pipeline step-by-step
            for index, step in enumerate(actions):
                action_name = step.get("action")
                params = step.get("params", {})
                params["account_uid"] = account_uid

                logger.info(f"[Job-{job.id}] Step {index+1}/{total_steps}: {action_name}")

                # Update progress
                AutomationJobRepository.update_status(
                    job.id,
                    status="running",
                    current_step_index=index,
                    current_action=action_name,
                )
                self.redis_tracker.update_job_state(
                    job_id=job.id,
                    account_uid=account_uid,
                    status="running",
                    current_step=index + 1,
                    total_steps=total_steps,
                    current_action=action_name,
                    container_id=container_id,
                    message=f"Executing {action_name}",
                )

                # Execute action via router
                res = execute_action(action_name, redroid_inst.adb_port, params)
                if res.get("status") != "success":
                    success = False
                    err_msg = res.get("message", f"Step '{action_name}' failed")
                    logger.error(f"[Job-{job.id}] Action {action_name} failed: {err_msg}")
                    break

                time.sleep(2)  # Cooldown between steps

            if success:
                AutomationJobRepository.update_status(
                    job.id,
                    status="finished",
                    result_message="All scenario steps completed successfully",
                )
                self.redis_tracker.update_job_state(
                    job_id=job.id,
                    account_uid=account_uid,
                    status="finished",
                    current_step=total_steps,
                    total_steps=total_steps,
                    current_action="completed",
                    container_id=container_id,
                    message="Finished successfully",
                )
            else:
                AutomationJobRepository.update_status(
                    job.id, status="failed", result_message=err_msg
                )
                self.redis_tracker.update_job_state(
                    job_id=job.id,
                    account_uid=account_uid,
                    status="failed",
                    container_id=container_id,
                    message=f"Failed: {err_msg}",
                )

        except Exception as e:
            logger.exception(f"[Job-{job.id}] Exception during job execution: {e}")
            success = False
            err_msg = str(e)
            AutomationJobRepository.update_status(
                job.id, status="failed", result_message=err_msg
            )
            self.redis_tracker.update_job_state(
                job_id=job.id,
                account_uid=account_uid,
                status="failed",
                container_id=container_id or "",
                message=f"Error: {err_msg}",
            )

        finally:
            # 6. Stop Redroid Container to save system resources
            if container_id:
                logger.info(f"[Job-{job.id}] Stopping container {container_id} to release resources...")
                redroid_mgr.stop_instance(container_id)

            # 7. Release Proxy lock
            ProxyRepository.release_proxy_by_account_uid(account_uid)
            logger.info(f"[Job-{job.id}] Proxy released for account {account_uid}.")

        return success

    def run_batch(self, group_tag: Optional[str] = None):
        """Runs batch jobs dynamically throttled by min(available_proxies, user_threads)."""
        pending_jobs = AutomationJobRepository.list_jobs(group_tag=group_tag, status="pending")
        if not pending_jobs:
            logger.info(f"No pending jobs found for group_tag='{group_tag or 'all'}'")
            return

        # Auto-release stale/orphaned proxy locks from stopped or killed jobs
        ProxyRepository.release_stale_proxies()

        all_proxies = ProxyRepository.list_all()
        total_proxies = len(all_proxies)

        if total_proxies == 0:
            logger.error("No proxies registered in database! Please add proxies before running jobs.")
            return

        effective_concurrency = min(total_proxies, self.requested_threads, MAX_CONCURRENT_REDROID_CONTAINERS)
        logger.info(
            f"Starting batch runner: Requested Threads={self.requested_threads}, Total Proxies={total_proxies}, Max Allowed Containers={MAX_CONCURRENT_REDROID_CONTAINERS} -> Effective Concurrency = min({total_proxies}, {self.requested_threads}, {MAX_CONCURRENT_REDROID_CONTAINERS}) = {effective_concurrency}"
        )

        with ThreadPoolExecutor(max_workers=effective_concurrency) as executor:
            futures = [executor.submit(self.run_job_single, job) for job in pending_jobs]
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Worker thread error: {e}")

