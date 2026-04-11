import unittest
from pathlib import Path


class MainStartupTests(unittest.TestCase):
    def test_lifespan_starts_only_single_initiative_worker(self):
        source = Path("main.py").read_text(encoding="utf-8")

        self.assertIn("await container.reengagement_service.start(bot)", source)
        self.assertNotIn("await container.proactive_message_service.start(bot)", source)
        self.assertNotIn("await container.proactive_message_service.close()", source)


if __name__ == "__main__":
    unittest.main()
