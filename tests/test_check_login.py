"""Unit tests for check_is_logged_in and is_logged_in."""

import unittest
from unittest.mock import MagicMock, patch
from src.automation.facebook.login import check_is_logged_in, is_logged_in
from src.automation.base_automator import BaseAutomator


class TestCheckLogin(unittest.TestCase):
    def setUp(self):
        self.mock_device = MagicMock()
        self.mock_device.app_current.return_value = {"package": "com.facebook.katana"}
        default_elem = MagicMock()
        default_elem.exists = False
        self.mock_device.return_value = default_elem
        self.mock_device.dump_hierarchy.return_value = "<xml></xml>"

    def test_logged_in_home_screen(self):
        def call_side_effect(**kwargs):
            elem = MagicMock()
            desc = kwargs.get("descriptionMatches", "")
            if "home" in desc or "trang chủ" in desc:
                elem.exists = True
            else:
                elem.exists = False
            return elem

        self.mock_device.side_effect = call_side_effect

        with patch("src.automation.facebook.login.CheckpointDetector") as mock_detector:
            mock_detector.return_value.is_checkpoint.return_value = (False, "")
            logged, reason = check_is_logged_in(self.mock_device)
            self.assertTrue(logged, f"Expected True but got False: {reason}")
            self.assertIn("LOGGED_IN", reason)
            self.assertTrue(is_logged_in(self.mock_device))

    def test_not_logged_in_credentials_form(self):
        def call_side_effect(**kwargs):
            elem = MagicMock()
            desc = kwargs.get("descriptionMatches", "")
            text = kwargs.get("textMatches", "")
            # Only match login form fields, not session expired
            if any(k in desc or k in text for k in ["mobile number or email", "số điện thoại hoặc email", "password|mật khẩu", "^(log in|login|đăng nhập)$"]):
                elem.exists = True
            else:
                elem.exists = False
            return elem

        self.mock_device.side_effect = call_side_effect

        with patch("src.automation.facebook.login.CheckpointDetector") as mock_detector:
            mock_detector.return_value.is_checkpoint.return_value = (False, "")
            logged, reason = check_is_logged_in(self.mock_device)
            self.assertFalse(logged)
            self.assertIn("NOT_LOGGED_IN", reason)
            self.assertFalse(is_logged_in(self.mock_device))

    def test_checkpoint_screen(self):
        with patch("src.automation.facebook.login.CheckpointDetector") as mock_detector:
            mock_detector.return_value.is_checkpoint.return_value = (True, "Your account has been locked")
            logged, reason = check_is_logged_in(self.mock_device)
            self.assertFalse(logged)
            self.assertIn("CHECKPOINT", reason)
            self.assertIn("Your account has been locked", reason)

    def test_session_expired_screen(self):
        def call_side_effect(**kwargs):
            elem = MagicMock()
            text = kwargs.get("textMatches", "")
            desc = kwargs.get("descriptionMatches", "")
            if "session expired" in text or "phiên đã hết hạn" in text or "session expired" in desc:
                elem.exists = True
            else:
                elem.exists = False
            return elem

        self.mock_device.side_effect = call_side_effect

        with patch("src.automation.facebook.login.CheckpointDetector") as mock_detector:
            mock_detector.return_value.is_checkpoint.return_value = (False, "")
            logged, reason = check_is_logged_in(self.mock_device)
            self.assertFalse(logged)
            self.assertIn("SESSION_EXPIRED", reason)

    def test_base_automator_methods(self):
        automator = BaseAutomator(adb_port=6555)
        automator.device = self.mock_device

        def call_side_effect(**kwargs):
            elem = MagicMock()
            desc = kwargs.get("descriptionMatches", "")
            if "home" in desc or "trang chủ" in desc:
                elem.exists = True
            else:
                elem.exists = False
            return elem

        self.mock_device.side_effect = call_side_effect

        with patch("src.automation.facebook.login.CheckpointDetector") as mock_detector:
            mock_detector.return_value.is_checkpoint.return_value = (False, "")
            logged, reason = automator.check_is_logged_in()
            self.assertTrue(logged, f"Expected True but got False: {reason}")
            self.assertIn("LOGGED_IN", reason)
            self.assertTrue(automator.is_logged_in())

    def test_router_dispatch_check_login_persists_results(self):
        from src.automation.facebook.router import FBActionRouter
        from src.core.models import Account, AccountStatus

        automator = BaseAutomator(adb_port=6555)
        automator.device = self.mock_device
        automator.launch = MagicMock()
        automator.open_facebook_app = MagicMock(return_value=True)
        account = Account(uid="1000888999", password="pwd", username="user_test")

        def call_side_effect(**kwargs):
            elem = MagicMock()
            desc = kwargs.get("descriptionMatches", "")
            if "home" in desc or "trang chủ" in desc:
                elem.exists = True
            else:
                elem.exists = False
            return elem

        self.mock_device.side_effect = call_side_effect

        with patch("src.automation.facebook.login.CheckpointDetector") as mock_detector, \
             patch("src.db.repository.AccountRepository.update_status") as mock_update_status, \
             patch("src.automation.facebook.login.record_login_result") as mock_record_log:
            mock_detector.return_value.is_checkpoint.return_value = (False, "")

            res = FBActionRouter.dispatch(automator, account, "check_login")
            self.assertTrue(res)

            # Verify SQLite DB update was invoked
            mock_update_status.assert_called_once()
            args, kwargs = mock_update_status.call_args
            self.assertEqual(args[0], "1000888999")
            self.assertEqual(args[1], AccountStatus.LIVE)
            self.assertIn("LOGGED_IN", kwargs.get("note", ""))

            # Verify log persistence was invoked
            mock_record_log.assert_called_once()
            log_args, log_kwargs = mock_record_log.call_args
            self.assertEqual(log_kwargs.get("uid"), "1000888999")
            self.assertTrue(log_kwargs.get("success"))
            self.assertEqual(log_kwargs.get("status"), AccountStatus.LIVE)

    def test_automator_open_facebook_app_happy_path(self):
        automator = BaseAutomator(adb_port=6555)
        automator.device = self.mock_device
        automator.adb_client = MagicMock()
        automator.adb_client.is_app_installed.return_value = True
        self.mock_device.app_current.return_value = {"package": "com.facebook.katana"}

        ok = automator.open_facebook_app(deeplink="fb://feed", max_attempts=2)
        self.assertTrue(ok)
        self.mock_device.shell.assert_called_with("am start -a android.intent.action.VIEW -d 'fb://feed' com.facebook.katana")

    def test_automator_open_facebook_app_retry_fallback(self):
        automator = BaseAutomator(adb_port=6555)
        automator.device = self.mock_device
        automator.adb_client = MagicMock()
        automator.adb_client.is_app_installed.return_value = True

        # Attempt 1: launcher3, Attempt 2: katana
        states = [{"package": "com.android.launcher3"}, {"package": "com.facebook.katana"}]
        self.mock_device.app_current.side_effect = lambda: states.pop(0) if states else {"package": "com.facebook.katana"}

        ok = automator.open_facebook_app(deeplink="fb://feed", max_attempts=2)
        self.assertTrue(ok)

    def test_automator_launch_defaults_to_deeplink_for_facebook(self):
        automator = BaseAutomator(adb_port=6555, package_name="com.facebook.katana")
        automator.device = self.mock_device

        automator.launch()  # No deeplink argument
        self.mock_device.shell.assert_called_with("am start -a android.intent.action.VIEW -d 'fb://feed' com.facebook.katana")


if __name__ == "__main__":
    unittest.main()


