"""Proxy configurator for Redroid containers using Android Global HTTP Proxy."""

import logging
import subprocess
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ContainerProxyConfigurator:
    """Configures proxy redirection on a target Redroid container via ADB."""

    def __init__(self, adb_target: str):
        self.adb_target = adb_target

    def setup_proxy(self, proxy_url: str) -> bool:
        """
        Sets up global HTTP proxy on the Android system via ADB settings.
        Handles format: http://host:port or http://user:pass@host:port
        """
        if not proxy_url:
            return False

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
