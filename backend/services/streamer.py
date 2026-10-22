"""SSE 事件发送器

事件必须是 ``{"event": ..., "data": ...}`` 结构：EventSourceResponse 会负责
拼装 ``event:`` / ``data:`` 行。若直接返回已经拼好的字符串，sse-starlette 会把它
当成普通 data 再包一层，前端解析器会收到 ``data: event: step`` 这种无效载荷。
"""
import json

async def sse_event(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}

async def step_event(step: str, status: str, **kwargs) -> dict:
    return await sse_event("step", {"step": step, "status": status, **kwargs})

async def error_event(message: str) -> dict:
    return await sse_event("error", {"message": message})

async def done_event(
    sources: list[str],
    review: dict | None = None,
    sources_detail: list[dict] | None = None,
) -> dict:
    payload = {"sources": sources}
    if sources_detail:
        payload["sources_detail"] = sources_detail
    if review:
        payload["review"] = {
            "passed": review.get("passed"),
            "score": review.get("score"),
            "mode": review.get("mode"),
        }
    return await sse_event("done", payload)
