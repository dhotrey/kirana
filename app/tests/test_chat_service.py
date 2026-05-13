from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from chat.service import _extract_tool_names_for_latest_turn


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
