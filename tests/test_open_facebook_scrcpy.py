"""Unit tests for FBOpenFacebookScrcpyAction, routing, and Scrcpy process lifecycle."""

import unittest
from unittest.mock import MagicMock, patch
from src.core.models import Account
from src.automation.facebook.actions.open_facebook_scrcpy import FBOpenFacebookScrcpyAction
from src.automation.facebook.router import FBActionRouter
from src.redroid.scrcpy_manager import ScrcpyManager
from src.db.database import init_db


class TestOpenFacebookScrcpyAction(unittest.TestCase):
    def setUp(self):
        init_db()
        self.mock_automator = MagicMock()
        self.mock_automator.adb_port = 6555
        self.mock_device = MagicMock()
        self.mock_device.app_current.return_value = {"package": "com.facebook.katana"}
        self.mock_automator.device = self.mock_device
        self.mock_automator.adb_client.execute_shell.return_value.stdout = "103.14.22.11:8080"
        self.account = Account(uid="1000998877", username="test_user", password="pwd")

    @patch("src.automation.facebook.actions.open_facebook_scrcpy.ScrcpyManager")
    def test_execute_happy_path(self, mock_scrcpy_cls):
        mock_scrcpy = MagicMock()
        mock_scrcpy_cls.return_value = mock_scrcpy
        mock_proc = MagicMock()
        mock_scrcpy.open_scrcpy_process.return_value = mock_proc
        self.mock_automator.adb_client.is_app_installed.return_value = True

        self.mock_automator.open_facebook_app.return_value = True

        action = FBOpenFacebookScrcpyAction(self.mock_automator, self.account)
        res = action.execute(deeplink="fb://feed", wait_for_close=True)

        self.assertTrue(res)
        mock_scrcpy.open_scrcpy_process.assert_called_once_with(
            6555,
            window_title="Facebook - UID: 1000998877 (Port: 6555)",
            force_reopen=True
        )
        self.mock_automator.open_facebook_app.assert_called_with(deeplink="fb://feed", max_attempts=5)
        mock_scrcpy.wait_for_scrcpy_close.assert_called_once_with(6555, proc=mock_proc)

    @patch("src.automation.facebook.actions.open_facebook_scrcpy.DEFAULT_FB_APK_PATH")
    @patch("src.automation.facebook.actions.open_facebook_scrcpy.ScrcpyManager")
    def test_execute_installs_apk_if_missing(self, mock_scrcpy_cls, mock_apk_path):
        mock_scrcpy = MagicMock()
        mock_scrcpy_cls.return_value = mock_scrcpy
        mock_proc = MagicMock()
        mock_scrcpy.open_scrcpy_process.return_value = mock_proc
        self.mock_automator.adb_client.is_app_installed.return_value = False
        mock_apk_path.exists.return_value = True
        self.mock_automator.open_facebook_app.return_value = True

        action = FBOpenFacebookScrcpyAction(self.mock_automator, self.account)
        res = action.execute(deeplink="fb://feed", wait_for_close=False)

        self.assertTrue(res)
        self.mock_automator.adb_client.install_apk.assert_called_once_with(str(mock_apk_path))
        mock_scrcpy.wait_for_scrcpy_close.assert_not_called()

    @patch("src.automation.facebook.actions.open_facebook_scrcpy.ScrcpyManager")
    def test_execute_fails_if_no_proxy_configured(self, mock_scrcpy_cls):
        """Strict proxy check: fails if container has no active proxy and none in DB."""
        self.mock_automator.adb_client.execute_shell.return_value.stdout = "null"

        with patch("src.automation.facebook.actions.open_facebook_scrcpy.ProxyRepository.get_by_account_uid", return_value=None), \
             patch("src.automation.facebook.actions.open_facebook_scrcpy.RedroidRepository.get_by_account_uid", return_value=None):
            action = FBOpenFacebookScrcpyAction(self.mock_automator, self.account)
            res = action.execute(deeplink="fb://feed", wait_for_close=False)
            self.assertFalse(res)

    @patch("src.automation.facebook.actions.open_facebook_scrcpy.ScrcpyManager")
    def test_execute_retries_app_launch_and_succeeds(self, mock_scrcpy_cls):
        """Tests that app launch uses open_facebook_app with custom max_open_attempts."""
        mock_scrcpy = MagicMock()
        mock_scrcpy_cls.return_value = mock_scrcpy
        mock_proc = MagicMock()
        mock_scrcpy.open_scrcpy_process.return_value = mock_proc
        self.mock_automator.adb_client.is_app_installed.return_value = True
        self.mock_automator.open_facebook_app.return_value = True

        action = FBOpenFacebookScrcpyAction(self.mock_automator, self.account)
        res = action.execute(deeplink="fb://feed", wait_for_close=False, max_open_attempts=3)

        self.assertTrue(res)
        self.mock_automator.open_facebook_app.assert_called_with(deeplink="fb://feed", max_attempts=3)

    @patch.object(FBOpenFacebookScrcpyAction, "execute", return_value=True)
    def test_router_dispatch_aliases(self, mock_execute):
        for alias in ["open_facebook_scrcpy", "open_scrcpy", "open_facebook", "open_app", "fb_scrcpy"]:
            ok = FBActionRouter.dispatch(self.mock_automator, self.account, action_name=alias, params={"deeplink": "fb://feed"})
            self.assertTrue(ok, f"Failed routing alias: {alias}")
            mock_execute.assert_called_with(
                deeplink="fb://feed",
                wait_for_close=True,
                package_name="com.facebook.katana",
            )
            mock_execute.reset_mock()

    def test_scrcpy_manager_wait_for_close_with_proc(self):
        mgr = ScrcpyManager()
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 0]

        with patch("time.sleep", return_value=None):
            mgr.wait_for_scrcpy_close(6555, proc=mock_proc, poll_interval=0.01)

        self.assertEqual(mock_proc.poll.call_count, 2)


if __name__ == "__main__":
    unittest.main()
