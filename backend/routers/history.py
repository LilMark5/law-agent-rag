"""GET /api/history —— 多轮对话历史（只读）

会话由 ``chat.py`` 在每轮问答结束后写入 ``SessionStore``（落盘到
``data/sessions.json``）。这里只提供查询：会话列表 + 单会话详情，
供前端历史页展示真实的对话记录，替代原先的 mock 数据。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.services.session_store import get_session_store

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/history")
async def list_history():
    """按最近更新倒序返回会话列表，元素含 id / title / turns / updated_at。"""
    return get_session_store().list_sessions()


@router.get("/history/{conversation_id}")
async def get_history(conversation_id: str):
    """返回单个会话的完整轮次（question / answer / domain）。"""
    session = get_session_store().get_session(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session
