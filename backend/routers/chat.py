"""POST /api/chat —— SSE 流式问答端点

编排完全交给 ``src/agents/graph.py`` 的 LangGraph 图，
本层只做两件事：把图的节点执行翻译成 SSE 事件、把异常转成 error 事件。

节点与事件的映射：
    identify            → step: intent
    retrieve            → step: retrieve
    civil_law / ...     → step: generate（可能因审查不通过出现多次）
    review              → step: review
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.services.streamer import done_event, error_event, step_event

logger = logging.getLogger(__name__)
router = APIRouter()


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@router.post("/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    question = (body.get("question") or "").strip()
    history = body.get("history") or []

    if not question:
        async def empty_stream():
            yield await error_event("question 不能为空")

        return EventSourceResponse(empty_stream())

    async def event_stream():
        from src.agents.graph import DOMAINS, astream_agent
        from src.agents.domain_agent import build_sources_detail

        started = time.perf_counter()
        latest: dict = {}

        try:
            async for node, update in astream_agent(question, history):
                latest.update(update)

                if node == "identify":
                    yield await step_event(
                        "intent",
                        "completed",
                        domain=update.get("domain", "general"),
                        domain_zh=update.get("domain_zh", "通用"),
                        intent=update.get("intent", ""),
                        elapsed_ms=_elapsed_ms(started),
                    )

                elif node == "retrieve":
                    docs = update.get("context_docs") or []
                    yield await step_event(
                        "retrieve",
                        "completed",
                        sources_count=len(docs),
                        retrieved_by=sorted(
                            {doc.metadata.get("retrieved_by", "vector") for doc in docs}
                        ),
                        elapsed_ms=_elapsed_ms(started),
                    )

                elif node == "review":
                    review = update.get("review") or {}
                    yield await step_event(
                        "review",
                        "passed" if review.get("passed") else "failed",
                        passed=review.get("passed"),
                        score=round(float(review.get("score", 0.0)), 2),
                        issues=review.get("issues", []),
                        mode=review.get("mode", "rule"),
                        attempt=latest.get("attempts", 1),
                        elapsed_ms=_elapsed_ms(started),
                    )

                elif node in DOMAINS:
                    yield await step_event(
                        "generate",
                        "completed",
                        answer=update.get("answer", ""),
                        domain=node,
                        attempt=update.get("attempts", 1),
                        elapsed_ms=_elapsed_ms(started),
                    )

            yield await done_event(
                latest.get("sources", []),
                review=latest.get("review"),
                sources_detail=build_sources_detail(latest.get("context_docs", [])),
            )

        except Exception as exc:  # 单点失败不应让连接悬挂
            logger.exception("问答链路异常")
            yield await error_event(str(exc))

    return EventSourceResponse(event_stream())
