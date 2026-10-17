import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from cruise_ai.assistant import AssistantError

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    def test_initial_demo_and_example(self):
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, "366")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        result = self.app.session_state["last_analysis"]["result"]
        self.assertEqual(result.matched_records, 366)
        self.assertEqual(len(self.app.chat_message), 2)

    def test_filter_change_clears_stale_answer(self):
        self.app.button[0].click().run()
        self.app.slider[0].set_value((2024, 2025)).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.chat_message), 0)
        self.assertNotEqual(self.app.metric[0].value, "366")

    def test_ai_requires_a_key_and_keeps_explorer_available(self):
        self.app.radio[0].set_value("AI assistant").run()
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.chat_input[0].disabled)
        self.assertTrue(self.app.warning)
        self.assertEqual(self.app.metric[0].value, "366")

    def test_no_data_scope(self):
        self.app.slider[0].set_value((2019, 2019))
        self.app.multiselect[0].set_value(["Royal Caribbean"])
        self.app.slider[1].set_value(5.0).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, "0")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.session_state["last_analysis"]["result"].table.empty)

    def test_ai_failure_does_not_leave_old_result(self):
        self.app.secrets["OPENAI_API_KEY"] = "local-test-placeholder"
        self.app.radio[0].set_value("AI assistant").run()
        from cruise_ai.models import QueryPlan
        with patch("cruise_ai.assistant.plan_question", return_value=QueryPlan(metric="avg_price", group_by="none")):
            self.app.chat_input[0].set_value("Average price?").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.chat_message), 2)
        with patch("cruise_ai.assistant.plan_question", side_effect=AssistantError("Test connection failure")):
            self.app.chat_input[0].set_value("Average price again?").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.chat_message), 0)
        self.assertIn("Test connection failure", self.app.error[0].value)


if __name__ == "__main__":
    unittest.main()
