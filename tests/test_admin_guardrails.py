import unittest

from services.admin_guardrails import (
    MAX_BROADCAST_RECIPIENTS,
    build_broadcast_confirmation_token,
    build_broadcast_preview,
    normalize_broadcast_user_ids,
)


class AdminGuardrailsTests(unittest.TestCase):
    def test_normalize_broadcast_user_ids_deduplicates_and_filters(self):
        result = normalize_broadcast_user_ids(["1", " 2 ", "bad", "2", 0, -5, 3])

        self.assertEqual(result, [1, 2, 3])

    def test_normalize_broadcast_user_ids_respects_limit(self):
        raw_ids = list(range(1, MAX_BROADCAST_RECIPIENTS + 10))

        result = normalize_broadcast_user_ids(raw_ids, max_recipients=5)

        self.assertEqual(result, [1, 2, 3, 4, 5])

    def test_confirmation_token_is_stable_for_same_payload(self):
        token_a = build_broadcast_confirmation_token([2, 1, 2], "Привет", secret="secret")
        token_b = build_broadcast_confirmation_token([1, 2], "Привет", secret="secret")

        self.assertEqual(token_a, token_b)

    def test_preview_contains_warnings_and_token(self):
        preview = build_broadcast_preview(
            list(range(1, 25)),
            "Очень длинное сообщение " * 40 + " https://example.com",
            secret="secret",
        )

        self.assertEqual(preview["phase"], "preview")
        self.assertEqual(preview["requested_count"], 24)
        self.assertTrue(preview["truncated"])
        self.assertEqual(len(preview["warnings"]), 3)
        self.assertTrue(preview["confirmation_token"])


if __name__ == "__main__":
    unittest.main()
