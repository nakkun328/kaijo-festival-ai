import time
import unittest

from telemetry import Telemetry


class TelemetryTests(unittest.TestCase):
    def test_successful_operation_is_measured(self):
        telemetry = Telemetry()
        with telemetry.measure("thinking") as timer:
            time.sleep(0.001)
        snapshot = telemetry.snapshot()["operations"]["thinking"]
        self.assertGreaterEqual(timer.duration_ms, 0)
        self.assertEqual(snapshot["count"], 1)
        self.assertEqual(snapshot["errors"], 0)
        self.assertEqual(snapshot["active"], 0)

    def test_failed_operation_is_counted(self):
        telemetry = Telemetry()
        with self.assertRaises(RuntimeError):
            with telemetry.measure("transcribing"):
                raise RuntimeError("failed")
        snapshot = telemetry.snapshot()["operations"]["transcribing"]
        self.assertEqual(snapshot["count"], 1)
        self.assertEqual(snapshot["errors"], 1)

