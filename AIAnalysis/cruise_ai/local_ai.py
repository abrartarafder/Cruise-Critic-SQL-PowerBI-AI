"""Use an installed Ollama model without an API key or new model downloads."""

import json

import httpx
from pydantic import ValidationError

from .assistant import AssistantError, SYSTEM_PROMPT
from .data import Dataset
from .models import Filters, QueryPlan

OLLAMA_URL = "http://127.0.0.1:11434"


def _request(path: str, payload: dict | None = None) -> dict:
    try:
        # Ignore proxy settings so local questions go directly to this computer.
        timeout = httpx.Timeout(120.0 if payload else 3.0, connect=3.0)
        with httpx.Client(base_url=OLLAMA_URL, timeout=timeout, trust_env=False) as client:
            response = client.get(path) if payload is None else client.post(path, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException as error:
        raise AssistantError("Ollama took too long to respond. The model may still be loading; try again in a moment.") from error
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404 and path == "/api/chat":
            raise AssistantError("That Ollama model is no longer available. Click Check again in AI settings and choose an installed model.") from error
        raise AssistantError("Ollama couldn't complete this request. Check that your selected model supports chat and try again.") from error
    except httpx.RequestError as error:
        raise AssistantError("Open Ollama on your computer, then click Check again in AI settings. You can also start it with ollama serve.") from error
    except ValueError as error:
        raise AssistantError("Ollama returned an unreadable response. Try restarting Ollama.") from error


def list_ollama_models() -> list[str]:
    response = _request("/api/tags")
    try:
        # Cloud model shortcuts cannot provide this app's local-only behavior.
        return sorted({
            model["name"] for model in response["models"]
            if not model.get("remote_host") and not model.get("remote_model")
            and "cloud" not in model["name"].lower()
        })
    except (KeyError, TypeError, AttributeError) as error:
        raise AssistantError("I couldn't read Ollama's model list. Try restarting Ollama.") from error


def plan_with_ollama(question: str, dataset: Dataset, model: str) -> QueryPlan:
    question = question.strip()
    if not question or len(question) > 1000:
        raise AssistantError("Ask a complete question using between 1 and 1,000 characters.")
    if not model or "cloud" in model.lower():
        raise AssistantError("Choose an installed local Ollama model in AI settings.")
    schema = QueryPlan.model_json_schema()
    schema["required"] = list(schema["properties"])
    schema["$defs"]["Filters"]["required"] = list(schema["$defs"]["Filters"]["properties"])
    unavailable_example = QueryPlan(
        kind="unsupported", message="The data contains deal offers, not confirmed passenger bookings.",
        metric="deal_count", group_by="none",
    )
    response = _request("/api/chat", {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT +
             "\nFirst decide if the requested measure EXISTS in the data. If it does not, "
             "kind MUST be unsupported. Never substitute deal counts for revenue, sales, "
             "profit, bookings, or passengers. Never approximate a missing measure. "
             "For unsupported questions, group_by MUST be none and message must explain "
             "what is missing.\nReply with JSON matching this schema:\n" + json.dumps(schema)},
            {"role": "user", "content": "How many passengers booked each cruise?"},
            {"role": "assistant", "content": unavailable_example.model_dump_json()},
            {"role": "user", "content": json.dumps({
                "dataset": dataset.context(), "app_scope": Filters().model_dump(), "question": question,
            })},
        ],
        "format": schema,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 1600},
    })
    try:
        if response.get("done") is not True or response.get("done_reason") == "length":
            raise AssistantError("The model didn't finish its answer. Try a shorter question.")
        return QueryPlan.model_validate_json(response["message"]["content"])
    except (ValidationError, KeyError, TypeError, AttributeError) as error:
        raise AssistantError("The local model couldn't turn that question into a valid analysis. Try a more specific question.") from error
