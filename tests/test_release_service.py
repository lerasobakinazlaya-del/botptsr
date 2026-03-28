import tempfile
import unittest
from pathlib import Path

from services.release_service import build_health_warnings, load_release_info


class ReleaseServiceTests(unittest.TestCase):
    def test_load_release_info_returns_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info = load_release_info(Path(temp_dir))

        self.assertFalse(info["available"])
        self.assertEqual(info["branch"], "")
        self.assertEqual(info["commit"], "")

    def test_load_release_info_reads_json_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_dir.joinpath("release.json").write_text(
                '{"branch":"master","commit":"abc123","deployed_at":"2026-03-29T12:00:00Z"}',
                encoding="utf-8",
            )

            info = load_release_info(config_dir)

        self.assertTrue(info["available"])
        self.assertEqual(info["branch"], "master")
        self.assertEqual(info["commit"], "abc123")

    def test_build_health_warnings_flags_default_password_and_queue_pressure(self):
        warnings = build_health_warnings(
            admin_dashboard_password="change-me",
            redis_ok=False,
            release_info={"available": False},
            runtime_stats={"queue_size": 8, "queue_capacity": 10},
        )

        codes = {item["code"] for item in warnings}

        self.assertIn("default_admin_password", codes)
        self.assertIn("redis_fallback", codes)
        self.assertIn("missing_release_metadata", codes)
        self.assertIn("ai_queue_pressure", codes)


if __name__ == "__main__":
    unittest.main()
