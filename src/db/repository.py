"""Database repositories for Accounts, Proxies, Device Profiles, and Redroid Instances."""

import json
import threading
from typing import List, Optional, Union, Dict, Any
from src.db.database import get_db_cursor
from src.core.models import Account, Proxy, RedroidInstance, AutomationTask, AccountStatus, AutomationJob, JobStatus
from src.core.fingerprint import DeviceProfile


class AccountRepository:
    @staticmethod
    def add(account: Account) -> Account:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO accounts (uid, username, password, two_fa, email, email_password, status, group_id, note, category, transaction_type, proxy_id, container_id, device_profile_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    username=excluded.username,
                    password=excluded.password,
                    two_fa=excluded.two_fa,
                    email=excluded.email,
                    email_password=excluded.email_password,
                    status=excluded.status,
                    group_id=excluded.group_id,
                    note=excluded.note,
                    category=excluded.category,
                    transaction_type=excluded.transaction_type,
                    updated_at=CURRENT_TIMESTAMP;
            """,
                (
                    account.uid,
                    account.username,
                    account.password,
                    account.two_fa,
                    account.email,
                    account.email_password,
                    account.status.value,
                    account.group_id,
                    account.note,
                    account.category,
                    account.transaction_type,
                    account.proxy_id,
                    account.container_id,
                    account.device_profile_id,
                ),
            )
            account.id = cursor.lastrowid
            return account

    @staticmethod
    def get_by_uid(uid: str) -> Optional[Account]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM accounts WHERE uid = ?", (uid,))
            row = cursor.fetchone()
            if row:
                return Account(**dict(row))
            return None

    @staticmethod
    def get_by_username(username: str) -> Optional[Account]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM accounts WHERE username = ?", (username,))
            row = cursor.fetchone()
            if row:
                return Account(**dict(row))
            return None

    @staticmethod
    def list_all(
        status: Optional[str] = None, group_id: Optional[int] = None, limit: int = 100
    ) -> List[Account]:
        with get_db_cursor() as cursor:
            query = "SELECT * FROM accounts WHERE 1=1"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if group_id is not None:
                query += " AND group_id = ?"
                params.append(group_id)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [Account(**dict(row)) for row in rows]

    @staticmethod
    def list_by_group(group_id: int, status: Optional[str] = None, limit: int = 1000) -> List[Account]:
        return AccountRepository.list_all(status=status, group_id=group_id, limit=limit)

    @staticmethod
    def update_status(uid: str, status: AccountStatus, note: Optional[str] = None):
        with get_db_cursor() as cursor:
            if note:
                cursor.execute(
                    "UPDATE accounts SET status = ?, note = ?, updated_at = CURRENT_TIMESTAMP WHERE uid = ?",
                    (status.value, note, uid),
                )
            else:
                cursor.execute(
                    "UPDATE accounts SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE uid = ?",
                    (status.value, uid),
                )

    @staticmethod
    def bind_container(uid: str, container_id: str, device_profile_id: str):
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE accounts SET container_id = ?, device_profile_id = ?, updated_at = CURRENT_TIMESTAMP WHERE uid = ?",
                (container_id, device_profile_id, uid),
            )

    @staticmethod
    def get_by_id_or_uid(target: str) -> Optional[Account]:
        with get_db_cursor() as cursor:
            if str(target).isdigit():
                cursor.execute("SELECT * FROM accounts WHERE id = ? OR uid = ?", (int(target), str(target)))
            else:
                cursor.execute("SELECT * FROM accounts WHERE uid = ? OR username = ?", (target, target))
            row = cursor.fetchone()
            if row:
                return Account(**dict(row))
            return None

    @staticmethod
    def delete(target: str) -> bool:
        acc = AccountRepository.get_by_id_or_uid(target)
        if not acc:
            return False
        with get_db_cursor() as cursor:
            cursor.execute("DELETE FROM accounts WHERE uid = ?", (acc.uid,))
            cursor.execute("DELETE FROM automation_jobs WHERE account_uid = ?", (acc.uid,))
            cursor.execute("DELETE FROM automation_tasks WHERE account_uid = ?", (acc.uid,))
        return True



class DeviceProfileRepository:
    @staticmethod
    def add(profile: DeviceProfile):
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO device_profiles (id, brand, manufacturer, model, product, device, board, hardware, fingerprint, android_id, imei, mac_address, serial, width, height, dpi, locale, timezone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    brand=excluded.brand,
                    model=excluded.model,
                    android_id=excluded.android_id,
                    imei=excluded.imei;
            """,
                (
                    profile.id,
                    profile.brand,
                    profile.manufacturer,
                    profile.model,
                    profile.product,
                    profile.device,
                    profile.board,
                    profile.hardware,
                    profile.fingerprint,
                    profile.android_id,
                    profile.imei,
                    profile.mac_address,
                    profile.serial,
                    profile.width,
                    profile.height,
                    profile.dpi,
                    profile.locale,
                    profile.timezone,
                ),
            )

    @staticmethod
    def get_by_id(profile_id: str) -> Optional[DeviceProfile]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM device_profiles WHERE id = ?", (profile_id,))
            row = cursor.fetchone()
            if row:
                return DeviceProfile(**dict(row))
            return None


