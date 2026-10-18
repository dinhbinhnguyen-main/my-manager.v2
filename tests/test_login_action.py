"""Unit tests for FBLoginAction and 2FA handling."""

import unittest
from unittest.mock import MagicMock, patch, call
from src.core.models import Account, AccountStatus
from src.automation.facebook.login import FBLoginAction
from src.db.database import init_db
from src.db.repository import AccountRepository


class TestFBLoginAction(unittest.TestCase):
    def setUp(self):
        init_db()
        self.mock_automator = MagicMock()
        self.mock_automator.adb_port = 5555
        self.mock_automator.package_name = "com.facebook.katana"
        self.mock_device = MagicMock()
        self.mock_automator.device = self.mock_device
        self.mock_automator.adb_client = MagicMock()
        self.mock_automator.adb_client.is_app_installed.return_value = True
        self.mock_automator.smart_sleep = MagicMock()

    @patch("src.db.repository.AccountRepository.get_by_uid")
    def test_step_0_0_account_not_found_in_db(self, mock_get_by_uid):
        """0.0: Returns False if account is not found in database."""
        mock_get_by_uid.return_value = None
        account = Account(uid="10001", password="secret_password", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)

        res = action.execute()
        self.assertFalse(res)
        mock_get_by_uid.assert_called_once_with("10001")

    @patch("src.db.repository.AccountRepository.get_by_uid")
    def test_step_0_0_missing_password(self, mock_get_by_uid):
        """0.0: Returns False if account has empty password in database."""
        mock_get_by_uid.return_value = Account(uid="10002", password="", two_fa="JBSWY3DPEHPK3PXP")
        account = Account(uid="10002", password="", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)

        res = action.execute()
        self.assertFalse(res)

    @patch("src.db.repository.AccountRepository.get_by_uid")
    def test_step_0_1_app_not_installed_fails_if_install_fails(self, mock_get_by_uid):
        """0.1: Returns False if Facebook app is not installed and install fails."""
        mock_get_by_uid.return_value = Account(uid="10003", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        self.mock_automator.adb_client.is_app_installed.return_value = False
        self.mock_automator.adb_client.install_apk.return_value = False

        account = Account(uid="10003", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)

        res = action.execute()
        self.assertFalse(res)
        self.mock_automator.adb_client.is_app_installed.assert_called_once_with("com.facebook.katana")
        self.mock_automator.adb_client.install_apk.assert_called_once()

    @patch("time.sleep")
    @patch("src.db.repository.AccountRepository.get_by_uid")
    def test_step_0_1_app_not_installed_installs_and_delays_3s(self, mock_get_by_uid, mock_sleep):
        """0.1: Installs APK and delays 3s for container stabilization if not installed."""
        mock_get_by_uid.return_value = Account(uid="10003", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        self.mock_automator.adb_client.is_app_installed.return_value = False
        self.mock_automator.adb_client.install_apk.return_value = True

        account = Account(uid="10003", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)
        action._is_home_screen = MagicMock(return_value=True)

        res = action.execute()
        self.assertTrue(res)
        self.mock_automator.adb_client.install_apk.assert_called_once()
        mock_sleep.assert_any_call(3.0)

    @patch("time.sleep")
    @patch("src.db.repository.AccountRepository.get_by_uid")
    @patch.object(FBLoginAction, "_dump_ui")
    def test_app_launch_fails_after_3_retries(self, mock_dump_ui, mock_get_by_uid, mock_sleep):
        """App launch retries up to 3 times before failing and dumping UI."""
        mock_get_by_uid.return_value = Account(uid="10004", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        self.mock_automator.adb_client.is_app_installed.return_value = True
        self.mock_device.app_current.return_value = {"package": "com.android.launcher3"}

        account = Account(uid="10004", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)
        action._is_start_screen = MagicMock(return_value=False)
        action._is_login_screen = MagicMock(return_value=False)
        action._is_home_screen = MagicMock(return_value=False)
        action._is_2fa_screen = MagicMock(return_value=False)

        res = action.execute()
        self.assertFalse(res)
        self.assertEqual(self.mock_automator.launch.call_count, 3)
        self.assertEqual(self.mock_automator.adb_client.launch_app.call_count, 2)
        mock_dump_ui.assert_called_once()
        self.assertIn("app_launch_failed_10004", mock_dump_ui.call_args[1]["tag"])

    @patch("time.sleep")
    @patch("src.db.repository.AccountRepository.get_by_uid")
    def test_app_launch_retries_and_succeeds_on_attempt_2(self, mock_get_by_uid, mock_sleep):
        """App launch fails on attempt 1, retries and succeeds on attempt 2."""
        mock_get_by_uid.return_value = Account(uid="10004", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        self.mock_automator.adb_client.is_app_installed.return_value = True

        app_pkgs = [{"package": "com.android.launcher3"}, {"package": "com.facebook.katana"}]
        self.mock_device.app_current.side_effect = lambda: app_pkgs.pop(0) if app_pkgs else {"package": "com.facebook.katana"}

        account = Account(uid="10004", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)
        action._is_start_screen = MagicMock(return_value=False)
        action._is_login_screen = MagicMock(return_value=False)
        action._is_2fa_screen = MagicMock(return_value=False)
        home_states = [False, True]
        action._is_home_screen = MagicMock(side_effect=lambda: home_states.pop(0) if home_states else True)

        res = action.execute()
        self.assertTrue(res)
        self.assertEqual(self.mock_automator.launch.call_count, 2)

    @patch("time.sleep")
    @patch("time.time")
    @patch("src.db.repository.AccountRepository.get_by_uid")
    @patch.object(FBLoginAction, "_dump_ui")
    def test_step_3_missing_2fa_screen_dumps_and_returns_false(self, mock_dump_ui, mock_get_by_uid, mock_time, mock_sleep):
        """3.0: If 02_two_fa does not appear, dumps screen and returns False."""
        curr_t = [0.0]
        def fake_time():
            curr_t[0] += 5.0
            return curr_t[0]
        mock_time.side_effect = fake_time
        mock_get_by_uid.return_value = Account(uid="10004", password="pwd", two_fa="JBSWY3DPEHPK3PXP")

        account = Account(uid="10004", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)

        # Mock detector: no checkpoint
        action.detector.is_checkpoint = MagicMock(return_value=(False, ""))

        # Mock screens: start -> False, login -> True, 2fa -> False, home -> False
        action._is_start_screen = MagicMock(return_value=False)
        action._is_login_screen = MagicMock(return_value=True)
        action._is_2fa_screen = MagicMock(return_value=False)
        action._is_home_screen = MagicMock(return_value=False)

        # Mock form inputs
        mock_user = MagicMock()
        mock_pwd = MagicMock()
        mock_btn = MagicMock()

        def device_call(**kwargs):
            if "descriptionMatches" in kwargs:
                pat = kwargs["descriptionMatches"]
                if "mobile number" in pat:
                    return mock_user
                if "password" in pat:
                    return mock_pwd
                if "log in" in pat:
                    return mock_btn
            m = MagicMock()
            m.exists = False
            return m

        self.mock_device.side_effect = device_call

        res = action.execute()
        self.assertFalse(res)
        mock_dump_ui.assert_called_once()
        self.assertIn("no_2fa_10004", mock_dump_ui.call_args[1]["tag"])

    @patch("time.sleep")
    @patch("src.db.repository.AccountRepository.update_status")
    @patch("src.db.repository.AccountRepository.get_by_uid")
    @patch("src.automation.facebook.login.get_totp")
    def test_full_login_flow_with_order_independent_steps(self, mock_get_totp, mock_get_by_uid, mock_update_status, mock_sleep):
        """Tests complete login flow with 00_start -> 01_login -> 02_two_fa -> (05_use_vi -> 03_save -> 06_add_friend) -> home."""
        self.mock_automator.smart_sleep = MagicMock()
        mock_get_by_uid.return_value = Account(uid="10005", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        mock_get_totp.return_value = "889900"

        account = Account(uid="10005", password="pwd", two_fa="JBSWY3DPEHPK3PXP")
        action = FBLoginAction(self.mock_automator, account)
        action.detector.is_checkpoint = MagicMock(return_value=(False, ""))

        # Sequence of screen states:
        # Initial: 00_start -> clicked
        action._is_start_screen = MagicMock(return_value=True)
        action._click_start_already_have_profile = MagicMock(return_value=True)

        # Step 2: 01_login
        action._is_login_screen = MagicMock(return_value=True)

        # Step 3: 02_two_fa appears once, then dismisses
        two_fa_counter = [True, False]
        action._is_2fa_screen = MagicMock(side_effect=lambda: two_fa_counter.pop(0) if two_fa_counter else False)

        # Reactive loop state transitions:
        # state 0: 05_use_vi -> click_continue_in_english
        # state 1: 03_save -> click_save
        # state 2: 06_add_friend -> click_skip
        # state 3: Home reached
        state_idx = 0

        def click_use_vi():
            nonlocal state_idx
            state_idx += 1
            return True

        def click_save():
            nonlocal state_idx
            state_idx += 1
            return True

        def click_skip():
            nonlocal state_idx
            state_idx += 1
            return True

        action._click_continue_in_english = MagicMock(side_effect=click_use_vi)
        action._click_save = MagicMock(side_effect=click_save)
        action._click_skip = MagicMock(side_effect=click_skip)

        action._is_use_vi_screen = lambda: state_idx == 0
        action._is_save_login_screen = lambda: state_idx == 1
        action._is_access_contact_screen = lambda: False
        action._is_add_friend_screen = lambda: state_idx == 2
        action._is_add_mail_screen = lambda: False
        action._is_add_phone_screen = lambda: False
        action._has_skip_button = lambda: state_idx == 2
        action._is_home_screen = lambda: state_idx >= 3

        # Mock interactive elements
        mock_elem = MagicMock()
        mock_elem.exists = True
        self.mock_device.return_value = mock_elem

        res = action.execute()
        self.assertTrue(res)

        # Verify calls
        self.mock_automator.launch.assert_called_with(deeplink="fb://feed")
        mock_get_totp.assert_called_once_with("JBSWY3DPEHPK3PXP")
        action._click_start_already_have_profile.assert_called_once()
        action._click_continue_in_english.assert_called_once()
        action._click_save.assert_called_once()
        action._click_skip.assert_called_once()
        mock_update_status.assert_called_with("10005", AccountStatus.LIVE, "Logged in successfully via Redroid")

    def test_record_login_result_creates_json_and_log(self):
        """Verifies record_login_result writes both JSON record and human-readable log line."""
        import tempfile
        from pathlib import Path
        import json
        from src.automation.facebook.login import record_login_result

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            rec1 = record_login_result("1111", True, AccountStatus.LIVE, "Logged in successfully", log_dir=tmppath)
            rec2 = record_login_result("2222", False, AccountStatus.CHECKPOINT, "Checkpoint detected", log_dir=tmppath)

            json_file = tmppath / "login_results.json"
            log_file = tmppath / "login_results.log"

            self.assertTrue(json_file.exists())
            self.assertTrue(log_file.exists())

            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["uid"], "1111")
            self.assertTrue(data[0]["success"])
            self.assertEqual(data[0]["status"], "live")
            self.assertEqual(data[1]["uid"], "2222")
            self.assertFalse(data[1]["success"])
            self.assertEqual(data[1]["status"], "checkpoint")

            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("[SUCCESS] UID: 1111", lines[0])
            self.assertIn("[FAILED ] UID: 2222", lines[1])


if __name__ == "__main__":
    unittest.main()
