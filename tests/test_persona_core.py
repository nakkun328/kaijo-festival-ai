import unittest

from persona_core import PersonaState, build_system_prompt


class PersonaCoreTests(unittest.TestCase):
    def test_state_and_memory_are_injected(self):
        state = PersonaState("リク", "俺", "お前", "好調", "宇宙", 3)
        prompt = build_system_prompt(state, "- 星を見るのが好き")
        for expected in ("リク", "好調", "宇宙", "3/10", "星を見るのが好き"):
            self.assertIn(expected, prompt)


if __name__ == "__main__":
    unittest.main()

