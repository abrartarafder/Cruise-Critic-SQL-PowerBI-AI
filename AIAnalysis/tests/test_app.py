import os
import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from cruise_ai.assistant import AssistantError
from cruise_ai.models import Filters, QueryPlan

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.models = patch("cruise_ai.local_ai.list_ollama_models", return_value=["qwen3:8b"])
        self.model_list = self.models.start()
        self.addCleanup(self.models.stop)
        st.cache_data.clear()
        self.app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    def use_openai(self):
        self.app.selectbox(key="provider").set_value("OpenAI (API key)").run()

    def connect_openai(self):
        self.use_openai()
        self.app.text_input(key="session_api_key").set_value("local-test-placeholder").run()

    def ask_question(self, text):
        self.app.text_input(key="question").set_value(text)
        self.app.button[-1].click().run()

    def test_ollama_is_ready_by_default_without_a_key(self):
        self.assertEqual(self.app.selectbox(key="provider").value, "Ollama (on this computer)")
        self.assertEqual(self.app.selectbox(key="ollama_model").value, "qwen3:8b")
        self.assertFalse(self.app.text_input(key="question").disabled)
        self.assertNotIn("session_api_key", [field.key for field in self.app.text_input])

    def test_ollama_question_uses_selected_local_model(self):
        with patch("cruise_ai.local_ai.plan_with_ollama", return_value=QueryPlan(metric="avg_price", group_by="none")) as local, patch("cruise_ai.assistant.plan_question") as remote:
            self.ask_question("What is the average deal price?")
        self.assertFalse(self.app.exception)
        self.assertEqual(local.call_args.args[2], "qwen3:8b")
        remote.assert_not_called()
        self.assertEqual(self.app.session_state["answer"]["provider"], "Ollama")
        self.assertEqual(self.app.session_state["answer"]["result"].matched_records, 366)

    def test_stopped_ollama_keeps_examples_available(self):
        self.model_list.side_effect = AssistantError("Open Ollama on your computer.")
        st.cache_data.clear()
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.text_input(key="question").disabled)
        self.app.button(key="example_0").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.session_state["answer"]["used_ai"])

    def test_refresh_finds_a_model_after_starting_ollama(self):
        self.model_list.return_value = []
        st.cache_data.clear()
        self.app.run()
        self.assertTrue(self.app.text_input(key="question").disabled)
        self.model_list.return_value = ["qwen3:8b"]
        self.app.button[0].click().run()  # Check again
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.text_input(key="question").disabled)

    def test_local_failure_does_not_fall_back_to_openai(self):
        self.app.button(key="example_0").click().run()
        with patch("cruise_ai.local_ai.plan_with_ollama", side_effect=AssistantError("Local model is busy")), patch("cruise_ai.assistant.plan_question") as remote:
            self.ask_question("Average price?")
        self.assertFalse(self.app.exception)
        self.assertNotIn("answer", self.app.session_state)
        self.assertIn("Local model is busy", self.app.error[0].value)
        remote.assert_not_called()

    def test_examples_work_without_key_or_ai_call(self):
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.tabs), 0)
        self.assertEqual(len(self.app.radio), 0)
        with patch("cruise_ai.assistant.plan_question") as service, patch("cruise_ai.local_ai.plan_with_ollama") as local:
            self.app.button(key="example_0").click().run()
        service.assert_not_called()
        local.assert_not_called()
        self.assertFalse(self.app.exception)
        answer = self.app.session_state["answer"]
        self.assertFalse(answer["used_ai"])
        self.assertEqual(answer["result"].matched_records, 366)
        self.assertEqual(len(self.app.get("vega_lite_chart")), 1)

    def test_each_example_replaces_the_previous_answer(self):
        for key, group in [("example_0", "cruise_line"), ("example_2", "destination"), ("example_1", "year")]:
            self.app.button(key=key).click().run()
            self.assertFalse(self.app.exception)
            self.assertEqual(self.app.session_state["answer"]["result"].plan.group_by, group)
            self.assertEqual(len(self.app.get("vega_lite_chart")), 1)

    def test_openai_questions_require_a_key(self):
        self.use_openai()
        self.assertTrue(self.app.text_input(key="question").disabled)
        self.assertTrue(self.app.button[-1].disabled)
        self.connect_openai()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.text_input(key="question").disabled)
        self.assertFalse(self.app.button[-1].disabled)

    def test_question_uses_session_key_and_calculates_result(self):
        self.connect_openai()
        with patch("cruise_ai.assistant.plan_question", return_value=QueryPlan(metric="avg_price", group_by="none")) as service:
            self.ask_question("What is the average deal price?")
        self.assertFalse(self.app.exception)
        self.assertEqual(service.call_args.args[3], "local-test-placeholder")
        self.assertTrue(self.app.session_state["answer"]["used_ai"])
        self.assertEqual(self.app.session_state["answer"]["result"].matched_records, 366)

    def test_example_never_calls_ai_even_with_key(self):
        self.connect_openai()
        with patch("cruise_ai.assistant.plan_question") as service, patch("cruise_ai.local_ai.plan_with_ollama") as local:
            self.app.button(key="example_0").click().run()
        service.assert_not_called()
        local.assert_not_called()
        self.assertFalse(self.app.session_state["answer"]["used_ai"])

    def test_failed_question_removes_old_answer(self):
        self.app.button(key="example_0").click().run()
        self.connect_openai()
        with patch("cruise_ai.assistant.plan_question", side_effect=AssistantError("Test connection failure")):
            self.ask_question("Average price?")
        self.assertFalse(self.app.exception)
        self.assertNotIn("answer", self.app.session_state)
        self.assertIn("Test connection failure", self.app.error[0].value)

    def test_blank_question_does_not_call_ai(self):
        self.connect_openai()
        with patch("cruise_ai.assistant.plan_question") as service:
            self.ask_question("   ")
        service.assert_not_called()
        self.assertTrue(self.app.warning)

    def test_no_matching_records_has_a_helpful_answer(self):
        self.connect_openai()
        plan = QueryPlan(metric="avg_price", group_by="none", filters=Filters(start_year=2030))
        with patch("cruise_ai.assistant.plan_question", return_value=plan):
            self.ask_question("What is the average price in 2030?")
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.session_state["answer"]["result"].table.empty)
        self.assertTrue(any("No deal records match" in item.value for item in self.app.markdown))

    def test_unsupported_question_does_not_show_a_chart(self):
        self.connect_openai()
        plan = QueryPlan(kind="unsupported", metric="deal_count", group_by="none", message="Actual revenue is unavailable.")
        with patch("cruise_ai.assistant.plan_question", return_value=plan):
            self.ask_question("What is actual revenue?")
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.get("vega_lite_chart")), 0)
        self.assertNotIn("result", self.app.session_state["answer"])


if __name__ == "__main__":
    unittest.main()
