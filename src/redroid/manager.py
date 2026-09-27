"""Redroid Container Lifecycle Manager."""

import os
import time
import logging
import subprocess
from typing import Optional, List, Dict
import docker
from docker.errors import NotFound, APIError

from pathlib import Path
from src.core.constants import (
    DEFAULT_REDROID_IMAGE,
    DEFAULT_ADB_START_PORT,
    DEFAULT_SCRCPY_START_PORT,
    DEFAULT_CONTAINER_PREFIX,
    MAX_CONCURRENT_REDROID_CONTAINERS,
    DEFAULT_FB_APK_PATH,
    FB_KATANA_PACKAGE,
    DATA_DIR,
)
from src.core.fingerprint import DeviceProfile, generate_device_profile
from src.core.models import RedroidInstance
from src.db.repository import RedroidRepository, DeviceProfileRepository
from src.automation.adb_client import ADBClient

logger = logging.getLogger(__name__)


from src.proxy.service import ProxyService
from src.redroid.proxy_configurator import ContainerProxyConfigurator


class RedroidManager:
    def __init__(self, image: str = DEFAULT_REDROID_IMAGE):
        self.image = image
        try:
            self.docker_client = docker.from_env()
        except Exception as e:
            logger.warning(f"Could not initialize Docker client via SDK: {e}. Subprocess fallback will be used.")
            self.docker_client = None

    @staticmethod
    def _is_port_occupied(port: int) -> bool:
        """Checks if a TCP port is currently occupied on the host."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def find_available_adb_port(self) -> int:
        """Finds an unused ADB port starting from DEFAULT_ADB_START_PORT, checking both DB and OS socket."""
        existing = RedroidRepository.list_all()
        used_ports = {inst.adb_port for inst in existing}
        port = DEFAULT_ADB_START_PORT
        while True:
            scrcpy_port = port + 2000
            if (
                port not in used_ports
                and not self._is_port_occupied(port)
                and not self._is_port_occupied(scrcpy_port)
            ):
                return port
            port += 1

    def get_total_running_containers(self) -> int:
        """Returns the count of currently running Redroid containers in Docker."""
        try:
            res = subprocess.run(
                ["docker", "ps", "--filter", f"name={DEFAULT_CONTAINER_PREFIX}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                running_list = [n.strip() for n in res.stdout.splitlines() if n.strip()]
                return len(running_list)
        except Exception as e:
            logger.warning(f"Error checking live running Docker containers: {e}")

        all_insts = RedroidRepository.list_all()
        return sum(1 for inst in all_insts if self.get_live_docker_status(inst.container_name) == "running")

    def evict_oldest_idle_container_if_needed(self, exclude_target: Optional[str] = None) -> bool:
        """
        If total running containers >= MAX_CONCURRENT_REDROID_CONTAINERS,
        evicts (stops) the oldest container that is currently IDLE (not actively executing an automation job).
        Returns True if an idle container was evicted or running count < max,
        False if limit reached and all running containers are actively executing jobs.
        """
        running_count = self.get_total_running_containers()
        if running_count < MAX_CONCURRENT_REDROID_CONTAINERS:
            return True

        from src.db.repository import AutomationJobRepository

        # Find account UIDs of jobs currently running automation steps
        active_jobs = AutomationJobRepository.list_jobs(status="running")
        active_uids = {job.account_uid for job in active_jobs if job.account_uid}

        # Query Docker for running redroid containers
        try:
            res = subprocess.run(
                ["docker", "ps", "--filter", f"name={DEFAULT_CONTAINER_PREFIX}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                running_names = [n.strip() for n in res.stdout.splitlines() if n.strip()]
            else:
                running_names = []
        except Exception as e:
            logger.warning(f"Error querying docker ps for eviction check: {e}")
            running_names = []

        if not running_names:
            all_insts = RedroidRepository.list_all()
            running_names = [
                inst.container_name
                for inst in all_insts
                if self.get_live_docker_status(inst.container_name) == "running"
            ]

        exclude_c_name, exclude_uid = (None, None)
        if exclude_target:
            exclude_c_name, exclude_uid = self.resolve_target(exclude_target)

        idle_candidates = []
        for c_name in running_names:
            resolved_name, acc_uid = self.resolve_target(c_name)

            if exclude_c_name and (resolved_name == exclude_c_name or c_name == exclude_c_name):
                continue
            if exclude_uid and acc_uid == exclude_uid:
                continue

            if acc_uid and acc_uid in active_uids:
                continue

            started_at = ""
            try:
                inspect_res = subprocess.run(
                    ["docker", "inspect", "--format={{.State.StartedAt}}", c_name],
                    capture_output=True,
                    text=True,
                )
                if inspect_res.returncode == 0:
                    started_at = inspect_res.stdout.strip()
            except Exception:
                pass

            idle_candidates.append({
                "container_name": c_name,
                "account_uid": acc_uid,
                "started_at": started_at,
            })

        if not idle_candidates:
            logger.warning(
                f"Limit reached ({running_count}/{MAX_CONCURRENT_REDROID_CONTAINERS}), but cannot auto-evict: All running containers are actively executing automation jobs."
            )
            return False

        # Sort by StartedAt (ISO 8601 string sort works chronologically, empty string goes first)
        idle_candidates.sort(key=lambda x: x["started_at"] or "0")
        oldest = idle_candidates[0]

        logger.info(
            f"Auto-evicting oldest IDLE container '{oldest['container_name']}' (UID: {oldest['account_uid']}, StartedAt: {oldest['started_at']}) to free slot for new container."
        )
        self.stop_instance(oldest["container_name"])
        return True

    def create_instance(
        self,
        account_uid: str,
        device_profile: Optional[DeviceProfile] = None,
        proxy_url: Optional[str] = None,
        apk_path: Optional[str] = None,
    ) -> RedroidInstance:
        """Spawns a new Redroid docker container with assigned device fingerprint, proxy, and Facebook APK."""
        running_count = self.get_total_running_containers()
        if running_count >= MAX_CONCURRENT_REDROID_CONTAINERS:
            evicted = self.evict_oldest_idle_container_if_needed(exclude_target=account_uid)
            if not evicted:
                msg = f"Cannot create container for UID {account_uid}: Maximum concurrent running container limit reached ({running_count}/{MAX_CONCURRENT_REDROID_CONTAINERS}) and all containers are actively executing jobs."
                logger.error(msg)
                raise RuntimeError(msg)

        if not device_profile:
            device_profile = generate_device_profile()

        DeviceProfileRepository.add(device_profile)

        # Acquire and rotate a Proxy URL for this account
        proxy_obj, parsed_proxy, proxy_msg = ProxyService.acquire_and_rotate_proxy(
            account_uid=account_uid, proxy_url_override=proxy_url
        )
        if parsed_proxy:
            logger.info(f"Assigned proxy {parsed_proxy['formatted_url']} to UID {account_uid}")
        else:
            logger.warning(f"Could not assign proxy for UID {account_uid}: {proxy_msg}")

        adb_port = self.find_available_adb_port()
        scrcpy_port = adb_port + 2000
        container_name = f"{DEFAULT_CONTAINER_PREFIX}{account_uid}"
        storage_dir = DATA_DIR / "containers" / account_uid
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Environment variables and build.prop parameters
        build_prop_params = device_profile.to_build_prop_dict()
        cmd_args = []
        for prop_key, prop_val in build_prop_params.items():
            cmd_args.append(f"{prop_key}={prop_val}")
        cmd_args.append(f"androidboot.redroid_width={device_profile.width}")
        cmd_args.append(f"androidboot.redroid_height={device_profile.height}")
        cmd_args.append(f"androidboot.redroid_dpi={device_profile.dpi}")
        cmd_args.append("androidboot.use_memfd=1")
        cmd_args.append("androidboot.redroid_gpu_mode=guest")

        logger.info(f"Creating Redroid container {container_name} on ADB port {adb_port}...")

        # Ensure any old container with the same name is removed
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

        # Construct Docker run command
        docker_cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--privileged",
            "-v", f"{storage_dir}:/data",
            "-p", f"{adb_port}:5555",
            "-p", f"{scrcpy_port}:8000",
            self.image
        ] + cmd_args

        try:
            res = subprocess.run(docker_cmd, capture_output=True, text=True, check=True)
            container_id = res.stdout.strip()[:12]
            logger.info(f"Container created successfully: {container_id}")

            instance = RedroidInstance(
                container_id=container_id,
                container_name=container_name,
                adb_port=adb_port,
                scrcpy_port=scrcpy_port,
                status="running",
                account_uid=account_uid,
                proxy_url=parsed_proxy["formatted_url"] if parsed_proxy else None,
                device_profile_id=device_profile.id,
            )
            RedroidRepository.add_or_update(instance)

            # Wait for Android OS to boot before applying post-boot configs
            adb_client = ADBClient(port=adb_port)
            logger.info(f"Waiting for Redroid OS (Port {adb_port}) to finish booting...")
            adb_client.wait_for_boot(timeout_sec=45)

            # Apply additional hardware identity props via ADB shell
            self._apply_post_boot_fingerprint(adb_port, device_profile)

            # Configure proxy inside Redroid if available
            if parsed_proxy:
                configurator = ContainerProxyConfigurator(f"127.0.0.1:{adb_port}")
                configurator.setup_proxy(parsed_proxy["formatted_url"])

            # Install Facebook APK automatically
            self._install_facebook_apk(adb_port, apk_path=apk_path)
            self.ensure_app_permissions(container_name)
            self.hide_virtual_keyboard(container_name)

            return instance
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create Redroid container: {e.stderr}")
            # Release proxy lock on failure
            ProxyService.release_proxy(account_uid)
            raise RuntimeError(f"Docker container creation failed: {e.stderr}")

    def _apply_post_boot_fingerprint(self, adb_port: int, profile: DeviceProfile):
        """Connects via ADB and applies Android ID, MAC, and device settings."""
        adb_target = f"127.0.0.1:{adb_port}"
        time.sleep(3)
        subprocess.run(["adb", "connect", adb_target], capture_output=True)

        # Set Android ID
        subprocess.run([
            "adb", "-s", adb_target, "shell",
            f"settings put secure android_id {profile.android_id}"
        ], capture_output=True)

        # Configure input method: disable on-screen virtual keyboard from popping up
        self.hide_virtual_keyboard(str(adb_port))

    def hide_virtual_keyboard(self, target: str) -> bool:
        """
        Disables virtual on-screen soft keyboard in Redroid container
        so that keyboard popup does not obscure screen during scrcpy view or automation.
        """
        c_name, acc_uid = self.resolve_target(target)
        inst = RedroidRepository.get_by_identifier(target)
        adb_port = inst.adb_port if inst else (int(target) if str(target).isdigit() and len(str(target)) <= 5 else None)

        success = False
        # 1. Primary approach: Docker exec directly as root (fastest and most reliable)
        try:
            cmd = [
                "docker", "exec", "-u", "0", c_name, "sh", "-c",
                "settings put secure show_ime_with_hard_keyboard 0; "
                "for pkg in $(pm list packages 2>/dev/null | grep -iE 'inputmethod|keyboard|gboard' | grep -v 'inputdevices' | cut -d: -f2); do "
                "  pm disable-user --user 0 \"$pkg\" 2>/dev/null; "
                "  pm disable \"$pkg\" 2>/dev/null; "
                "done; "
                "for ime in $(ime list -a -s 2>/dev/null); do "
                "  ime disable \"$ime\" 2>/dev/null; "
                "done"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                logger.debug(f"Disabled virtual keyboard via Docker for '{c_name}'.")
                success = True
        except Exception as e:
            logger.debug(f"Docker exec keyboard hide skipped for {c_name}: {e}")

        # 2. Fallback approach via ADB if docker exec failed or container name unknown
        if not success and adb_port:
            adb_target = f"127.0.0.1:{adb_port}"
            try:
                subprocess.run([
                    "adb", "-s", adb_target, "shell",
                    "su 0 sh -c 'settings put secure show_ime_with_hard_keyboard 0; "
                    "for pkg in $(pm list packages 2>/dev/null | grep -iE \"inputmethod|keyboard|gboard\" | grep -v \"inputdevices\" | cut -d: -f2); do "
                    "  pm disable-user --user 0 \"$pkg\" 2>/dev/null; "
                    "  pm disable \"$pkg\" 2>/dev/null; "
                    "done; "
                    "for ime in $(ime list -a -s 2>/dev/null); do "
                    "  ime disable \"$ime\" 2>/dev/null; "
                    "done'"
                ], capture_output=True, timeout=10)
                success = True
            except Exception as e:
                logger.debug(f"ADB keyboard hide skipped for {adb_target}: {e}")

        return success

    def show_virtual_keyboard(self, target: str) -> bool:
        """
        Re-enables virtual on-screen soft keyboard in Redroid container if needed.
        """
        c_name, acc_uid = self.resolve_target(target)
        inst = RedroidRepository.get_by_identifier(target)
        adb_port = inst.adb_port if inst else (int(target) if str(target).isdigit() and len(str(target)) <= 5 else None)

        success = False
        try:
            cmd = [
                "docker", "exec", "-u", "0", c_name, "sh", "-c",
                "settings put secure show_ime_with_hard_keyboard 1; "
                "for pkg in $(pm list packages -d 2>/dev/null | grep -iE 'inputmethod|keyboard|gboard' | grep -v 'inputdevices' | cut -d: -f2); do "
                "  pm enable \"$pkg\" 2>/dev/null; "
                "  pm enable --user 0 \"$pkg\" 2>/dev/null; "
                "done; "
                "for ime in $(ime list -a -s 2>/dev/null); do "
                "  ime enable \"$ime\" 2>/dev/null; "
                "  ime set \"$ime\" 2>/dev/null; "
                "done"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                success = True
        except Exception as e:
            logger.debug(f"Docker exec keyboard show skipped for {c_name}: {e}")

        if not success and adb_port:
            adb_target = f"127.0.0.1:{adb_port}"
            try:
                subprocess.run([
                    "adb", "-s", adb_target, "shell",
                    "su 0 sh -c 'settings put secure show_ime_with_hard_keyboard 1; "
                    "for pkg in $(pm list packages -d 2>/dev/null | grep -iE \"inputmethod|keyboard|gboard\" | grep -v \"inputdevices\" | cut -d: -f2); do "
                    "  pm enable \"$pkg\" 2>/dev/null; "
                    "  pm enable --user 0 \"$pkg\" 2>/dev/null; "
                    "done; "
                    "for ime in $(ime list -a -s 2>/dev/null); do "
                    "  ime enable \"$ime\" 2>/dev/null; "
                    "  ime set \"$ime\" 2>/dev/null; "
                    "done'"
                ], capture_output=True, timeout=10)
                success = True
            except Exception as e:
                logger.debug(f"ADB keyboard show skipped for {adb_target}: {e}")

        return success

    def is_virtual_keyboard_hidden(self, target: str) -> bool:
        """Checks whether the on-screen virtual keyboard is currently disabled."""
        c_name, _ = self.resolve_target(target)
        try:
            res = subprocess.run(
                ["docker", "exec", "-u", "0", c_name, "sh", "-c",
                 "pm list packages -e 2>/dev/null | grep -iE 'inputmethod|keyboard|gboard' | grep -v 'inputdevices' | cut -d: -f2"],
                capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                enabled_pkgs = res.stdout.strip()
                return len(enabled_pkgs) == 0
        except Exception:
            pass
        return False

    def ensure_app_permissions(self, container_name: str, package_name: str = FB_KATANA_PACKAGE) -> bool:
        """
        Ensures that private app data directories inside the Redroid container
        are correctly owned by the application's sandboxed Android UID (e.g. u0_a116 / 10116)
        and have mode 0700, preventing EACCES permission denied crashes.
        """
        script = f'''
        UID_LINE=$(grep 'name="{package_name}"' /data/system/packages.xml 2>/dev/null)
        if [ -n "$UID_LINE" ]; then
            APP_UID=$(echo "$UID_LINE" | sed -n 's/.*userId="\\([0-9]*\\)".*/\\1/p')
            if [ -n "$APP_UID" ]; then
                chown -R $APP_UID:$APP_UID /data/data/{package_name} 2>/dev/null
                chmod 700 /data/data/{package_name} 2>/dev/null
                if [ -d /data/user_de/0/{package_name} ]; then
                    chown -R $APP_UID:$APP_UID /data/user_de/0/{package_name} 2>/dev/null
                    chmod 700 /data/user_de/0/{package_name} 2>/dev/null
                fi
                if [ -d /data/misc/profiles/cur/0/{package_name} ]; then
                    chown -R $APP_UID:$APP_UID /data/misc/profiles/cur/0/{package_name} 2>/dev/null
                    chmod 700 /data/misc/profiles/cur/0/{package_name} 2>/dev/null
                fi
            fi
        fi
        # Ensure media storage directories exist and are accessible
        mkdir -p /data/media/0/DCIM/Camera /data/media/0/Pictures /data/media/0/Download 2>/dev/null
        chown -R media_rw:media_rw /data/media/0 2>/dev/null
        chmod -R 777 /data/media/0 2>/dev/null
        chmod -R 777 /sdcard/DCIM 2>/dev/null
        chmod -R 777 /sdcard/Pictures 2>/dev/null
        chmod -R 777 /sdcard/Download 2>/dev/null

        # Pre-grant storage & media runtime permissions
        pm grant {package_name} android.permission.READ_EXTERNAL_STORAGE 2>/dev/null
        pm grant {package_name} android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null
        pm grant {package_name} android.permission.ACCESS_MEDIA_LOCATION 2>/dev/null
        pm grant {package_name} android.permission.READ_MEDIA_IMAGES 2>/dev/null
        pm grant {package_name} android.permission.READ_MEDIA_VIDEO 2>/dev/null
        exit 0
        '''
        try:
            res = subprocess.run(
                ["docker", "exec", "-u", "0", container_name, "sh", "-c", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0:
                logger.info(f"Verified and ensured app permissions for '{package_name}' in container '{container_name}'.")
                return True
            else:
                logger.warning(f"ensure_app_permissions returned code {res.returncode}: {res.stderr.strip()}")
                return False
        except Exception as e:
            logger.warning(f"Failed to ensure permissions for '{package_name}' in container '{container_name}': {e}")
            return False

    def _install_facebook_apk(self, adb_port: int, apk_path: Optional[str] = None):
        """Automatically installs Facebook APK into Redroid container via ADB."""
        target_apk = Path(apk_path) if apk_path else DEFAULT_FB_APK_PATH
        client = ADBClient(port=adb_port)

        logger.info(f"Waiting for Redroid (Port {adb_port}) to finish booting before installing APK...")
        if not client.wait_for_boot(timeout_sec=45):
            logger.warning(f"Redroid container on port {adb_port} did not complete boot in time.")
            return

        if client.is_app_installed(FB_KATANA_PACKAGE):
            logger.info(f"Facebook app ({FB_KATANA_PACKAGE}) is already installed on port {adb_port}.")
            return

        if not target_apk.exists():
            logger.warning(
                f"Facebook APK not found at '{target_apk}'. "
                f"Please place the Facebook APK at '{DEFAULT_FB_APK_PATH}' or specify --apk <path>."
            )
            return

        logger.info(f"Installing Facebook APK '{target_apk}' on port {adb_port}...")
        client.install_apk(str(target_apk))

    def install_apk(self, target: str, apk_path: str, auto_start: bool = True) -> bool:
        """
        Installs an APK file onto a specified Redroid container (accepts UID, Port, Name, or ID).
        If container is currently stopped, automatically starts it if auto_start=True.
        """
        c_name, acc_uid = self.resolve_target(target)
        inst = RedroidRepository.get_by_identifier(target)
        if not inst and acc_uid:
            inst = RedroidRepository.get_by_account_uid(acc_uid)

        if not inst:
            # Fallback if target is numeric ADB port
            if target.isdigit() and len(target) <= 5:
                adb_port = int(target)
                c_name = f"port_{adb_port}"
            else:
                from src.db.repository import AccountRepository
                acc = AccountRepository.get_by_uid(acc_uid) if acc_uid else None
                if acc and auto_start:
                    logger.info(
                        f"Tài khoản UID '{acc_uid}' ({acc.username}) chưa có máy ảo Redroid. "
                        f"Đang tự động khởi tạo máy ảo mới và cài đặt APK..."
                    )
                    try:
                        inst = self.create_instance(account_uid=acc_uid, apk_path=apk_path)
                        AccountRepository.bind_container(acc_uid, inst.container_id, inst.device_profile_id or "")
                        logger.info(f"Đã tự động khởi tạo thành công máy ảo cho UID '{acc_uid}' (Port {inst.adb_port}) và cài đặt APK.")
                        return True
                    except Exception as e:
                        logger.error(f"Tự động tạo máy ảo cho UID '{acc_uid}' thất bại: {e}")
                        return False
                elif acc:
                    logger.error(
                        f"Tài khoản UID '{acc_uid}' ({acc.username}) chưa được khởi tạo máy ảo Redroid trong Docker. "
                        f"Vui lòng tạo máy ảo trước bằng lệnh: python main-cli.py redroid create --uid {acc_uid}"
                    )
                    return False
                else:
                    logger.error(f"Không tìm thấy máy ảo Redroid hoặc tài khoản tương ứng với mục tiêu '{target}'.")
                    return False
        else:
            c_name = inst.container_name
            adb_port = inst.adb_port

        live_status = self.get_live_docker_status(c_name)
        if live_status != "running":
            if auto_start:
                if live_status == "not_found" and acc_uid:
                    logger.info(f"Container '{c_name}' không tồn tại trong Docker. Đang tự động tạo lại máy ảo...")
                    try:
                        from src.db.repository import AccountRepository
                        inst = self.create_instance(account_uid=acc_uid, apk_path=apk_path)
                        AccountRepository.bind_container(acc_uid, inst.container_id, inst.device_profile_id or "")
                        logger.info(f"Đã tự động tạo lại thành công máy ảo cho UID '{acc_uid}' (Port {inst.adb_port}) và cài đặt APK.")
                        return True
                    except Exception as e:
                        logger.error(f"Tạo lại máy ảo cho UID '{acc_uid}' thất bại: {e}")
                        return False

                logger.info(f"Container '{c_name}' is currently stopped. Auto-starting it to install APK...")
                self.start_instance(c_name)
            else:
                logger.error(f"Container '{c_name}' is not running.")
                return False

        target_apk = Path(apk_path)
        if not target_apk.exists():
            msg = f"APK file not found at path '{target_apk}'"
            logger.error(msg)
            raise FileNotFoundError(msg)

        client = ADBClient(port=adb_port)
        logger.info(f"Connecting to container on ADB port {adb_port} to install APK '{target_apk.name}'...")
        if not client.wait_for_boot(timeout_sec=35):
            logger.warning(f"Redroid container on port {adb_port} is not responding or did not boot in time.")
            return False

        logger.info(f"Installing APK '{target_apk}' on ADB port {adb_port}...")
        ok = client.install_apk(str(target_apk))
        if ok:
            self.ensure_app_permissions(c_name)
        return ok

    def install_apk_batch(self, targets: List[str], apk_path: str) -> Dict[str, bool]:
        """Installs an APK file onto multiple Redroid containers sequentially."""
        results = {}
        for tgt in targets:
            try:
                ok = self.install_apk(tgt, apk_path=apk_path, auto_start=True)
                results[tgt] = ok
            except Exception as e:
                logger.error(f"Failed to install APK for target '{tgt}': {e}")
                results[tgt] = False
        return results

    def resolve_target(self, target: str) -> Tuple[str, Optional[str]]:
        """
        Resolves container name and account UID from container_id, name, account_uid, or ADB port.
        Returns: (container_name_or_id, account_uid)
        """
        record = RedroidRepository.get_by_identifier(target)
        if record:
            return record.container_name, record.account_uid
        if target.startswith(DEFAULT_CONTAINER_PREFIX):
            return target, target.replace(DEFAULT_CONTAINER_PREFIX, "")
        if len(target) > 5 and target.isdigit():
            # Looks like a Facebook UID
            return f"{DEFAULT_CONTAINER_PREFIX}{target}", target
        return target, None

    def get_live_docker_status(self, container_name_or_id: str) -> str:
        """Queries Docker for actual live status (running, exited, created, missing)."""
        res = subprocess.run(
            ["docker", "inspect", "--format={{.State.Status}}", container_name_or_id],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            status = res.stdout.strip().lower()
            return "running" if status == "running" else "stopped"
        return "not_found"

    def stop_instance(self, target: str):
        """Stops a Redroid container, updates DB status, and releases bound proxy."""
        c_name, acc_uid = self.resolve_target(target)
        subprocess.run(["docker", "stop", c_name], capture_output=True)
        RedroidRepository.update_status(c_name, "stopped")
        if acc_uid:
            ProxyService.release_proxy(acc_uid)
        logger.info(f"Container '{c_name}' stopped and proxy released.")

    def stop_all_instances(self) -> int:
        """Stops all currently running Redroid containers, updates DB statuses, and releases all bound proxies."""
        try:
            res = subprocess.run(
                ["docker", "ps", "--filter", f"name={DEFAULT_CONTAINER_PREFIX}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                running_names = [n.strip() for n in res.stdout.splitlines() if n.strip()]
            else:
                running_names = []
        except Exception as e:
            logger.warning(f"Error querying running docker containers: {e}")
            running_names = []

        stopped_count = 0
        for c_name in running_names:
            self.stop_instance(c_name)
            stopped_count += 1

        logger.info(f"Stopped all {stopped_count} running Redroid containers.")
        return stopped_count

    def start_instance(self, target: str, proxy_url: Optional[str] = None):
        """Starts an existing Redroid container, acquires/configures proxy, and updates DB status."""
        c_name, acc_uid = self.resolve_target(target)

        # Check if container exists in Docker
        docker_status = self.get_live_docker_status(c_name)
        if docker_status == "running":
            logger.info(f"Container '{c_name}' is already running.")
            return
        elif docker_status == "not_found":
            from src.db.repository import AccountRepository
            acc = AccountRepository.get_by_uid(acc_uid) if acc_uid else None
            if acc:
                logger.info(f"Container '{c_name}' chưa có trong Docker. Đang tự động khởi tạo máy ảo mới cho UID '{acc_uid}' ({acc.username})...")
                new_inst = self.create_instance(account_uid=acc_uid, proxy_url=proxy_url)
                AccountRepository.bind_container(acc_uid, new_inst.container_id, new_inst.device_profile_id or "")
                logger.info(f"Đã tự động khởi tạo thành công máy ảo cho UID '{acc_uid}' (Port {new_inst.adb_port}).")
                return
            else:
                uid_hint = f" --uid {acc_uid}" if acc_uid else ""
                msg = f"Container '{c_name}' không tồn tại trong Docker. Vui lòng tạo máy ảo trước bằng lệnh: python main-cli.py redroid create{uid_hint}"
                logger.error(msg)
                raise RuntimeError(msg)

        running_count = self.get_total_running_containers()
        if running_count >= MAX_CONCURRENT_REDROID_CONTAINERS:
            evicted = self.evict_oldest_idle_container_if_needed(exclude_target=c_name)
            if not evicted:
                msg = f"Cannot start container '{c_name}': Maximum concurrent running container limit reached ({running_count}/{MAX_CONCURRENT_REDROID_CONTAINERS}) and all containers are actively executing jobs."
                logger.error(msg)
                raise RuntimeError(msg)

        # Resolve proxy_url target if passed as ID or Name
        if proxy_url and acc_uid:
            from src.db.repository import ProxyRepository
            if str(proxy_url).isdigit():
                proxies = ProxyRepository.list_all()
                matched = [p for p in proxies if p.id == int(proxy_url)]
                if matched:
                    proxy_url = matched[0].url
            else:
                proxies = ProxyRepository.list_all()
                matched = [p for p in proxies if p.name == proxy_url or p.url == proxy_url]
                if matched:
                    proxy_url = matched[0].url

        start_res = subprocess.run(["docker", "start", c_name], capture_output=True, text=True)
        if start_res.returncode != 0:
            err = start_res.stderr.strip() or f"Failed to start container '{c_name}'"
            logger.error(f"Cannot start container '{c_name}': {err}")
            raise RuntimeError(f"Cannot start container '{c_name}': {err}")

        RedroidRepository.update_status(c_name, "running")
        logger.info(f"Container '{c_name}' started.")

        inst = RedroidRepository.get_by_identifier(c_name)
        if inst and inst.adb_port:
            adb_client = ADBClient(port=inst.adb_port)
            logger.info(f"Waiting for container '{c_name}' (Port {inst.adb_port}) to finish booting...")
            adb_client.wait_for_boot(timeout_sec=30)

        # Ensure correct app sandbox permissions for Facebook app
        self.ensure_app_permissions(c_name)
        self.hide_virtual_keyboard(c_name)

        # Acquire and configure proxy if account_uid exists
        if acc_uid:
            proxy_obj, parsed_proxy, proxy_msg = ProxyService.acquire_and_rotate_proxy(
                account_uid=acc_uid, proxy_url_override=proxy_url
            )
            if parsed_proxy:
                if inst:
                    inst.proxy_url = parsed_proxy["formatted_url"]
                    RedroidRepository.add_or_update(inst)

                if inst and inst.adb_port:
                    configurator = ContainerProxyConfigurator(f"127.0.0.1:{inst.adb_port}")
                    configurator.setup_proxy(parsed_proxy["formatted_url"])
                logger.info(f"Assigned and configured proxy '{parsed_proxy['formatted_url']}' for container '{c_name}'.")
            else:
                logger.warning(f"Could not assign proxy when starting container '{c_name}': {proxy_msg}")

    def _delete_container_storage(self, storage_dir: Path):
        """Deletes container data directory on disk, bypassing root ownership created by Docker."""
        if not storage_dir.exists():
            return

        import shutil
        # 1. Try standard Python rmtree first
        try:
            shutil.rmtree(storage_dir)
            logger.info(f"Deleted container data directory at '{storage_dir}'.")
            return
        except (PermissionError, OSError):
            pass

        # 2. Use Docker helper to purge root-owned directory cleanly
        parent_dir = storage_dir.parent.resolve()
        dir_name = storage_dir.name
        try:
            res = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "-v", f"{parent_dir}:/parent",
                    "alpine:latest",
                    "rm", "-rf", f"/parent/{dir_name}"
                ],
                capture_output=True,
                timeout=15,
            )
            if res.returncode == 0 and not storage_dir.exists():
                logger.info(f"Deleted container data directory via Docker cleanup: '{storage_dir}'.")
                return
        except Exception as e:
            logger.warning(f"Docker cleanup attempt failed: {e}")

        # 3. Fallback: try sudo rm -rf if passwordless sudo or standard cleanup
        try:
            subprocess.run(["sudo", "-n", "rm", "-rf", str(storage_dir)], capture_output=True)
        except Exception:
            pass

        if storage_dir.exists():
            logger.warning(f"Could not delete container data directory '{storage_dir}' due to root permissions.")

    def remove_instance(self, target: str):
        """Stops and removes a Redroid container, cleans DB record, releases proxy, and deletes container data directory."""
        c_name, acc_uid = self.resolve_target(target)
        if not acc_uid:
            inst = RedroidRepository.get_by_identifier(target)
            if inst and inst.account_uid:
                acc_uid = inst.account_uid
            elif target.isdigit() and len(target) > 5:
                acc_uid = target

        subprocess.run(["docker", "rm", "-f", c_name], capture_output=True)
        if acc_uid:
            ProxyService.release_proxy(acc_uid)
            storage_dir = DATA_DIR / "containers" / acc_uid
            self._delete_container_storage(storage_dir)

        RedroidRepository.delete_by_container(c_name)
        logger.info(f"Container '{c_name}' removed from Docker, DB, and Disk.")


