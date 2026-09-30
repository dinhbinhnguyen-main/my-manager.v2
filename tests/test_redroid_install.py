"""Unit tests for Redroid APK install and auto-provision logic."""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.redroid.manager import RedroidManager, extract_apk_package_name
from src.core.models import Account, RedroidInstance
from src.db.database import init_db


class TestRedroidInstall(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_extract_apk_package_name_facebook(self):
        pkg = extract_apk_package_name("data/apks/facebook.apk")
        self.assertEqual(pkg, "com.facebook.katana")

    def test_install_apk_status_auto_provisions_if_container_not_found(self):
        manager = RedroidManager()
        account = Account(uid="test_uid_9999", username="test_user", password="dummy_password")

        with patch("src.db.repository.RedroidRepository.get_by_identifier", return_value=None), \
             patch("src.db.repository.RedroidRepository.get_by_account_uid", return_value=None), \
             patch("src.db.repository.AccountRepository.get_by_uid", return_value=account), \
             patch.object(manager, "create_instance") as mock_create, \
             patch("src.db.repository.AccountRepository.bind_container") as mock_bind:

            mock_inst = MagicMock()
            mock_inst.container_id = "cid12345"
            mock_inst.adb_port = 5555
            mock_inst.device_profile_id = "prof1"
            mock_create.return_value = mock_inst

            status = manager.install_apk_status("test_uid_9999", "data/apks/facebook.apk", auto_start=True)
            self.assertEqual(status, "created")
            mock_create.assert_called_once_with(account_uid="test_uid_9999", apk_path="data/apks/facebook.apk")
            mock_bind.assert_called_once_with("test_uid_9999", "cid12345", "prof1")

    def test_install_apk_status_skips_if_already_installed(self):
        manager = RedroidManager()
        existing_inst = RedroidInstance(
            container_id="cid_existing",
            container_name="redroid_test_uid",
            adb_port=5555,
            scrcpy_port=7555,
            status="running",
            account_uid="test_uid_8888",
        )

        with patch("src.db.repository.RedroidRepository.get_by_identifier", return_value=existing_inst), \
             patch.object(manager, "get_live_docker_status", return_value="running"), \
             patch("src.redroid.manager.ADBClient") as mock_adb_cls, \
             patch.object(manager, "ensure_app_permissions") as mock_perm:

            mock_client = MagicMock()
            mock_client.wait_for_boot.return_value = True
            mock_client.is_app_installed.return_value = True  # Already installed!
            mock_adb_cls.return_value = mock_client

            status = manager.install_apk_status("test_uid_8888", "data/apks/facebook.apk", auto_start=True)
            self.assertEqual(status, "skipped")
            mock_client.install_apk.assert_not_called()
            mock_perm.assert_called_once_with("redroid_test_uid", package_name="com.facebook.katana")

    def test_install_apk_status_installs_if_not_installed(self):
        manager = RedroidManager()
        existing_inst = RedroidInstance(
            container_id="cid_existing",
            container_name="redroid_test_uid",
            adb_port=5555,
            scrcpy_port=7555,
            status="running",
            account_uid="test_uid_7777",
        )

        with patch("src.db.repository.RedroidRepository.get_by_identifier", return_value=existing_inst), \
             patch.object(manager, "get_live_docker_status", return_value="running"), \
             patch("src.redroid.manager.ADBClient") as mock_adb_cls, \
             patch.object(manager, "ensure_app_permissions") as mock_perm:

            mock_client = MagicMock()
            mock_client.wait_for_boot.return_value = True
            mock_client.is_app_installed.return_value = False  # Not yet installed!
            mock_client.install_apk.return_value = True
            mock_adb_cls.return_value = mock_client

            status = manager.install_apk_status("test_uid_7777", "data/apks/facebook.apk", auto_start=True)
            self.assertEqual(status, "installed")
            mock_client.install_apk.assert_called_once_with("data/apks/facebook.apk")
            mock_perm.assert_called_once_with("redroid_test_uid", package_name="com.facebook.katana")


if __name__ == "__main__":
    unittest.main()
