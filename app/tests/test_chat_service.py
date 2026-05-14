from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from chat.service import (
    RateLimitRetryEvent,
    _extract_tool_names_for_latest_turn,
    _invoke_model_with_rate_limit_retry,
    _is_rate_limit_error,
)


def test_extract_tool_names_for_latest_turn_counts_executed_tools():
    messages = [
        HumanMessage(content="older question"),
        AIMessage(content="older answer"),
        HumanMessage(content="How much did we spend in March?"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "query_finance_db",
                    "args": {"sql": "SELECT 1 FROM receipts"},
                }
            ],
        ),
        ToolMessage(
            content='{"ok": true}',
            name="query_finance_db",
            tool_call_id="call_1",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_2",
                    "name": "query_finance_db",
                    "args": {"sql": "SELECT 2 FROM receipts"},
                }
            ],
        ),
        ToolMessage(content='{"ok": true}', name="query_finance_db", tool_call_id="call_2"),
        AIMessage(content="The total was $123.45."),
    ]

    assert _extract_tool_names_for_latest_turn(messages) == [
        "query_finance_db",
        "query_finance_db",
    ]


def test_extract_tool_names_for_latest_turn_reads_gemini_recorded_tools():
    messages = [
        HumanMessage(content="How much did we spend in March?"),
        AIMessage(
            content="The total was $123.45.",
            additional_kwargs={"kirana_tool_names": ["query_finance_db"]},
        ),
    ]

    assert _extract_tool_names_for_latest_turn(messages) == ["query_finance_db"]


def test_is_rate_limit_error_detects_cloudflare_gateway_shape():
    exc = Exception(
        "Error code: 429 - {'object': 'error', 'message': 'Rate limit exceeded', "
        "'type': 'rate_limited', 'param': None, 'code': '1300', "
        "'raw_status_code': 429}"
    )

    assert _is_rate_limit_error(exc)


def test_invoke_model_retries_rate_limits(monkeypatch):
    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls <= 2:
                raise Exception("Error code: 429 - Rate limit exceeded")
            return AIMessage(content="ok")

    sleeps: list[int] = []
    events: list[RateLimitRetryEvent] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def retry_callback(event: RateLimitRetryEvent) -> None:
        events.append(event)

    monkeypatch.setattr("chat.service.asyncio.sleep", fake_sleep)

    model = FakeModel()
    response = asyncio.run(
        _invoke_model_with_rate_limit_retry(
            model,
            [HumanMessage(content="hello")],
            model_name="test",
            model_identifier="test-model",
            call_name="agent",
            retry_callback=retry_callback,
        )
    )

    assert response.content == "ok"
    assert model.calls == 3
    assert sleeps == [10, 15]
    assert [event.attempt for event in events] == [1, 2]
