"""Proxy Rotation Service for proxyxoay.shop and Proxy Lifecycle Management."""

import re
import time
import logging
import requests
from typing import Optional, Dict, Any, Tuple

from src.core.models import Proxy, ProxyStatus
from src.db.repository import ProxyRepository

logger = logging.getLogger(__name__)


class ProxyService:
    @staticmethod
    def parse_proxy_http_string(proxyhttp_raw: str) -> Optional[Dict[str, Any]]:
        """
        Parses proxyhttp string into host, port, user, pass components.
        Examples:
          "160.250.166.28:10947::" -> host="160.250.166.28", port=10947, user=None, pass=None
          "160.250.166.28:10947:usr:pwd" -> host="160.250.166.28", port=10947, user="usr", pass="pwd"
        """
        if not proxyhttp_raw:
            return None

        parts = proxyhttp_raw.strip().split(":")
        if len(parts) < 2:
            return None

        host = parts[0].strip()
        try:
            port = int(parts[1].strip())
        except ValueError:
            return None

        user = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
        password = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None

        if user and password:
            formatted_url = f"http://{user}:{password}@{host}:{port}"
        else:
            formatted_url = f"http://{host}:{port}"

        return {
            "host": host,
            "port": port,
            "user": user,
            "pass": password,
            "formatted_url": formatted_url,
            "raw": proxyhttp_raw,
        }

    @staticmethod
    def _extract_cooldown_seconds(msg: str) -> int:
        """
        Extracts remaining cooldown seconds specifically from status 101 message:
        e.g. 'Con 18s moi co the doi proxy' -> 18
        """
        if not msg:
            return 10
        match = re.search(r'(?:Con|chờ)\s*(\d+)\s*s', msg, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        match_generic = re.search(r'(\d+)\s*s\s*moi co the doi', msg, re.IGNORECASE)
        if match_generic:
            try:
                return int(match_generic.group(1))
            except ValueError:
                pass
        return 10

    @staticmethod
    def rotate_proxy_api(proxy_url: str) -> Tuple[bool, Optional[Dict[str, Any]], str, int]:
        """
        Sends HTTP GET request to Proxy Rotation API URL.
        Returns: (success: bool, parsed_proxy: Optional[Dict], message: str, status_code: int)
        """
        clean_url = str(proxy_url).strip()
        logger.info(f"Requesting proxy rotation from API: {clean_url}")
        try:
            resp = requests.get(clean_url, timeout=15)
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to request Proxy API URL: {e}")
            return False, None, f"Network/HTTP error: {e}", -1

        try:
            status_code = int(data.get("status", 0))
        except (ValueError, TypeError):
            status_code = 0

        message = data.get("message", "")
        proxy_http_raw = data.get("proxyhttp", "")

        # Status == 100 means proxy rotation succeeded!
        if status_code == 100:
            parsed = ProxyService.parse_proxy_http_string(proxy_http_raw)
            if parsed:
                logger.info(f"Proxy rotated successfully! (Status 100) New IP: {parsed['host']}:{parsed['port']}")
                return True, parsed, message, 100
            else:
                logger.error(f"Status 100 but invalid proxyhttp format: '{proxy_http_raw}'")
                return False, None, f"Invalid proxyhttp format: {proxy_http_raw}", 100

        # Status == 101 means cooldown (e.g. 'Con 18s moi co the doi proxy')
        elif status_code == 101:
            logger.warning(f"Proxy rotation cooldown (Status 101): {message}")
            return False, None, message, 101
        else:
            logger.error(f"Proxy API returned status {status_code}: {message}")
            return False, None, f"API error ({status_code}): {message}", status_code

    @classmethod
    def acquire_and_rotate_proxy(
        cls, 
        account_uid: str, 
        proxy_url_override: Optional[str] = None,
        max_retries: int = 10
    ) -> Tuple[Optional[Proxy], Optional[Dict[str, Any]], str]:
        """
        Locks an available Proxy URL from DB for account_uid, calls rotation API, and returns parsed proxy dict.
        Strict logic based on API status:
        - If status == 100: Proxy rotated successfully -> Return immediately.
        - If status == 101: Proxy in cooldown (e.g. 'Con 18s moi co the doi proxy') -> Freeze thread for XXs and retry calling API.
        """
        if proxy_url_override:
            proxy = ProxyRepository.add(Proxy(url=proxy_url_override, status=ProxyStatus.WORKING, assigned_account_uid=account_uid))
        else:
            proxy = ProxyRepository.acquire_available_proxy(account_uid)

        if not proxy:
            return None, None, "No available Proxy URL in database (all are working or unavailable)."

        for attempt in range(1, max_retries + 1):
            success, parsed_proxy, msg, status_code = cls.rotate_proxy_api(proxy.url)

            # STATUS == 100 -> Thành công xoay IP mới, không đóng băng, trả về ngay lập tức!
            if success and parsed_proxy:
                proxy_target = proxy.id if proxy.id else proxy.url
                ProxyRepository.update_current_proxy_http(proxy_target, parsed_proxy["formatted_url"])
                proxy.current_proxy_http = parsed_proxy["formatted_url"]
                return proxy, parsed_proxy, "Proxy acquired and rotated successfully."

            # STATUS == 101 -> Chưa hết cooldown, cần chờ XX giây rồi gọi lại URL
            if status_code == 101:
                cooldown_sec = cls._extract_cooldown_seconds(msg)
                wait_sec = cooldown_sec + 2  # Thêm 2 giây đệm an toàn
                logger.info(
                    f"❄️ [Status 101 - Cooldown] Luồng UID {account_uid} đóng băng {wait_sec}s "
                    f"để chờ URL proxy ({proxy.url}) hết cooldown (Message: '{msg}')..."
                )
                print(
                    f"❄️ [Luồng UID {account_uid}] Status 101 (Con {cooldown_sec}s) -> Đóng băng {wait_sec}s chờ reset (Lần {attempt}/{max_retries})..."
                )
                time.sleep(wait_sec)
            else:
                # Lỗi hệ thống/mạng khác (không phải status 101), chờ 5s rồi thử lại
                logger.warning(f"Proxy API non-101 error: {msg}. Retrying in 5s...")
                time.sleep(5)

        return proxy, None, f"Failed to acquire new proxy after {max_retries} attempts: {msg}"

    @classmethod
    def release_proxy(cls, account_uid: str):
        """Releases proxy bound to account_uid back to available status."""
        logger.info(f"Releasing proxy bound to account UID {account_uid} back to 'available'...")
        ProxyRepository.release_proxy_by_account_uid(account_uid)
