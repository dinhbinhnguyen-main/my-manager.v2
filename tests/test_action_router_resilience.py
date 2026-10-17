"""Unit tests for action routing resilience and NoneType prevention."""

import unittest
from unittest.mock import MagicMock, patch

from src.core.models import Account, AutomationJob
from src.automation.facebook.router import FBActionRouter, execute_action
from src.automation.job_runner import JobRunner
from src.services.redis_tracker import RedisTracker
from src.db.database import init_db


class TestActionRouterResilience(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_fb_action_router_dispatch_none_action_name(self):
        """Ensures passing None as action_name returns False without raising AttributeError."""
        mock_automator = MagicMock()
        mock_account = Account(uid="12345", username="user", password="pwd")
        res = FBActionRouter.dispatch(mock_automator, mock_account, action_name=None)
        self.assertFalse(res)

    def test_execute_action_none_action_name(self):
        """Ensures execute_action handles None action_name cleanly."""
        res = execute_action(action_name=None, adb_port=5555, params={})
        self.assertEqual(res.get("status"), "failed")
        self.assertIn("Action name is required", res.get("message", ""))

    def test_redis_tracker_none_current_action(self):
        """Ensures update_job_state sanitizes None current_action into a string."""
        tracker = RedisTracker()
        tracker._connected = True
        mock_client = MagicMock()
        tracker._client = mock_client

        # Should not raise exception
        tracker.update_job_state(
            job_id=999,
            account_uid="12345",
            status="running",
            current_action=None,
            container_id=None,
            message=None,
        )

        mock_client.hset.assert_called_once()
        mapping = mock_client.hset.call_args[1].get("mapping", {})
        self.assertEqual(mapping.get("current_action"), "")
        self.assertEqual(mapping.get("container_id"), "")
        self.assertEqual(mapping.get("message"), "")

    @patch("src.db.repository.AutomationJobRepository.update_status")
    def test_job_runner_early_validation_missing_action(self, mock_update_status):
        """Ensures job runner rejects jobs with unrecognizable actions early without waiting for proxies."""
        runner = JobRunner()
        job = AutomationJob(
            id=999,
            name="Test Job",
            group_tag="test",
            account_uid="12345",
            actions_json='[{"invalid_param": 123}]',
        )

        success = runner.run_job_single(job)
        self.assertFalse(success)
        mock_update_status.assert_called_with(
            999, status="failed", result_message=unittest.mock.ANY
        )

    @patch("src.automation.job_runner.execute_action")
    @patch("src.db.repository.AutomationJobRepository.update_status")
    @patch("src.db.repository.ProxyRepository.acquire_available_proxy")
    @patch("src.automation.job_runner.RedroidManager")
    @patch("src.db.repository.RedroidRepository.get_by_account_uid")
    def test_job_runner_auto_infers_scroll_feed(
        self,
        mock_get_redroid,
        mock_mgr_cls,
        mock_acquire_proxy,
        mock_update_status,
        mock_exec_action,
    ):
        """Ensures job runner auto-infers scroll_feed when action is omitted but scroll params are present."""
        runner = JobRunner()
        job = AutomationJob(
            id=132,
            name="Test Feed Job",
            group_tag="test",
            account_uid="12345",
            actions_json='[{"max_swipes": 25, "min_delay": 10.0, "max_delay": 8.0, "max_likes": 1}]',
        )

        # Mock proxy
        mock_proxy = MagicMock()
        mock_proxy.id = 1
        mock_proxy.url = "http://127.0.0.1:8080"
        mock_acquire_proxy.return_value = mock_proxy

        # Mock redroid
        mock_inst = MagicMock()
        mock_inst.container_id = "test_container"
        mock_inst.container_name = "redroid_fb_12345"
        mock_inst.adb_port = 5555
        mock_get_redroid.return_value = mock_inst
        mock_mgr = MagicMock()
        mock_mgr.get_live_docker_status.return_value = "running"
        mock_mgr_cls.return_value = mock_mgr

        mock_exec_action.return_value = {"status": "success", "message": "OK"}

        success = runner.run_job_single(job)
        self.assertTrue(success)
        mock_exec_action.assert_called_once()
        action_arg = mock_exec_action.call_args[0][0]
        params_arg = mock_exec_action.call_args[0][2]
        self.assertEqual(action_arg, "scroll_feed")
        self.assertEqual(params_arg.get("max_swipes"), 25)
