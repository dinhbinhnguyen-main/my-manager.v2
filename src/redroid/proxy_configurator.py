"""Proxy configurator for Redroid containers using Android Global HTTP Proxy."""

import logging
import subprocess
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ContainerProxyConfigurator:
    """Configures proxy redirection on a target Redroid container via ADB."""

    def __init__(self, adb_target: str):
        self.adb_target = adb_target

    @classmethod
    def configure_proxy_for_container(cls, container_name_or_target: str, proxy_url: str) -> bool:
        """Configures proxy on a container or ADB target (e.g. '127.0.0.1:6584' or 'redroid_fb_...')."""
        if not proxy_url:
            return False
        target = str(container_name_or_target)
        if not (":" in target and target.split(":")[-1].isdigit()):
            from src.db.repository import RedroidRepository
            clean_uid = target.replace("redroid_fb_", "")
            inst = RedroidRepository.get_by_account_uid(clean_uid)
            if not inst:
                for row in RedroidRepository.list_all():
                    if row.container_name == target or row.container_id == target:
                        inst = row
                        break
            if inst:
                target = f"127.0.0.1:{inst.adb_port}"
        return cls(target).setup_proxy(proxy_url)

    def setup_proxy(self, proxy_url: str) -> bool:
        """
        Sets up global HTTP proxy on the Android system via ADB settings.
        Handles format: http://host:port or http://user:pass@host:port
        """
        if not proxy_url:
            return False

        # If a proxy rotation API URL is passed (e.g. proxyxoay.shop/api/get.php), rotate and extract HTTP proxy
        if "api" in proxy_url.lower() or "key=" in proxy_url.lower() or ".php" in proxy_url.lower():
            logger.info(f"Resolving HTTP proxy IP:PORT from rotation API URL: {proxy_url[:45]}...")
            try:
                from src.proxy.service import ProxyService
                success, parsed_proxy, msg, status = ProxyService.rotate_proxy_api(proxy_url)
                if success and parsed_proxy and "formatted_url" in parsed_proxy:
                    proxy_url = parsed_proxy["formatted_url"]
                else:
                    # Fallback to current_proxy_http in database if rotation was in cooldown or failed
                    from src.db.repository import ProxyRepository
                    for p in ProxyRepository.list_all():
                        if p.url == proxy_url and p.current_proxy_http:
                            parsed_fallback = ProxyService.parse_proxy_http_string(p.current_proxy_http)
                            if parsed_fallback:
                                proxy_url = parsed_fallback["formatted_url"]
                                logger.info(f"Using cached current_proxy_http for container: {proxy_url}")
                                break
            except Exception as e:
                logger.warning(f"Error rotating/resolving proxy API URL: {e}")

        # If passed as raw host:port or host:port:user:pass without protocol
        if "://" not in proxy_url and ":" in proxy_url:
            try:
                from src.proxy.service import ProxyService
                parsed_raw = ProxyService.parse_proxy_http_string(proxy_url)
                if parsed_raw:
                    proxy_url = parsed_raw["formatted_url"]
                else:
                    proxy_url = f"http://{proxy_url}"
            except Exception:
                proxy_url = f"http://{proxy_url}"

        parsed = urlparse(proxy_url)
        proxy_ip = parsed.hostname
        proxy_port = parsed.port

        if not proxy_ip or not proxy_port:
            logger.error(f"Invalid proxy URL provided: {proxy_url}")
            return False

        logger.info(f"Setting Android Global HTTP Proxy on {self.adb_target} -> {proxy_ip}:{proxy_port}")

        # Set Android System Global HTTP Proxy settings
        commands = [
            f"settings put global http_proxy {proxy_ip}:{proxy_port}",
            f"settings put global global_http_proxy_host {proxy_ip}",
            f"settings put global global_http_proxy_port {proxy_port}",
        ]

        if parsed.username and parsed.password:
            commands.extend([
                f"settings put global global_http_proxy_username {parsed.username}",
                f"settings put global global_http_proxy_password {parsed.password}",
            ])

        for cmd in commands:
            subprocess.run(["adb", "-s", self.adb_target, "shell", cmd], capture_output=True, text=True)

        # Verify applied setting
        verify = subprocess.run(
            ["adb", "-s", self.adb_target, "shell", "settings", "get", "global", "http_proxy"],
            capture_output=True,
            text=True,
        )
        current_val = verify.stdout.strip()
        logger.info(f"Verified Android HTTP Proxy on {self.adb_target}: '{current_val}'")
        return current_val == f"{proxy_ip}:{proxy_port}"

    def clear_proxy(self):
        """Clears global proxy settings in Android."""
        logger.info(f"Clearing proxy configuration on {self.adb_target}")
        commands = [
            "settings put global http_proxy :0",
            "settings delete global http_proxy",
            "settings delete global global_http_proxy_host",
            "settings delete global global_http_proxy_port",
            "settings delete global global_http_proxy_username",
            "settings delete global global_http_proxy_password",
        ]
        for cmd in commands:
            subprocess.run(["adb", "-s", self.adb_target, "shell", cmd], capture_output=True)
