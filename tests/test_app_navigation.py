from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest


def click_button(at: AppTest, label: str) -> AppTest:
    matches = [button for button in at.button if button.label == label]
    if not matches:
        available = [button.label for button in at.button]
        raise AssertionError(f"Button {label!r} not found. Available: {available}")
    return matches[0].click().run(timeout=120)


class AppNavigationTest(unittest.TestCase):
    def test_primary_user_journey_has_no_streamlit_state_errors(self):
        at = AppTest.from_file("app.py", default_timeout=120).run()
        self.assertEqual(len(at.exception), 0, list(at.exception))

        # These buttons previously mutated widget-bound keys after
        # instantiation, which raises StreamlitWidgetAlreadyInstantiatedError.
        at = click_button(at, "2026 only")
        self.assertEqual(len(at.exception), 0, list(at.exception))

        at = click_button(at, "Reset filters")
        self.assertEqual(len(at.exception), 0, list(at.exception))

        # Search result -> Story.
        at = click_button(at, "✨ Explain")
        self.assertEqual(len(at.exception), 0, list(at.exception))
        self.assertTrue(any(button.label == "← Back to paper" for button in at.button))

        # Story -> Paper.
        at = click_button(at, "← Back to paper")
        self.assertEqual(len(at.exception), 0, list(at.exception))
        self.assertTrue(any(button.label == "← Back to search results" for button in at.button))

        # Paper -> results -> Paper again.
        at = click_button(at, "← Back to search results")
        self.assertEqual(len(at.exception), 0, list(at.exception))

        at = click_button(at, "Read paper")
        self.assertEqual(len(at.exception), 0, list(at.exception))
        self.assertTrue(any(button.label == "← Back to search results" for button in at.button))


if __name__ == "__main__":
    unittest.main()
