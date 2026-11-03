"""SSE 事件结构：必须是 dict，由 EventSourceResponse 负责拼装协议行。"""

import asyncio
import json

from backend.services.streamer import done_event, error_event, sse_event, step_event


def test_event_shape_is_dict_not_preformatted_string():
    event = asyncio.run(sse_event("step", {"step": "intent"}))

    assert isinstance(event, dict)
    assert event["event"] == "step"
    assert json.loads(event["data"]) == {"step": "intent"}


def test_step_event_keeps_payload_fields():
    event = asyncio.run(step_event("retrieve", "completed", sources_count=8))

    payload = json.loads(event["data"])
    assert payload == {"step": "retrieve", "status": "completed", "sources_count": 8}


def test_done_event_includes_review():
    event = asyncio.run(
        done_event(["法1"], review={"passed": True, "score": 0.9, "mode": "rule"})
    )

    payload = json.loads(event["data"])
    assert payload["sources"] == ["法1"]
    assert payload["review"]["passed"] is True


def test_error_event_message():
    event = asyncio.run(error_event("boom"))

    assert event["event"] == "error"
    assert json.loads(event["data"]) == {"message": "boom"}
