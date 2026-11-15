import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jarvis_workplace_server


class WorkplaceTelemetryTests(unittest.TestCase):
    def test_snapshot_reuses_system_metrics_until_refresh_interval(self):
        memory = SimpleNamespace(percent=42)
        disk = SimpleNamespace(percent=27, free=1024 ** 3)
        with (
            patch.object(
                jarvis_workplace_server.psutil,
                "virtual_memory",
                return_value=memory,
            ),
            patch.object(
                jarvis_workplace_server.psutil,
                "disk_usage",
                return_value=disk,
            ),
            patch.object(
                jarvis_workplace_server.psutil,
                "sensors_battery",
                return_value=None,
            ),
            patch.object(
                jarvis_workplace_server.psutil,
                "cpu_percent",
                return_value=18,
            ) as cpu_percent,
        ):
            state = jarvis_workplace_server.WorkplaceState()
            cpu_percent.reset_mock()
            state._system_updated_at = time.monotonic()

            state.snapshot()
            state.snapshot()
            cpu_percent.assert_not_called()

            state._system_updated_at -= (
                jarvis_workplace_server.SYSTEM_REFRESH_INTERVAL + 0.01
            )
            snapshot = state.snapshot()

            cpu_percent.assert_called_once_with()
            self.assertEqual(snapshot["sys"]["cpu"], 18)
            self.assertEqual(snapshot["sys"]["ram"], 42)
            self.assertEqual(snapshot["sys"]["disk"], 27)


if __name__ == "__main__":
    unittest.main()
