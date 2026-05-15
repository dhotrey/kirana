from __future__ import annotations

from pathlib import Path

import httpx

from utils.benchmarks import BenchmarkClient


def _stream_response(thread_id: str, content: str, latency: float, tools: list[str]):
    body = "\n\n".join(
        [
            f'data: {{"type":"start","thread_id":"{thread_id}","conversation":{{"id":"{thread_id}","title":"Test","created_at":"now","updated_at":"now"}}}}',
            f'data: {{"type":"delta","content":"{content}"}}',
            'data: {"type":"rate_limit_retry","retry_count":1,"retry_attempt":1,"delay_seconds":10,"max_retries":3,"call":"agent"}',
            (
                f'data: {{"type":"end","thread_id":"{thread_id}",'
                f'"conversation":{{"id":"{thread_id}","title":"Test","created_at":"now","updated_at":"now"}},'
                f'"message":{{"role":"assistant","content":"{content}",'
                f'"stats":{{"total_tat_seconds":{latency},"input_tokens":10,'
                f'"output_tokens":5,"total_tokens":15,"tool_calls":{len(tools)},'
                f'"tools":{tools!r},"rate_limit_retries":1}}}}}}'
            ).replace("'", '"'),
        ]
    )
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=f"{body}\n\n",
    )


def test_query_and_follow_up_accumulate_conversation_telemetry():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _stream_response("thread-1", "first answer", 1.25, ["query_finance_db"])
        return _stream_response(
            "thread-1",
            "second answer",
            2.5,
            ["search_receipt_vectors", "query_finance_db"],
        )

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )
    benchmark = BenchmarkClient(model="mistral", client=client)

    response = benchmark.query("first prompt")
    response = response.follow_up("follow-up prompt")

    assert response.content == "second answer"
    assert response.thread_id == "thread-1"
    assert response.latency_seconds == 3.75
    assert response.input_tokens == 20
    assert response.output_tokens == 10
    assert response.total_tokens == 30
    assert response.tool_calls == 3
    assert response.tools_called == [
        "query_finance_db",
        "search_receipt_vectors",
        "query_finance_db",
    ]
    assert response.rate_limit_retries == 2
    assert response.telemetry.turns == 2

    first_payload = requests[0].read().decode()
    second_payload = requests[1].read().decode()
    assert '"thread_id":null' in first_payload
    assert '"thread_id":"thread-1"' in second_payload


def test_query_image_posts_multipart_and_records_image_path(tmp_path: Path):
    image_path = tmp_path / "item.jpg"
    image_path.write_bytes(b"fake image bytes")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _stream_response(
            "image-thread",
            "Yes",
            3.0,
            ["search_item_vectors", "query_finance_db"],
        )

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )
    benchmark = BenchmarkClient(model="mistral", client=client)

    response = benchmark.query_image("Have I bought this?", image_path)

    assert response.content == "Yes"
    assert response.thread_id == "image-thread"
    assert response.tools_called == ["search_item_vectors", "query_finance_db"]
    assert response.turns[0].image_path == str(image_path)
    assert requests[0].url.path == "/api/chat/image/stream"
    assert requests[0].headers["content-type"].startswith("multipart/form-data")
    body = requests[0].read()
    assert b'name="model"' in body
    assert b'name="message"' in body
    assert b'name="image"; filename="item.jpg"' in body
