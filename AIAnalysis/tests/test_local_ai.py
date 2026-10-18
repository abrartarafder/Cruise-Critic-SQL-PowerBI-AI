import json
import unittest
from unittest.mock import patch

import httpx

from cruise_ai.assistant import AssistantError
from cruise_ai.data import load_dataset
from cruise_ai.local_ai import list_ollama_models, plan_with_ollama
from cruise_ai.models import QueryPlan


class OllamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()

    def setUp(self):
        self.client_class = httpx.Client
        self.plan = QueryPlan(metric="avg_price_per_day", group_by="cruise_line", direction="asc")

    def transport(self, handler):
        def create_client(**kwargs):
            self.assertEqual(kwargs["base_url"], "http://127.0.0.1:11434")
            self.assertFalse(kwargs["trust_env"])
            return self.client_class(transport=httpx.MockTransport(handler), **kwargs)
        return patch("cruise_ai.local_ai.httpx.Client", side_effect=create_client)

    def response(self, plan=None, **changes):
        body = {"done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": (plan or self.plan).model_dump_json(),
        }}
        body.update(changes)
        return body

    def test_lists_installed_models_and_excludes_cloud_shortcuts(self):
        def respond(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/api/tags")
            return httpx.Response(200, json={"models": [
                {"name": "qwen3:8b"}, {"name": "qwen3:8b"},
                {"name": "other:cloud"}, {"name": "remote", "remote_host": "https://ollama.com"},
                {"name": "remote-alias", "remote_model": "cloud-model"},
            ]})
        with self.transport(respond):
            self.assertEqual(list_ollama_models(), ["qwen3:8b"])

    def test_empty_model_list_is_valid(self):
        with self.transport(lambda request: httpx.Response(200, json={"models": []})):
            self.assertEqual(list_ollama_models(), [])

    def test_malformed_model_list_has_a_helpful_error(self):
        with self.transport(lambda request: httpx.Response(200, json={"models": "invalid"})):
            with self.assertRaisesRegex(AssistantError, "model list"):
                list_ollama_models()

    def test_request_uses_schema_local_context_and_no_api_key(self):
        def respond(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/api/chat")
            self.assertNotIn("authorization", request.headers)
            body = json.loads(request.content)
            self.assertEqual(body["model"], "qwen3:8b")
            self.assertFalse(body["stream"])
            self.assertFalse(body["think"])
            self.assertEqual(body["options"]["temperature"], 0)
            schema = body["format"]
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            context = json.loads(body["messages"][-1]["content"])
            self.assertEqual(context["dataset"]["records"], 366)
            self.assertNotIn("rows", context["dataset"])
            self.assertNotIn("deal_id", context["dataset"])
            return httpx.Response(200, json=self.response())
        with self.transport(respond):
            result = plan_with_ollama("Compare average prices per day", self.dataset, "qwen3:8b")
        self.assertEqual(result, self.plan)

    def test_unsupported_plan_is_preserved(self):
        plan = QueryPlan(kind="unsupported", message="Actual revenue is unavailable.", metric="deal_count", group_by="none")
        with self.transport(lambda request: httpx.Response(200, json=self.response(plan))):
            result = plan_with_ollama("Actual revenue?", self.dataset, "qwen3:8b")
        self.assertEqual(result.kind, "unsupported")

    def test_invalid_plans_cannot_become_executable_sql(self):
        for content in [
            "SELECT * FROM deals", '{"metric":"SUM(revenue)","group_by":"none"}',
            '{"metric":"avg_price","group_by":"none","sql":"DROP TABLE deals"}',
        ]:
            with self.subTest(content=content), self.transport(lambda request: httpx.Response(200, json=self.response(message={"content": content}))):
                with self.assertRaisesRegex(AssistantError, "valid analysis"):
                    plan_with_ollama("Question", self.dataset, "qwen3:8b")

    def test_truncated_or_incomplete_generation_is_rejected(self):
        for changes in [{"done": False}, {"done_reason": "length"}]:
            with self.subTest(changes=changes), self.transport(lambda request: httpx.Response(200, json=self.response(**changes))):
                with self.assertRaisesRegex(AssistantError, "didn't finish"):
                    plan_with_ollama("Question", self.dataset, "qwen3:8b")

    def test_stopped_service_explains_how_to_start_it(self):
        def fail(request):
            raise httpx.ConnectError("Connection refused", request=request)
        with self.transport(fail):
            with self.assertRaisesRegex(AssistantError, "Open Ollama"):
                list_ollama_models()

    def test_timeout_suggests_model_might_be_loading(self):
        def fail(request):
            raise httpx.ReadTimeout("Timeout", request=request)
        with self.transport(fail):
            with self.assertRaisesRegex(AssistantError, "still be loading"):
                plan_with_ollama("Question", self.dataset, "qwen3:8b")

    def test_removed_model_has_a_helpful_error(self):
        with self.transport(lambda request: httpx.Response(404, json={"error": "not found"})):
            with self.assertRaisesRegex(AssistantError, "no longer available"):
                plan_with_ollama("Question", self.dataset, "qwen3:8b")

    def test_service_error_does_not_leak_raw_details(self):
        with self.transport(lambda request: httpx.Response(500, json={"error": "private diagnostic"})):
            with self.assertRaises(AssistantError) as error:
                plan_with_ollama("Question", self.dataset, "qwen3:8b")
        self.assertNotIn("private diagnostic", str(error.exception))

    def test_non_json_service_response_is_rejected(self):
        with self.transport(lambda request: httpx.Response(200, text="not json")):
            with self.assertRaisesRegex(AssistantError, "unreadable"):
                list_ollama_models()

    def test_invalid_questions_and_cloud_model_names_make_no_request(self):
        with patch("cruise_ai.local_ai._request") as request:
            for question, model in [(" ", "qwen3:8b"), ("x" * 1001, "qwen3:8b"), ("Question", ""), ("Question", "large:cloud")]:
                with self.subTest(question=question[:20], model=model), self.assertRaises(AssistantError):
                    plan_with_ollama(question, self.dataset, model)
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