class ProxyRepository:
    @staticmethod
    def add(proxy: Proxy) -> Proxy:
        with get_db_cursor() as cursor:
            status_val = proxy.status.value if hasattr(proxy.status, 'value') else str(proxy.status)
            cursor.execute(
                """
                INSERT INTO proxies (name, url, status, current_proxy_http, assigned_account_uid)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    assigned_account_uid=COALESCE(excluded.assigned_account_uid, proxies.assigned_account_uid);
            """,
                (
                    proxy.name,
                    proxy.url,
                    status_val,
                    proxy.current_proxy_http,
                    proxy.assigned_account_uid,
                ),
            )
            cursor.execute("SELECT id FROM proxies WHERE url = ?", (proxy.url,))
            row = cursor.fetchone()
            if row:
                proxy.id = row["id"]
            return proxy

    _lock = threading.Lock()

    @staticmethod
    def acquire_available_proxy(account_uid: str) -> Optional[Proxy]:
        """Atomically locks an available Proxy URL for an account UID."""
        with ProxyRepository._lock:
            with get_db_cursor() as cursor:
                # 1. First check if this account already has an assigned proxy
                cursor.execute(
                    """
                    SELECT * FROM proxies 
                    WHERE assigned_account_uid = ? 
                      AND status != 'unavailable' 
                    LIMIT 1
                    """,
                    (account_uid,),
                )
                row = cursor.fetchone()
                if row:
                    proxy = Proxy(**dict(row))
                    if proxy.status != "working":
                        cursor.execute(
                            "UPDATE proxies SET status = 'working' WHERE id = ?",
                            (proxy.id,),
                        )
                        proxy.status = "working"
                    return proxy

                # 2. Otherwise find a proxy that is strictly available AND unassigned
                cursor.execute(
                    """
                    SELECT * FROM proxies 
                    WHERE status = 'available' 
                      AND (assigned_account_uid IS NULL OR assigned_account_uid = '')
                    ORDER BY id ASC LIMIT 1
                    """
                )
                row = cursor.fetchone()
                if not row:
                    return None

                proxy = Proxy(**dict(row))
                cursor.execute(
                    "UPDATE proxies SET status = 'working', assigned_account_uid = ? WHERE id = ?",
                    (account_uid, proxy.id),
                )
                proxy.status = "working"
                proxy.assigned_account_uid = account_uid
                return proxy

    @staticmethod
    def release_proxy_by_id(proxy_id: int):
        """Releases a specific proxy by ID back to available and unassigned."""
        with ProxyRepository._lock:
            with get_db_cursor() as cursor:
                cursor.execute(
                    "UPDATE proxies SET status = 'available', assigned_account_uid = NULL WHERE id = ?",
                    (proxy_id,),
                )

    @staticmethod
    def release_proxy_by_account_uid(account_uid: str):
        """Releases all proxies currently bound to an account UID back to available."""
        with ProxyRepository._lock:
            with get_db_cursor() as cursor:
                cursor.execute(
                    "UPDATE proxies SET status = 'available', assigned_account_uid = NULL WHERE assigned_account_uid = ?",
                    (account_uid,),
                )

    @staticmethod
    def release_all_unassigned_proxies():
        """Resets all unassigned proxies back to 'available'."""
        with ProxyRepository._lock:
            with get_db_cursor() as cursor:
                cursor.execute(
                    "UPDATE proxies SET status = 'available' WHERE (assigned_account_uid IS NULL OR assigned_account_uid = '') AND status != 'unavailable'"
                )

    @staticmethod
    def release_stale_proxies():
        """
        Releases proxies that are marked 'working' or assigned to accounts
        that do not have an active running automation job in SQLite.
        """
        with ProxyRepository._lock:
            with get_db_cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proxies 
                    SET status = 'available', assigned_account_uid = NULL 
                    WHERE status != 'unavailable' 
                      AND (
                        assigned_account_uid IS NULL 
                        OR assigned_account_uid = '' 
                        OR assigned_account_uid NOT IN (
                            SELECT account_uid FROM automation_jobs WHERE status = 'running'
                        )
                      )
                    """
                )

    @staticmethod
    def release_all_proxies():
        """Force-resets all proxies back to 'available' and unassigned."""
        with ProxyRepository._lock:
            with get_db_cursor() as cursor:
                cursor.execute(
                    "UPDATE proxies SET status = 'available', assigned_account_uid = NULL WHERE status != 'unavailable'"
                )

    @staticmethod
    def set_status(proxy_id_or_url: str, status: str):
        """Updates proxy status ('available', 'working', 'unavailable')."""
        with get_db_cursor() as cursor:
            if str(proxy_id_or_url).isdigit():
                cursor.execute(
                    "UPDATE proxies SET status = ? WHERE id = ?",
                    (status, int(proxy_id_or_url)),
                )
            else:
                cursor.execute(
                    "UPDATE proxies SET status = ? WHERE url = ?",
                    (status, proxy_id_or_url),
                )

    @staticmethod
    def update_current_proxy_http(proxy_id_or_url: Union[int, str], current_proxy_http: str):
        """Stores the rotated IP:PORT string and updates timestamp."""
        with get_db_cursor() as cursor:
            if isinstance(proxy_id_or_url, int) or str(proxy_id_or_url).isdigit():
                cursor.execute(
                    "UPDATE proxies SET current_proxy_http = ?, last_rotated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (current_proxy_http, int(proxy_id_or_url)),
                )
            else:
                cursor.execute(
                    "UPDATE proxies SET current_proxy_http = ?, last_rotated_at = CURRENT_TIMESTAMP WHERE url = ?",
                    (current_proxy_http, str(proxy_id_or_url)),
                )

    @staticmethod
    def list_all() -> List[Proxy]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM proxies ORDER BY id ASC")
            rows = cursor.fetchall()
            return [Proxy(**dict(row)) for row in rows]

    @staticmethod
    def delete(target: str) -> bool:
        with get_db_cursor() as cursor:
            if str(target).isdigit():
                cursor.execute("DELETE FROM proxies WHERE id = ?", (int(target),))
            else:
                cursor.execute("DELETE FROM proxies WHERE name = ? OR url = ?", (target, target))
            return cursor.rowcount > 0



class RedroidRepository:
    @staticmethod
    def add_or_update(instance: RedroidInstance):
        with get_db_cursor() as cursor:
            # Clean up any previous container records for this account_uid or container_name
            if instance.account_uid:
                cursor.execute(
                    "DELETE FROM redroid_instances WHERE (account_uid = ? OR container_name = ?) AND container_id != ?",
                    (instance.account_uid, instance.container_name, instance.container_id),
                )
            else:
                cursor.execute(
                    "DELETE FROM redroid_instances WHERE container_name = ? AND container_id != ?",
                    (instance.container_name, instance.container_id),
                )

            cursor.execute(
                """
                INSERT INTO redroid_instances (container_id, container_name, adb_port, scrcpy_port, status, account_uid, proxy_url, device_profile_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(container_id) DO UPDATE SET
                    container_name=excluded.container_name,
                    adb_port=excluded.adb_port,
                    scrcpy_port=excluded.scrcpy_port,
                    status=excluded.status,
                    account_uid=excluded.account_uid,
                    proxy_url=excluded.proxy_url,
                    device_profile_id=excluded.device_profile_id;
            """,
                (
                    instance.container_id,
                    instance.container_name,
                    instance.adb_port,
                    instance.scrcpy_port,
                    instance.status,
                    instance.account_uid,
                    instance.proxy_url,
                    instance.device_profile_id,
                ),
            )

    @staticmethod
    def get_by_account_uid(account_uid: str) -> Optional[RedroidInstance]:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM redroid_instances WHERE account_uid = ?", (account_uid,)
            )
            row = cursor.fetchone()
            if row:
                return RedroidInstance(**dict(row))
            return None

    @staticmethod
    def list_all() -> List[RedroidInstance]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM redroid_instances ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [RedroidInstance(**dict(row)) for row in rows]

    @staticmethod
    def update_status(container_name_or_id: str, status: str):
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE redroid_instances SET status = ? WHERE container_id = ? OR container_name = ? OR account_uid = ?",
                (status, container_name_or_id, container_name_or_id, container_name_or_id),
            )

    @staticmethod
    def get_by_identifier(target: str) -> Optional[RedroidInstance]:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM redroid_instances WHERE container_id = ? OR container_name = ? OR account_uid = ? OR adb_port = ?",
                (target, target, target, target),
            )
            row = cursor.fetchone()
            if row:
                return RedroidInstance(**dict(row))
            return None

    @staticmethod
    def delete_by_container(container_name_or_id: str):
        with get_db_cursor() as cursor:
            cursor.execute(
                "DELETE FROM redroid_instances WHERE container_id = ? OR container_name = ? OR account_uid = ?",
                (container_name_or_id, container_name_or_id, container_name_or_id),
            )


class SettingRepository:
    @staticmethod
    def get(name: str, default: str = "") -> str:
        """Retrieves a setting value by name."""
        with get_db_cursor() as cursor:
            cursor.execute("SELECT value FROM settings WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row and row["value"] is not None:
                return row["value"]
            return default

    @staticmethod
    def set(name: str, value: str):
        """Sets or updates a setting value."""
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO settings (name, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    value=excluded.value,
                    updated_at=CURRENT_TIMESTAMP;
            """,
                (name, value),
            )

    @staticmethod
    def list_all() -> List[dict]:
        """Lists all system settings."""
        with get_db_cursor() as cursor:
            cursor.execute("SELECT name, value, updated_at FROM settings ORDER BY id ASC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


class AutomationJobRepository:
    @staticmethod
    def create(job: AutomationJob) -> AutomationJob:
        with get_db_cursor() as cursor:
            status_val = job.status.value if hasattr(job.status, 'value') else str(job.status)
            cursor.execute(
                """
                INSERT INTO automation_jobs (name, group_tag, account_uid, actions_json, current_step_index, current_action, status, container_id, result_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.name,
                    job.group_tag,
                    job.account_uid,
                    job.actions_json,
                    job.current_step_index,
                    job.current_action,
                    status_val,
                    job.container_id,
                    job.result_message,
                ),
            )
            job.id = cursor.lastrowid
            return job

    @staticmethod
    def get_by_id(job_id: int) -> Optional[AutomationJob]:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM automation_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return AutomationJob(**dict(row))
            return None

    @staticmethod
    def list_jobs(group_tag: Optional[str] = None, status: Optional[str] = None) -> List[AutomationJob]:
        with get_db_cursor() as cursor:
            query = "SELECT * FROM automation_jobs"
            params = []
            conditions = []
            if group_tag:
                conditions.append("group_tag = ?")
                params.append(group_tag)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY id ASC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [AutomationJob(**dict(row)) for row in rows]

    @staticmethod
    def update_status(job_id: int, status: str, result_message: Optional[str] = None, current_step_index: Optional[int] = None, current_action: Optional[str] = None, container_id: Optional[str] = None):
        with get_db_cursor() as cursor:
            updates = ["status = ?"]
            params = [status]
            if result_message is not None:
                updates.append("result_message = ?")
                params.append(result_message)
            if current_step_index is not None:
                updates.append("current_step_index = ?")
                params.append(current_step_index)
            if current_action is not None:
                updates.append("current_action = ?")
                params.append(current_action)
            if container_id is not None:
                updates.append("container_id = ?")
                params.append(container_id)
            if status == "running":
                updates.append("started_at = CURRENT_TIMESTAMP")
            elif status in ("finished", "failed"):
                updates.append("finished_at = CURRENT_TIMESTAMP")

            params.append(job_id)
            sql = f"UPDATE automation_jobs SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(sql, params)

    @staticmethod
    def delete(target: Optional[str] = None, group_tag: Optional[str] = None, status: Optional[str] = None) -> int:
        with get_db_cursor() as cursor:
            query = "DELETE FROM automation_jobs WHERE 1=1"
            params = []
            if target:
                if str(target).isdigit():
                    query += " AND (id = ? OR group_tag = ? OR account_uid = ?)"
                    params.extend([int(target), target, target])
                else:
                    query += " AND (group_tag = ? OR account_uid = ?)"
                    params.extend([target, target])
            if group_tag:
                query += " AND group_tag = ?"
                params.append(group_tag)
            if status:
                query += " AND status = ?"
                params.append(status)

            cursor.execute(query, tuple(params))
            return cursor.rowcount

    @staticmethod
    def reset(group_tag: Optional[str] = None, target: Optional[str] = None, status_filter: Optional[str] = None) -> int:
        with get_db_cursor() as cursor:
            query = """
                UPDATE automation_jobs 
                SET status = 'pending',
                    current_step_index = 0,
                    current_action = NULL,
                    container_id = NULL,
                    result_message = NULL,
                    started_at = NULL,
                    finished_at = NULL
                WHERE 1=1
            """
            params = []
            if group_tag and group_tag.lower() != "all":
                query += " AND group_tag = ?"
                params.append(group_tag)
            if target and str(target).lower() != "all":
                if str(target).isdigit():
                    query += " AND (id = ? OR group_tag = ? OR account_uid = ?)"
                    params.extend([int(target), target, target])
                else:
                    query += " AND (group_tag = ? OR account_uid = ?)"
                    params.extend([target, target])
            if status_filter:
                query += " AND status = ?"
                params.append(status_filter)

            cursor.execute(query, tuple(params))
            count = cursor.rowcount

        # Clean up stale/leaked proxies when jobs are reset
        ProxyRepository.release_stale_proxies()
        return count


