"""Facebook Automated Login and 2FA Action."""

import os
import time
import re
import json
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import uiautomator2 as u2

from src.core.constants import DEFAULT_FB_APK_PATH, LOG_DIR, LOGIN_RESULTS_JSON, LOGIN_RESULTS_LOG
from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector
from src.utils.totp import get_totp

logger = logging.getLogger(__name__)

_login_log_lock = threading.Lock()


def record_login_result(
    uid: str,
    success: bool,
    status: Any,
    message: str,
    log_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Appends login outcome to both logs/login_results.json and logs/login_results.log in a thread-safe manner.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_dir = log_dir or LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "login_results.json"
    log_path = target_dir / "login_results.log"

    status_str = status.value if hasattr(status, "value") else str(status)

    record = {
        "timestamp": now_str,
        "uid": str(uid),
        "success": bool(success),
        "status": status_str,
        "message": str(message),
    }

    with _login_log_lock:
        # 1. Append line to log file
        try:
            status_tag = "SUCCESS" if success else "FAILED "
            log_line = f"[{now_str}] [{status_tag}] UID: {uid} | Status: {status_str} | Message: {message}\n"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"Failed to append to login log file {log_path}: {e}")

        # 2. Append object to json file
        try:
            records = []
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            records = data
                except Exception:
                    records = []
            records.append(record)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to update login results json {json_path}: {e}")

    return record


class FBLoginAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)

    @property
    def d(self) -> Optional[u2.Device]:
        return self.automator.device

    # -------------------------------------------------------------------------
    # Screen Detectors
    # -------------------------------------------------------------------------

    def _is_home_screen(self) -> bool:
        """Checks if Facebook News Feed or main navigation tab bar is visible."""
        d = self.d
        if not d:
            return False
        try:
            # Check for top/bottom navigation tab bars or main screen features
            tab_patterns = [
                r"(?i).*(home|trang chủ).*tab.*",
                r"(?i).*(notifications|thông báo).*tab.*",
                r"(?i).*(watch|video).*tab.*",
                r"(?i).*(marketplace).*tab.*",
                r"(?i).*(menu).*tab.*",
            ]
            for pat in tab_patterns:
                if d(descriptionMatches=pat).exists:
                    return True

            # Check for search or composer
            if (
                d(descriptionMatches=r"(?i).*(search facebook|tìm kiếm trên facebook).*").exists
                or d(textMatches=r"(?i).*(search facebook|tìm kiếm trên facebook).*").exists
                or d(descriptionMatches=r"(?i).*(what's on your mind|bạn đang nghĩ gì).*").exists
                or d(textMatches=r"(?i).*(what's on your mind|bạn đang nghĩ gì).*").exists
            ):
                return True
        except Exception as e:
            logger.debug(f"Error checking home screen: {e}")
        return False

    def _is_start_screen(self) -> bool:
        """Checks if initial '00_start' screen is visible (Join Facebook / I already have a profile)."""
        d = self.d
        if not d:
            return False
        try:
            return (
                d(descriptionMatches=r"(?i).*(already have a profile|already have an account|đã có tài khoản).*").exists
                or d(textMatches=r"(?i).*(already have a profile|already have an account|đã có tài khoản).*").exists
                or d(descriptionMatches=r"(?i).*(join facebook|tham gia facebook).*").exists
                or d(textMatches=r"(?i).*(join facebook|tham gia facebook).*").exists
            )
        except Exception:
            return False

    def _is_login_screen(self) -> bool:
        """Checks if '01_login' credentials form is visible."""
        d = self.d
        if not d:
            return False
        try:
            has_user_field = (
                d(descriptionMatches=r"(?i).*(mobile number or email|số điện thoại hoặc email).*").exists
                or d(textMatches=r"(?i).*(mobile number or email|số điện thoại hoặc email).*").exists
            )
            has_pwd_field = (
                d(descriptionMatches=r"(?i).*(password|mật khẩu).*").exists
                or d(textMatches=r"(?i).*(password|mật khẩu).*").exists
            )
            has_login_btn = (
                d(descriptionMatches=r"(?i)^(log in|login|đăng nhập)$").exists
                or d(textMatches=r"(?i)^(log in|login|đăng nhập)$").exists
                or d(className="android.widget.Button", descriptionMatches=r"(?i).*log in.*").exists
            )

            if (has_user_field or has_pwd_field) and has_login_btn:
                return True

            # Also check if two EditTexts and a login button exist
            edits = d(className="android.widget.EditText")
            if len(edits) >= 2 and has_login_btn:
                return True

            return False
        except Exception:
            return False

    def _is_2fa_screen(self) -> bool:
        """Checks if '02_two_fa' screen is visible."""
        d = self.d
        if not d:
            return False
        try:
            kws = r"(?i).*(authentication app|two-factor|6-digit code|ứng dụng xác thực|xác thực 2 yếu tố|mã gồm 6 chữ số).*"
            if d(descriptionMatches=kws).exists or d(textMatches=kws).exists:
                return True

            # Check for EditText with Code hint and Continue button
            has_code_input = (
                d(descriptionMatches=r"(?i).*code.*", className="android.widget.EditText").exists
                or d(textMatches=r"(?i).*code.*", className="android.widget.EditText").exists
            )
            has_continue_btn = (
                d(descriptionMatches=r"(?i)^(continue|tiếp tục)$").exists
                or d(textMatches=r"(?i)^(continue|tiếp tục)$").exists
            )
            if has_code_input and has_continue_btn:
                return True

            return False
        except Exception:
            return False

    def _is_save_login_screen(self) -> bool:
        """Checks if '03_save' screen ('Save your login info?') is visible."""
        d = self.d
        if not d:
            return False
        try:
            header_pat = r"(?i).*(save your login info|lưu thông tin đăng nhập).*"
            if d(descriptionMatches=header_pat).exists or d(textMatches=header_pat).exists:
                return True

            # Button 'Save' together with 'Not now'
            has_save = d(descriptionMatches=r"(?i)^(save|lưu)$").exists or d(textMatches=r"(?i)^(save|lưu)$").exists
            has_not_now = d(descriptionMatches=r"(?i).*(not now|lúc khác).*").exists or d(textMatches=r"(?i).*(not now|lúc khác).*").exists
            return has_save and has_not_now
        except Exception:
            return False

    def _is_use_vi_screen(self) -> bool:
        """Checks if '05_use_vi' language selection screen is visible."""
        d = self.d
        if not d:
            return False
        try:
            return (
                d(descriptionMatches=r"(?i).*continue in english.*").exists
                or d(textMatches=r"(?i).*continue in english.*").exists
                or d(descriptionMatches=r"(?i).*thử dùng facebook bằng tiếng việt.*").exists
                or d(textMatches=r"(?i).*thử dùng facebook bằng tiếng việt.*").exists
            )
        except Exception:
            return False

    def _is_access_contact_screen(self) -> bool:
        """Checks if '04_access_contact' screen is visible."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i).*(contacts access|uploading your contacts|truy cập danh bạ|tải danh bạ).*"
            return d(descriptionMatches=pat).exists or d(textMatches=pat).exists
        except Exception:
            return False

    def _is_add_friend_screen(self) -> bool:
        """Checks if '06_add_friend' screen is visible."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i).*(find friends|people you may know|những người bạn có thể biết|tìm bạn bè).*"
            return d(descriptionMatches=pat).exists or d(textMatches=pat).exists
        except Exception:
            return False

    def _is_add_mail_screen(self) -> bool:
        """Checks if '07_add_mail' screen is visible."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i).*(add an email address|thêm địa chỉ email|add email with google).*"
            return d(descriptionMatches=pat).exists or d(textMatches=pat).exists
        except Exception:
            return False

    def _is_add_phone_screen(self) -> bool:
        """Checks if 'add_phone' screen is visible."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i).*(more current number|add your most current phone number|thêm số điện thoại).*"
            return d(descriptionMatches=pat).exists or d(textMatches=pat).exists
        except Exception:
            return False

    def _has_skip_button(self) -> bool:
        """Checks if a standalone Skip button exists on current screen."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i)^(skip|bỏ qua)$"
            return d(descriptionMatches=pat).exists or d(textMatches=pat).exists
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # UI Actions & Click Helpers
    # -------------------------------------------------------------------------

    def _click_start_already_have_profile(self) -> bool:
        """Clicks 'I already have a profile' / 'Tôi đã có tài khoản' button on 00_start screen."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i).*(already have a profile|already have an account|đã có tài khoản).*"
            btn = d(className="android.widget.Button", descriptionMatches=pat)
            if not btn.exists:
                btn = d(className="android.widget.Button", textMatches=pat)
            if not btn.exists:
                btn = d(clickable=True, descriptionMatches=pat)
            if not btn.exists:
                btn = d(clickable=True, textMatches=pat)
            if btn.exists:
                btn.click()
                return True
        except Exception as e:
            logger.warning(f"Error clicking 'I already have a profile': {e}")
        return False

    def _click_save(self) -> bool:
        """Clicks 'Save' / 'Lưu' button on 03_save screen."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i)^(save|lưu)$"
            btn = d(className="android.widget.Button", descriptionMatches=pat)
            if not btn.exists:
                btn = d(className="android.widget.Button", textMatches=pat)
            if not btn.exists:
                btn = d(clickable=True, descriptionMatches=pat)
            if not btn.exists:
                btn = d(clickable=True, textMatches=pat)
            if btn.exists:
                btn.click()
                return True
        except Exception as e:
            logger.warning(f"Error clicking 'Save': {e}")
        return False

    def _click_continue_in_english(self) -> bool:
        """Clicks 'Continue in English...' on 05_use_vi screen."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i).*continue in english.*"
            btn = d(className="android.widget.Button", descriptionMatches=pat)
            if not btn.exists:
                btn = d(className="android.widget.Button", textMatches=pat)
            if not btn.exists:
                btn = d(clickable=True, descriptionMatches=pat)
            if not btn.exists:
                btn = d(clickable=True, textMatches=pat)
            if btn.exists:
                btn.click()
                return True
        except Exception as e:
            logger.warning(f"Error clicking 'Continue in English...': {e}")
        return False

    def _click_skip(self) -> bool:
        """Clicks 'Skip' / 'Bỏ qua' button on onboarding screens."""
        d = self.d
        if not d:
            return False
        try:
            pat = r"(?i)^(skip|bỏ qua)$"
            btn = d(clickable=True, descriptionMatches=pat)
            if not btn.exists:
                btn = d(clickable=True, textMatches=pat)
            if not btn.exists:
                btn = d(className="android.widget.TextView", textMatches=pat)
            if not btn.exists:
                btn = d(className="android.view.View", textMatches=pat)
            if btn.exists:
                btn.click()
                return True
        except Exception as e:
            logger.warning(f"Error clicking 'Skip': {e}")
        return False

    def _dump_ui(self, tag: str = "login_dump") -> None:
        """Captures XML hierarchy and screenshot PNG for analysis/debugging."""
        device_target = f"127.0.0.1:{self.automator.adb_port}"
        try:
            from tests.dump_view import dump_screen
            dump_screen(device_target=device_target, tag=tag)
            logger.info(f"UI dump completed successfully with tag '{tag}'")
        except Exception as e:
            logger.warning(f"dump_screen failed ({e}). Performing direct fallback dump...")
            try:
                ts = time.strftime("%Y%m%d_%H%M%S")
                dump_dir = os.path.join("tests", "dumps", f"{tag}_{ts}")
                os.makedirs(dump_dir, exist_ok=True)
                latest_dir = os.path.join("tests", "dumps", "latest")
                os.makedirs(latest_dir, exist_ok=True)

                if self.d:
                    xml = self.d.dump_hierarchy()
                    for fpath in [os.path.join(dump_dir, "dumped_view.xml"), os.path.join(latest_dir, "dumped_view.xml")]:
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write(xml)
                    for ppath in [os.path.join(dump_dir, "dumped_screen.png"), os.path.join(latest_dir, "dumped_screen.png")]:
                        self.d.screenshot(ppath)
                    logger.info(f"Direct fallback UI dump saved to {dump_dir}")
            except Exception as fe:
                logger.error(f"Fallback UI dump failed: {fe}")

    # -------------------------------------------------------------------------
    # Main Login Flow Execution
    # -------------------------------------------------------------------------

    def _record_result(self, success: bool, status: Any, message: str) -> bool:
        record_login_result(
            uid=str(self.account.uid),
            success=success,
            status=status,
            message=message
        )
        return success

    def execute(self, deeplink: str = "fb://feed", apk_path: Optional[str] = None) -> bool:
        """
        Executes full FB Login flow with 2FA support and order-independent post-login handling.
        """
        try:
            return self._execute_flow(deeplink=deeplink, apk_path=apk_path)
        except Exception as e:
            logger.exception(f"Unexpected exception during login flow for UID {self.account.uid}: {e}")
            self._dump_ui(tag=f"login_exception_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Unexpected exception: {e}")

    def _execute_flow(self, deeplink: str = "fb://feed", apk_path: Optional[str] = None) -> bool:
        logger.info(f"Starting login flow for account UID {self.account.uid}...")

        # ---------------------------------------------------------------------
        # 0.0. Lấy thông tin của account từ db (bảng accounts)
        # ---------------------------------------------------------------------
        db_account = AccountRepository.get_by_uid(self.account.uid)
        if not db_account:
            logger.error(f"[Step 0.0] Account UID {self.account.uid} not found in database (table 'accounts')!")
            return self._record_result(False, AccountStatus.ERROR, f"Account UID {self.account.uid} not found in database (table 'accounts')")

        self.account = db_account
        logger.info(f"[Step 0.0] Retrieved account info for UID {self.account.uid} from database.")

        if not self.account.password:
            logger.error(f"[Step 0.0] Account UID {self.account.uid} does not have a password configured in database!")
            return self._record_result(False, AccountStatus.ERROR, f"Account UID {self.account.uid} does not have a password configured in database")

        # ---------------------------------------------------------------------
        # 0.1. Kiểm tra xem ứng dụng facebook đã cài đặt chưa
        # Sau khi install delay 3s để container ổn định
        # ---------------------------------------------------------------------
        package_name = self.automator.package_name or "com.facebook.katana"
        if not self.automator.adb_client.is_app_installed(package_name):
            target_apk = Path(apk_path) if apk_path else DEFAULT_FB_APK_PATH
            logger.info(f"[Step 0.1] Facebook application ('{package_name}') is NOT installed. Installing from {target_apk}...")
            if not target_apk.exists():
                logger.error(f"[Step 0.1] APK file not found at {target_apk}!")
                return self._record_result(False, AccountStatus.ERROR, f"APK file not found at {target_apk}")

            install_ok = self.automator.adb_client.install_apk(str(target_apk))
            if not install_ok:
                logger.error(f"[Step 0.1] Failed to install Facebook APK from {target_apk} on port {self.automator.adb_port}!")
                return self._record_result(False, AccountStatus.ERROR, f"Failed to install Facebook APK from {target_apk} on port {self.automator.adb_port}")

            logger.info(f"[Step 0.1] Facebook APK installed successfully. Delaying 3s for container stabilization...")
            time.sleep(3.0)
        else:
            logger.info(f"[Step 0.1] Verified Facebook app ('{package_name}') is installed.")

        # ---------------------------------------------------------------------
        # Mở app Facebook thông qua deeplink trước Bước 1 (thử lại tối đa 3 lần nếu thất bại)
        # ---------------------------------------------------------------------
        app_opened = False
        max_open_attempts = 3
        for attempt in range(1, max_open_attempts + 1):
            logger.info(f"Launching Facebook app via Deep Link '{deeplink}' (Attempt {attempt}/{max_open_attempts})...")
            try:
                self.automator.launch(deeplink=deeplink)
                self.automator.smart_sleep(3.0, 5.0)
                self.automator.handle_system_popups()

                # Kiểm tra xem ứng dụng đã ở foreground hoặc xuất hiện màn hình FB chưa
                curr_pkg = None
                if self.d:
                    try:
                        curr = self.d.app_current()
                        if isinstance(curr, dict):
                            curr_pkg = curr.get("package")
                    except Exception as e:
                        logger.warning(f"Could not retrieve current app package: {e}")

                if (
                    curr_pkg == package_name
                    or self._is_start_screen()
                    or self._is_login_screen()
                    or self._is_home_screen()
                    or self._is_2fa_screen()
                ):
                    logger.info(f"Facebook app opened successfully on attempt {attempt}/{max_open_attempts}.")
                    app_opened = True
                    break

                logger.warning(
                    f"Facebook app not in foreground after launch attempt {attempt}/{max_open_attempts} "
                    f"(current package: '{curr_pkg}')."
                )
                if attempt < max_open_attempts:
                    logger.info(f"Retrying app launch in 2s (Attempt {attempt + 1}/{max_open_attempts})...")
                    if self.d:
                        try:
                            self.d.app_start(package_name, stop=False)
                        except Exception:
                            pass
                    try:
                        self.automator.adb_client.launch_app(package_name)
                    except Exception:
                        pass
                    time.sleep(2.0)
            except Exception as e:
                logger.warning(f"Error during app launch attempt {attempt}/{max_open_attempts}: {e}")
                if attempt < max_open_attempts:
                    time.sleep(2.0)

        if not app_opened:
            logger.error(f"Failed to open Facebook app ('{package_name}') after {max_open_attempts} attempts!")
            self._dump_ui(tag=f"app_launch_failed_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Failed to open Facebook app ('{package_name}') after {max_open_attempts} attempts")

        # Check early checkpoint
        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            logger.warning(f"Checkpoint detected immediately upon launch: {cp_msg}")
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return self._record_result(False, AccountStatus.CHECKPOINT, f"Checkpoint detected immediately upon launch: {cp_msg}")

        # Check if already logged in
        if self._is_home_screen():
            logger.info(f"Account UID {self.account.uid} is already logged in and at Home feed!")
            AccountRepository.update_status(self.account.uid, AccountStatus.LIVE, "Already logged in")
            return self._record_result(True, AccountStatus.LIVE, "Already logged in and at Home feed")

        d = self.d
        if not d:
            logger.error(f"UIAutomator2 device connection not available for UID {self.account.uid}.")
            return self._record_result(False, AccountStatus.ERROR, f"UIAutomator2 device connection not available for UID {self.account.uid}")

        # ---------------------------------------------------------------------
        # 1. @tests/dumps/00_start: Nếu có ui này thì click vào btn 'I already have a profile' hoặc tương tự
        # ---------------------------------------------------------------------
        if self._is_start_screen():
            logger.info("[Step 1] Detected '00_start' screen. Clicking 'I already have a profile'...")
            if not self._click_start_already_have_profile():
                logger.warning("[Step 1] Failed to click 'I already have a profile'. Trying generic button click...")
                self.automator.click_element(text="I already have a profile") or self.automator.click_element(text="Tôi đã có tài khoản")
            self.automator.smart_sleep(2.5, 4.0)

        # In case a saved profile / 'Log into another account' appears
        if d(descriptionMatches=r"(?i).*log into another account.*").exists:
            d(descriptionMatches=r"(?i).*log into another account.*").click()
            self.automator.smart_sleep(2.0, 3.0)
        elif d(textMatches=r"(?i).*đăng nhập bằng tài khoản khác.*").exists:
            d(textMatches=r"(?i).*đăng nhập bằng tài khoản khác.*").click()
            self.automator.smart_sleep(2.0, 3.0)

        # ---------------------------------------------------------------------
        # 2. @tests/dumps/01_login: type uid, mật khẩu -> Click btn 'Login' hoặc tương tự
        # ---------------------------------------------------------------------
        login_ready = False
        start_wait_login = time.time()
        while time.time() - start_wait_login < 10.0:
            if self._is_login_screen():
                login_ready = True
                break
            time.sleep(1.0)

        if not login_ready and not self._is_2fa_screen() and not self._is_home_screen():
            logger.warning(f"[Step 2] Credentials form not detected within 10s for UID {self.account.uid}. Dumping screen...")
            self._dump_ui(tag=f"no_login_form_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Credentials form not detected within 10s for UID {self.account.uid}")

        if self._is_login_screen():
            logger.info(f"[Step 2] Inputting credentials for UID {self.account.uid}...")

            # 2.1. Type UID into EditText
            user_field = d(className="android.widget.EditText", descriptionMatches=r"(?i).*(mobile number or email|số điện thoại hoặc email).*")
            if not user_field.exists:
                user_field = d(className="android.widget.EditText", textMatches=r"(?i).*(mobile number or email|số điện thoại hoặc email).*")
            if not user_field.exists:
                edits = d(className="android.widget.EditText")
                if len(edits) > 0:
                    user_field = edits[0]

            if user_field and user_field.exists:
                user_field.click()
                self.automator.smart_sleep(0.5, 0.8)
                user_field.set_text(self.account.uid)
                self.automator.smart_sleep(0.5, 0.8)

                # Fallback if text was not set
                if not user_field.get_text():
                    logger.warning("[Step 2] set_text did not populate user field. Attempting send_keys fallback...")
                    user_field.click()
                    self.automator.smart_sleep(0.3, 0.5)
                    d.send_keys(self.account.uid)
                    self.automator.smart_sleep(0.5, 0.8)
            else:
                logger.error(f"[Step 2] Could not find username/email input field for UID {self.account.uid}.")
                self._dump_ui(tag=f"missing_user_field_{self.account.uid}")
                return self._record_result(False, AccountStatus.ERROR, f"Could not find username/email input field for UID {self.account.uid}")

            # 2.2. Type password into EditText
            pwd_field = d(className="android.widget.EditText", descriptionMatches=r"(?i).*(password|mật khẩu).*")
            if not pwd_field.exists:
                pwd_field = d(className="android.widget.EditText", textMatches=r"(?i).*(password|mật khẩu).*")
            if not pwd_field.exists:
                pwd_field = d(className="android.widget.EditText", password=True)
            if not pwd_field.exists:
                edits = d(className="android.widget.EditText")
                if len(edits) > 1:
                    pwd_field = edits[1]

            if pwd_field and pwd_field.exists:
                pwd_field.click()
                self.automator.smart_sleep(0.5, 0.8)
                pwd_field.set_text(self.account.password)
                self.automator.smart_sleep(0.5, 0.8)

                # Fallback if text was not set
                if not pwd_field.get_text():
                    logger.warning("[Step 2] set_text did not populate password field. Attempting send_keys fallback...")
                    pwd_field.click()
                    self.automator.smart_sleep(0.3, 0.5)
                    d.send_keys(self.account.password)
                    self.automator.smart_sleep(0.5, 0.8)
            else:
                logger.error(f"[Step 2] Could not find password input field for UID {self.account.uid}.")
                self._dump_ui(tag=f"missing_pwd_field_{self.account.uid}")
                return self._record_result(False, AccountStatus.ERROR, f"Could not find password input field for UID {self.account.uid}")

            # 2.3. Click 'Login' Button
            login_btn = d(className="android.widget.Button", descriptionMatches=r"(?i).*(log in|login|đăng nhập).*")
            if not login_btn.exists:
                login_btn = d(className="android.widget.Button", textMatches=r"(?i).*(log in|login|đăng nhập).*")
            if not login_btn.exists:
                login_btn = d(clickable=True, descriptionMatches=r"(?i)^(log in|login|đăng nhập)$")
            if not login_btn.exists:
                login_btn = d(clickable=True, textMatches=r"(?i)^(log in|login|đăng nhập)$")

            if login_btn and login_btn.exists:
                login_btn.click()
                logger.info(f"[Step 2] Clicked Log In button for UID {self.account.uid}")
            else:
                logger.error(f"[Step 2] Could not find Log In button for UID {self.account.uid}.")
                self._dump_ui(tag=f"missing_login_btn_{self.account.uid}")
                return self._record_result(False, AccountStatus.ERROR, f"Could not find Log In button for UID {self.account.uid}")

            self.automator.smart_sleep(4.0, 6.0)

        # ---------------------------------------------------------------------
        # 3. @tests/dumps/02_two_fa: MANDATORY!
        # Nếu có thì sử dụng logic @src/utils/2fa.py để lấy code (raw_secret luôn không chứa khoảng trắng)
        # -> Click btn 'Continue' chờ trong 30s hoặc không còn UI này nữa.
        # Nếu không có @tests/dumps/02_two_fa thì dump & return False
        # ---------------------------------------------------------------------
        logger.info(f"[Step 3] Waiting for 2FA screen (02_two_fa) for UID {self.account.uid}...")
        two_fa_detected = False
        start_wait_2fa = time.time()
        while time.time() - start_wait_2fa < 15.0:
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                logger.warning(f"Checkpoint detected while waiting for 2FA: {cp_msg}")
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return self._record_result(False, AccountStatus.CHECKPOINT, f"Checkpoint detected while waiting for 2FA: {cp_msg}")

            if self._is_2fa_screen():
                two_fa_detected = True
                break
            time.sleep(1.0)

        if not two_fa_detected:
            logger.error(f"[Step 3] Mandatory 2FA screen (02_two_fa) did NOT appear for UID {self.account.uid}! Dumping screen...")
            self._dump_ui(tag=f"no_2fa_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Mandatory 2FA screen (02_two_fa) did NOT appear for UID {self.account.uid}")

        logger.info(f"[Step 3] Detected 2FA screen for UID {self.account.uid}.")

        if not self.account.two_fa:
            logger.error(f"[Step 3] Account UID {self.account.uid} has no 2FA secret key in database!")
            self._dump_ui(tag=f"missing_2fa_secret_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Account UID {self.account.uid} has no 2FA secret key in database")

        # Generate TOTP using logic in src/utils/2fa.py
        try:
            clean_secret = self.account.two_fa.replace(" ", "").strip()
            totp_code = get_totp(clean_secret)
            logger.info(f"[Step 3] Generated TOTP code successfully: {totp_code}")
        except Exception as e:
            logger.error(f"[Step 3] Failed to generate TOTP code from secret key: {e}")
            self._dump_ui(tag=f"totp_gen_error_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Failed to generate TOTP code from secret key: {e}")

        # Input OTP code
        code_input = d(className="android.widget.EditText", descriptionMatches=r"(?i).*code.*")
        if not code_input.exists:
            code_input = d(className="android.widget.EditText", textMatches=r"(?i).*code.*")
        if not code_input.exists:
            code_input = d(className="android.widget.EditText")

        if code_input and code_input.exists:
            code_input.click()
            self.automator.smart_sleep(0.5, 0.8)
            code_input.set_text(totp_code)
            self.automator.smart_sleep(0.5, 0.8)
            if not code_input.get_text():
                logger.warning("[Step 3] set_text did not populate code field. Using send_keys fallback...")
                code_input.click()
                self.automator.smart_sleep(0.3, 0.5)
                d.send_keys(totp_code)
                self.automator.smart_sleep(0.5, 0.8)
        else:
            logger.error(f"[Step 3] Could not find 2FA code input field for UID {self.account.uid}.")
            self._dump_ui(tag=f"missing_code_input_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Could not find 2FA code input field for UID {self.account.uid}")

        # Click Continue button
        continue_btn = d(className="android.widget.Button", descriptionMatches=r"(?i).*(continue|tiếp tục).*")
        if not continue_btn.exists:
            continue_btn = d(className="android.widget.Button", textMatches=r"(?i).*(continue|tiếp tục).*")
        if not continue_btn.exists:
            continue_btn = d(clickable=True, descriptionMatches=r"(?i)^(continue|tiếp tục)$")
        if not continue_btn.exists:
            continue_btn = d(clickable=True, textMatches=r"(?i)^(continue|tiếp tục)$")

        if continue_btn and continue_btn.exists:
            continue_btn.click()
            logger.info(f"[Step 3] Clicked Continue for 2FA on UID {self.account.uid}.")
        else:
            logger.error(f"[Step 3] Could not find Continue button on 2FA screen for UID {self.account.uid}.")
            self._dump_ui(tag=f"missing_continue_btn_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Could not find Continue button on 2FA screen for UID {self.account.uid}")

        # Chờ trong 30s hoặc không còn UI này nữa
        logger.info("[Step 3] Waiting up to 30s or until 2FA UI is dismissed...")
        start_wait_dismiss = time.time()
        while time.time() - start_wait_dismiss < 30.0:
            if not self._is_2fa_screen():
                logger.info(f"[Step 3] 2FA UI dismissed after {time.time() - start_wait_dismiss:.1f}s.")
                break
            time.sleep(1.0)

        # ---------------------------------------------------------------------
        # Order-Independent Post-Login Reactive Loop:
        # Handles 03_save, 05_use_vi, 04_access_contact, 06_add_friend, 07_add_mail, add_phone
        # Cần 1 logic để có thể không phụ thuộc vào các bước
        # ---------------------------------------------------------------------
        logger.info(f"Entering order-independent post-login reactive loop for UID {self.account.uid}...")
        max_loop_steps = 25
        logged_in_confirmed = False

        for step in range(1, max_loop_steps + 1):
            self.automator.ensure_foreground()

            # 1. Checkpoint Check
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                logger.warning(f"[Post-Login Step {step}] Checkpoint detected: {cp_msg}")
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return self._record_result(False, AccountStatus.CHECKPOINT, f"Checkpoint detected post-login: {cp_msg}")

            # 2. Check if Home / News Feed is reached
            if self._is_home_screen():
                logger.info(f"[Post-Login Step {step}] Successfully reached Facebook Home Feed for UID {self.account.uid}!")
                logged_in_confirmed = True
                break

            # 3. Handle @tests/dumps/03_save: nếu có thì click btn 'Save'
            if self._is_save_login_screen():
                logger.info(f"[Post-Login Step {step}] Detected '03_save' screen. Clicking 'Save'...")
                self._click_save()
                self.automator.smart_sleep(2.0, 3.0)
                continue

            # 4. Handle @tests/dumps/05_use_vi: nếu có thì click btn 'Continue in English...'
            if self._is_use_vi_screen():
                logger.info(f"[Post-Login Step {step}] Detected '05_use_vi' screen. Clicking 'Continue in English...'...")
                self._click_continue_in_english()
                self.automator.smart_sleep(2.0, 3.0)
                continue

            # 5. Handle Onboarding Screens:
            # @tests/dumps/04_access_contact, @tests/dumps/06_add_friend,
            # @tests/dumps/07_add_mail, @tests/dumps/add_phone: Nếu có thì click skip
            if (
                self._is_access_contact_screen()
                or self._is_add_friend_screen()
                or self._is_add_mail_screen()
                or self._is_add_phone_screen()
                or self._has_skip_button()
            ):
                logger.info(f"[Post-Login Step {step}] Detected onboarding screen with Skip. Clicking 'Skip'...")
                self._click_skip()
                self.automator.smart_sleep(2.0, 3.0)
                continue

            # 6. Handle any system permission dialogs
            self.automator.handle_system_popups()

            # Wait briefly before checking next UI transition
            time.sleep(1.5)

        # Final Verification
        if logged_in_confirmed or self._is_home_screen():
            AccountRepository.update_status(self.account.uid, AccountStatus.LIVE, "Logged in successfully via Redroid")
            logger.info(f"✅ Account {self.account.uid} logged in successfully and verified LIVE!")
            return self._record_result(True, AccountStatus.LIVE, "Logged in successfully via Redroid")
        else:
            logger.warning(f"⚠️ Post-login flow finished without confirming Home screen for UID {self.account.uid}. Dumping screen...")
            self._dump_ui(tag=f"login_incomplete_{self.account.uid}")
            return self._record_result(False, AccountStatus.ERROR, f"Post-login flow finished without confirming Home screen for UID {self.account.uid}")
