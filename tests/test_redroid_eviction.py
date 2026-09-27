"""Unit tests for Redroid container auto-eviction logic."""

import unittest
from unittest.mock import MagicMock, patch

from src.redroid.manager import RedroidManager
from src.core.constants import MAX_CONCURRENT_REDROID_CONTAINERS
from src.db.database import init_db


class TestRedroidEviction(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_evict_oldest_idle_container_when_under_limit(self):
        manager = RedroidManager()
        with patch.object(manager, "get_total_running_containers", return_value=3):
            res = manager.evict_oldest_idle_container_if_needed()
            self.assertTrue(res)

    def test_evict_oldest_idle_container_success(self):
        manager = RedroidManager()
        with patch.object(manager, "get_total_running_containers", return_value=6), \
             patch("src.db.repository.AutomationJobRepository.list_jobs", return_value=[]), \
             patch.object(manager, "resolve_target", side_effect=lambda name: (name, name.replace("redroid_", ""))), \
             patch("subprocess.run") as mock_run, \
             patch.object(manager, "stop_instance") as mock_stop:

            docker_ps_res = MagicMock()
            docker_ps_res.returncode = 0
            docker_ps_res.stdout = "redroid_1001\nredroid_1002\nredroid_1003\nredroid_1004\nredroid_1005\nredroid_1006\n"

            def side_effect(cmd, **kwargs):
                if "ps" in cmd:
                    return docker_ps_res
                if "inspect" in cmd:
                    res = MagicMock()
                    res.returncode = 0
                    target_container = cmd[-1]
                    timestamps = {
                        "redroid_1001": "2026-09-23T10:05:00Z",
                        "redroid_1002": "2026-09-23T08:00:00Z",  # oldest
                        "redroid_1003": "2026-09-23T09:30:00Z",
                        "redroid_1004": "2026-09-23T11:00:00Z",
                        "redroid_1005": "2026-09-23T12:00:00Z",
                        "redroid_1006": "2026-09-23T13:00:00Z",
                    }
                    res.stdout = timestamps.get(target_container, "")
                    return res
                return MagicMock(returncode=0)

            mock_run.side_effect = side_effect

            evicted = manager.evict_oldest_idle_container_if_needed()
            self.assertTrue(evicted)
            mock_stop.assert_called_once_with("redroid_1002")

    def test_evict_oldest_idle_container_skips_active_jobs(self):
        manager = RedroidManager()
        active_job = MagicMock()
        active_job.account_uid = "1002"  # 1002 is actively executing a job!

        with patch.object(manager, "get_total_running_containers", return_value=6), \
             patch("src.db.repository.AutomationJobRepository.list_jobs", return_value=[active_job]), \
             patch.object(manager, "resolve_target", side_effect=lambda name: (name, name.replace("redroid_", ""))), \
             patch("subprocess.run") as mock_run, \
             patch.object(manager, "stop_instance") as mock_stop:

            docker_ps_res = MagicMock()
            docker_ps_res.returncode = 0
            docker_ps_res.stdout = "redroid_1001\nredroid_1002\nredroid_1003\n"

            def side_effect(cmd, **kwargs):
                if "ps" in cmd:
                    return docker_ps_res
                if "inspect" in cmd:
                    res = MagicMock()
                    res.returncode = 0
                    target_container = cmd[-1]
                    timestamps = {
                        "redroid_1001": "2026-09-23T10:00:00Z",
                        "redroid_1002": "2026-09-23T07:00:00Z",  # oldest but ACTIVE -> skip!
                        "redroid_1003": "2026-09-23T09:00:00Z",  # oldest IDLE -> evict!
                    }
                    res.stdout = timestamps.get(target_container, "")
                    return res
                return MagicMock(returncode=0)

            mock_run.side_effect = side_effect

            evicted = manager.evict_oldest_idle_container_if_needed()
            self.assertTrue(evicted)
            mock_stop.assert_called_once_with("redroid_1003")


if __name__ == "__main__":
    unittest.main()
