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
import uuid

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.services.session_store import get_session_store
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
    # 前端可回传会话 ID 以延续同一会话；未传时后端生成一个，并在 done 事件里回传，
    # 前端据此在后续轮次带上同一个 ID，形成持久化的多轮对话。
    conversation_id = (body.get("conversation_id") or "").strip() or uuid.uuid4().hex

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
                        keywords=update.get("keywords", []),
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
                        # 「语料里存在但本轮未召回」的引用：不是编造，而是召回瓶颈的
                        # 证据，单独暴露出来供前端展示，体现审查的精细度。
                        unretrieved=review.get("unretrieved", []),
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

            # 回答完成后落盘这一轮，供 /api/history 读取。审查回炉时 answer 会被
            # 多次覆盖，latest 里最终保留的是最后一版，正好是应该记录的那版。
            final_answer = latest.get("answer", "")
            if final_answer:
                get_session_store().add_turn(
                    conversation_id,
                    question,
                    final_answer,
                    domain=latest.get("domain", ""),
                    domain_zh=latest.get("domain_zh", ""),
                )

            yield await done_event(
                latest.get("sources", []),
                review=latest.get("review"),
                sources_detail=build_sources_detail(latest.get("context_docs", [])),
                conversation_id=conversation_id,
            )

        except Exception as exc:  # 单点失败不应让连接悬挂
            logger.exception("问答链路异常")
            yield await error_event(str(exc))

    return EventSourceResponse(event_stream())
