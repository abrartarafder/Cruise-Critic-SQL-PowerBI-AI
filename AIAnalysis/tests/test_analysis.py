import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pandas as pd
from openai import APIConnectionError, AuthenticationError, OpenAI, RateLimitError
from pydantic import ValidationError

from cruise_ai.assistant import AssistantError, EXAMPLES, plan_question
from cruise_ai.data import FACT_PATH, PROJECT_ROOT, Dataset, load_dataset
from cruise_ai.models import Filters, QueryPlan
from cruise_ai.query import execute_plan, filter_rows, summarize


def fixture():
    rows = pd.DataFrame({
        "company_name": ["A", "A", "B", "B"],
        "destination_name": ["Island", "City", "Island", "City"],
        "ship_name": ["Ship A", "Ship A", "Ship B", "Ship B"],
        "year": [2023, 2023, 2024, 2024], "duration": [2, 4, 2, 8],
        "price": [100.0, 300.0, 200.0, 400.0],
        "price_per_day": [50.0, 75.0, 100.0, 50.0],
        "rating": [3.0, 5.0, 4.0, 5.0],
        "deal_id": [1, 2, 3, 4], "trip_id": [10, 11, 12, 13],
        "source_row": [2, 3, 4, 5],
        "observation_date": pd.to_datetime(["2023-01-01", "2023-05-01", "2024-01-01", "2024-05-01"]),
    })
    return Dataset(rows, pd.DataFrame(), pd.DataFrame())


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.dataset = fixture()

    def test_average_of_individual_daily_prices(self):
        result = execute_plan(self.dataset, QueryPlan(
            metric="avg_price_per_day", group_by="cruise_line", direction="asc"))
        self.assertEqual(result.table["group"].tolist(), ["A", "B"])
        self.assertEqual(result.table["value"].tolist(), [62.5, 75.0])
        self.assertEqual(result.table["records"].tolist(), [2, 2])
        self.assertIn("62.50 price units/day", summarize(result))

    def test_scope_and_question_filters_intersect(self):
        result = execute_plan(
            self.dataset,
            QueryPlan(metric="deal_count", group_by="none", filters=Filters(max_price=250)),
            Filters(start_year=2024, min_rating=4),
        )
        self.assertEqual(result.matched_records, 1)
        self.assertEqual(result.table.iloc[0]["value"], 1)
        self.assertEqual(result.source_rows.deal_id.tolist(), [3])

    def test_question_cannot_expand_sidebar_scope(self):
        result = execute_plan(
            self.dataset,
            QueryPlan(metric="deal_count", group_by="none", filters=Filters(start_year=2023)),
            Filters(start_year=2024),
        )
        self.assertEqual(result.matched_records, 2)

    def test_conflicting_filters_return_no_data(self):
        result = execute_plan(
            self.dataset,
            QueryPlan(metric="avg_price", group_by="none", filters=Filters(end_year=2023)),
            Filters(start_year=2024),
        )
        self.assertTrue(result.table.empty)
        self.assertIn("No deal records match", summarize(result))

    def test_rating_condition_is_applied_before_aggregation(self):
        result = execute_plan(self.dataset, QueryPlan(
            metric="avg_price", group_by="cruise_line", direction="asc",
            filters=Filters(min_rating=4),
        ))
        self.assertEqual(result.matched_records, 3)
        self.assertEqual(result.table["value"].tolist(), [300.0, 300.0])
        self.assertIn("tied", summarize(result))

    def test_exact_duration_and_destination_filter(self):
        result = execute_plan(self.dataset, QueryPlan(
            metric="avg_price", group_by="none",
            filters=Filters(min_duration=2, max_duration=2, destinations=["Island"]),
        ))
        self.assertEqual(result.table.iloc[0]["value"], 150.0)
        self.assertEqual(result.matched_records, 2)

    def test_chronological_result(self):
        result = execute_plan(self.dataset, QueryPlan(
            metric="avg_price", group_by="year", sort_by="group", direction="asc"))
        self.assertEqual(result.table["group"].tolist(), [2023, 2024])
        self.assertEqual(result.table["value"].tolist(), [200.0, 300.0])
        self.assertIn("2023", summarize(result))
        self.assertIn("observation date", summarize(result))

    def test_limit_and_values_use_bound_parameters(self):
        result = execute_plan(self.dataset, QueryPlan(
            metric="avg_rating", group_by="cruise_line", limit=1,
            filters=Filters(cruise_lines=["A"]),
        ))
        self.assertEqual(result.parameters, ["A", 1])
        self.assertIn("company_name IN (?)", result.sql)
        self.assertNotIn("'A'", result.sql)
        self.assertEqual(len(result.table), 1)

    def test_unknown_or_injected_categories_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "No matching"):
            execute_plan(self.dataset, QueryPlan(
                metric="deal_count", group_by="none",
                filters=Filters(cruise_lines=["A'); DROP TABLE deals; --"]),
            ))
        self.assertEqual(len(filter_rows(self.dataset, Filters())), 4)

    def test_invalid_measures_and_excessive_limits_are_rejected(self):
        for payload in [
            {"metric": "SUM(revenue)", "group_by": "none"},
            {"metric": "avg_price", "group_by": "none", "limit": 1000000},
            {"metric": "avg_price", "group_by": "none", "sql": "SELECT * FROM deals"},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                QueryPlan.model_validate(payload)

    def test_invalid_filter_ranges_are_rejected(self):
        for payload in [{"start_year": 2025, "end_year": 2023}, {"min_duration": 8, "max_duration": 2}, {"min_rating": 6}]:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                Filters.model_validate(payload)

    def test_unsupported_plan_does_not_execute(self):
        with self.assertRaisesRegex(ValueError, "cannot be answered"):
            execute_plan(self.dataset, QueryPlan(kind="unsupported", metric="deal_count", group_by="none"))


class SourceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()

    def test_all_source_records_preserved(self):
        self.assertEqual(len(self.dataset.rows), 366)
        self.assertEqual(self.dataset.rows.source_row.tolist(), list(range(2, 368)))
        self.assertEqual(self.dataset.rows.year.min(), 2019)
        self.assertEqual(self.dataset.rows.year.max(), 2025)

    def test_relationship_audit_matches_the_exports(self):
        audit = self.dataset.audit.set_index("Check")["Affected records"]
        self.assertEqual(audit["Trip IDs without a dimension match"], 358)
        self.assertEqual(audit["Matched trip IDs with ship or line conflicts"], 7)
        for name in ["Ship names", "Cruise lines", "Destinations", "Observation dates"]:
            self.assertEqual(audit[f"{name} without a dimension match"], 0)

    def test_all_demo_plans_execute_on_current_exports(self):
        for question, plan in EXAMPLES.items():
            with self.subTest(question=question):
                result = execute_plan(self.dataset, plan)
                self.assertFalse(result.table.empty)
                self.assertFalse(result.table.value.isna().any())

    def test_invalid_duration_fails_instead_of_silently_dropping_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "FactTable").mkdir()
            facts = pd.read_csv(PROJECT_ROOT / FACT_PATH)
            facts.loc[0, "DURATION"] = 0
            facts.to_csv(root / FACT_PATH, index=False)
            with self.assertRaisesRegex(ValueError, "positive"):
                load_dataset(root)

    def test_incorrect_daily_price_is_audited_and_recalculated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(PROJECT_ROOT / "DimensionTables", root / "DimensionTables")
            (root / "FactTable").mkdir()
            facts = pd.read_csv(PROJECT_ROOT / FACT_PATH)
            facts.loc[0, "PRICE_PER_DAY"] = 1.0
            facts.to_csv(root / FACT_PATH, index=False)
            changed = load_dataset(root)
            self.assertAlmostEqual(changed.rows.iloc[0].price_per_day, 1930 / 8)
            count = changed.audit.set_index("Check").loc["Inconsistent exported price per day", "Affected records"]
            self.assertEqual(count, 1)


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.dataset = fixture()
        self.plan = QueryPlan(metric="avg_price", group_by="year", sort_by="group", direction="asc")
        self.client = Mock()
        self.client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=self.plan)

    def test_sdk_receives_schema_and_context_without_raw_rows(self):
        plan = plan_question("Compare average prices by year", self.dataset, Filters(start_year=2023), "", client=self.client)
        self.assertEqual(plan, self.plan)
        kwargs = self.client.responses.parse.call_args.kwargs
        self.assertIs(kwargs["text_format"], QueryPlan)
        self.assertFalse(kwargs["store"])
        payload = json.loads(kwargs["input"][1]["content"])
        self.assertEqual(payload["app_scope"]["start_year"], 2023)
        self.assertEqual(payload["dataset"]["records"], 4)
        self.assertNotIn("deal_id", payload["dataset"])
        self.assertNotIn("rows", payload["dataset"])

    def test_real_sdk_serializes_and_parses_the_structured_response(self):
        def respond(request):
            body = json.loads(request.content)
            self.assertEqual(body["text"]["format"]["type"], "json_schema")
            self.assertTrue(body["text"]["format"]["strict"])
            schema = body["text"]["format"]["schema"]
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            self.assertFalse(body["store"])
            return httpx.Response(200, json={
                "id": "resp_local_test", "object": "response", "created_at": 0,
                "status": "completed", "model": body["model"],
                "output": [{"id": "msg_local_test", "type": "message", "status": "completed",
                            "role": "assistant", "content": [{"type": "output_text",
                            "text": self.plan.model_dump_json(), "annotations": []}]}],
            })

        with OpenAI(api_key="local-test-placeholder", http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
            plan = plan_question("Average prices by year?", self.dataset, Filters(), "", client=client)
        self.assertEqual(plan, self.plan)

    def test_refusal_or_incomplete_response_never_fabricates_an_answer(self):
        for status, parsed in [("completed", None), ("incomplete", self.plan)]:
            self.client.responses.parse.return_value = SimpleNamespace(status=status, output_parsed=parsed)
            with self.subTest(status=status), self.assertRaises(AssistantError):
                plan_question("Question", self.dataset, Filters(), "", client=self.client)

    def test_service_errors_have_safe_messages(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        failures = [
            (AuthenticationError("secret must not leak", response=httpx.Response(401, request=request), body=None), "not accepted"),
            (RateLimitError("secret must not leak", response=httpx.Response(429, request=request), body=None), "limit"),
            (APIConnectionError(request=request), "Could not reach"),
        ]
        for failure, message in failures:
            self.client.responses.parse.side_effect = failure
            with self.subTest(failure=type(failure).__name__), self.assertRaises(AssistantError) as raised:
                plan_question("Question", self.dataset, Filters(), "", client=self.client)
            self.assertIn(message, str(raised.exception))
            self.assertNotIn("secret must not leak", str(raised.exception))

    def test_unsupported_interpretation_is_returned_without_execution(self):
        self.client.responses.parse.return_value.output_parsed = QueryPlan(
            kind="unsupported", message="Actual revenue is unavailable.", metric="deal_count", group_by="none")
        plan = plan_question("What is actual revenue?", self.dataset, Filters(), "", client=self.client)
        self.assertEqual(plan.kind, "unsupported")

    def test_missing_key_or_invalid_question_does_not_call_service(self):
        with self.assertRaisesRegex(AssistantError, "API key"):
            plan_question("Question", self.dataset, Filters(), "")
        for question in [" ", "x" * 1001]:
            with self.assertRaises(AssistantError):
                plan_question(question, self.dataset, Filters(), "", client=self.client)
        self.client.responses.parse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
