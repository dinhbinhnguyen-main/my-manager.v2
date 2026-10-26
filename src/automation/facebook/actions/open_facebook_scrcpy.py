"""Action to launch Facebook App and Scrcpy GUI window, and wait for scrcpy window closure."""

import time
import logging
from typing import Optional
from src.core.models import Account
from src.automation.base_automator import BaseAutomator
from src.redroid.scrcpy_manager import ScrcpyManager
from src.core.constants import FB_KATANA_PACKAGE, DEFAULT_FB_APK_PATH
from src.automation.facebook.login import check_is_logged_in
from src.redroid.proxy_configurator import ContainerProxyConfigurator
from src.db.repository import ProxyRepository, RedroidRepository

logger = logging.getLogger(__name__)


class FBOpenFacebookScrcpyAction:
    """
    Action that opens a container's Scrcpy window and launches the Facebook app.
    When wait_for_close=True, it blocks until the user closes the Scrcpy window,
    allowing the runner to stop the container, release the proxy, and open the next UID.
    """

    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.scrcpy_mgr = ScrcpyManager()

    def _ensure_proxy_configured(self, port: int, uid: str) -> bool:
        """
        Ensures global HTTP proxy is configured on the Android container.
        Strict requirement: Opening Facebook app MUST ALWAYS use proxy.
        """
        try:
            verify_res = self.automator.adb_client.execute_shell("settings get global http_proxy")
            curr_proxy = verify_res.stdout.strip() if hasattr(verify_res, "stdout") else ""
            if curr_proxy and curr_proxy not in ("null", ":0", ""):
                logger.info(f"Verified active container proxy on port {port}: {curr_proxy}")
                return True

            # If not yet set in Android settings, attempt to fetch and apply assigned proxy from DB
            logger.warning(f"No global HTTP proxy detected on port {port}. Checking assigned proxy in DB...")
            proxy_obj = ProxyRepository.get_by_account_uid(uid)
            proxy_url = proxy_obj.url if proxy_obj else None

            if not proxy_url:
                inst = RedroidRepository.get_by_account_uid(uid)
                if inst and inst.proxy_url:
                    proxy_url = inst.proxy_url

            if proxy_url:
                logger.info(f"Applying assigned proxy '{proxy_url}' for UID {uid} on port {port}...")
                configurator = ContainerProxyConfigurator(f"127.0.0.1:{port}")
                if configurator.setup_proxy(proxy_url):
                    logger.info(f"Successfully applied proxy '{proxy_url}' to container port {port}.")
                    return True

            logger.error(
                f"❌ Strict Proxy Requirement Failed: Container for UID {uid} (port {port}) "
                f"does not have an active proxy configured! Aborting app launch."
            )
            return False
        except Exception as e:
            logger.error(f"Error validating/applying proxy on port {port}: {e}")
            return False

    def execute(
        self,
        deeplink: Optional[str] = "fb://feed",
        wait_for_close: bool = True,
        package_name: str = FB_KATANA_PACKAGE,
        max_open_attempts: int = 5,
    ) -> bool:
        """
        1. Ensures Facebook APK is installed on container (auto-installs if missing).
        2. Strictly verifies and configures proxy on container (app opening must use proxy).
        3. Opens Scrcpy window for container screen view.
        4. Launches Facebook app with robust retry loop (similar logic to login.py).
        5. Waits until Scrcpy window is closed by the user.
        """
        port = self.automator.adb_port
        uid = self.account.uid
        logger.info(f"🚀 Initializing Facebook & Scrcpy Action for UID {uid} (ADB Port {port})...")

        # Step 1: Ensure Facebook app is installed
        try:
            if not self.automator.adb_client.is_app_installed(package_name):
                if DEFAULT_FB_APK_PATH.exists():
                    logger.info(f"Facebook app not installed on port {port}. Installing from {DEFAULT_FB_APK_PATH}...")
                    self.automator.adb_client.install_apk(str(DEFAULT_FB_APK_PATH))
                else:
                    logger.warning(f"Facebook app '{package_name}' is not installed and APK was not found at {DEFAULT_FB_APK_PATH}.")
        except Exception as e:
            logger.warning(f"Error checking/installing Facebook app on port {port}: {e}")

        # Step 2: Strictly verify proxy is active on container
        if not self._ensure_proxy_configured(port, uid):
            logger.error(f"❌ Cannot open Facebook app for UID {uid}: Proxy is strictly required but not configured.")
            return False

        # Step 3: Open Scrcpy GUI window
        title = f"Facebook - UID: {uid} (Port: {port})"
        proc = self.scrcpy_mgr.open_scrcpy_process(port, window_title=title, force_reopen=True)
        if not proc:
            pids = self.scrcpy_mgr.get_running_scrcpy_pids().get(port, [])
            if not pids:
                logger.error(f"Failed to launch Scrcpy for UID {uid} on port {port}.")
                return False

        # Step 4: Launch Facebook App with multi-attempt retry loop (similar logic to login.py)
        app_opened = self.automator.open_facebook_app(deeplink=deeplink, max_attempts=max_open_attempts)
        if not app_opened:
            logger.error(f"Failed to open Facebook app ('{package_name}') after {max_open_attempts} attempts!")
            return False

        logger.info(f"✔ Facebook app opened and Scrcpy window active for UID {uid}.")

        # Step 5: Wait for user to close Scrcpy window
        if wait_for_close:
            logger.info(f"⏳ Scrcpy window is active for UID {uid}. Waiting for user to close Scrcpy window...")
            self.scrcpy_mgr.wait_for_scrcpy_close(port, proc=proc)
            logger.info(f"⏹ Scrcpy window closed for UID {uid}.")

        return True
