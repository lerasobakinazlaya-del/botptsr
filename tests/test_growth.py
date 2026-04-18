import unittest

from handlers.chat import _build_share_card
from handlers.growth import (
    build_ref_link,
    build_referral_message,
    build_shareable_insight_text,
)


class GrowthHelpersTests(unittest.TestCase):
    def test_build_ref_link_uses_start_prefix(self):
        self.assertEqual(
            build_ref_link(username="mybot", prefix="ref_", user_id=42),
            "https://t.me/mybot?start=ref_42",
        )

    def test_build_referral_message_mentions_double_reward(self):
        text = build_referral_message(
            {
                "program_title": "Реферальная программа",
                "program_description": "Приглашай друзей.",
                "share_text_template": "Ссылка: {ref_link}",
                "reward_premium_days": 7,
                "reward_plan_key": "pro",
            },
            ref_link="https://t.me/mybot?start=ref_42",
        )

        self.assertIn("Реферальная программа", text)
        self.assertIn("тебе и другу по 7 дней Pro", text)
        self.assertIn("https://t.me/mybot?start=ref_42", text)

    def test_build_share_card_extracts_summary_and_action(self):
        card = _build_share_card(
            "Сначала остановись и назови, что тебя реально перегружает. Потом выбери один разговор, который стоит закрыть сегодня. И не пытайся решить всё сразу."
        )

        self.assertIsNotNone(card)
        self.assertEqual(card["title"], "Инсайт, который мне дал AI-компаньон")
        self.assertIn("Сначала остановись", card["summary"])
        self.assertIn("Потом выбери", card["action"])

    def test_build_shareable_insight_text_includes_link(self):
        text = build_shareable_insight_text(
            share_card={
                "title": "Инсайт дня",
                "summary": "Ты не ленишься, ты перегружен.",
                "action": "Сделай один маленький шаг.",
            },
            ref_link="https://t.me/mybot?start=ref_42",
        )

        self.assertIn("Инсайт дня", text)
        self.assertIn("Что можно сделать: Сделай один маленький шаг.", text)
        self.assertIn("https://t.me/mybot?start=ref_42", text)


if __name__ == "__main__":
    unittest.main()
