import unittest

from services.state_engine import StateEngine


class StateEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StateEngine()

    def test_infer_emotional_tone_grief_maps_to_overwhelmed(self):
        state = self.engine.update_state({}, "Смерть собаки. Очень тяжело.")
        self.assertEqual(state.get("emotional_tone"), "overwhelmed")

    def test_infer_emotional_tone_heart_symptoms_maps_to_anxious(self):
        state = self.engine.update_state({}, "У мужа нарушение ритма, неделю назад стало хуже.")
        self.assertEqual(state.get("emotional_tone"), "anxious")

    def test_infer_emotional_tone_default_is_neutral(self):
        state = self.engine.update_state({}, "Привет")
        self.assertEqual(state.get("emotional_tone"), "neutral")


if __name__ == "__main__":
    unittest.main()
