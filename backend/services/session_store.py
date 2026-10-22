"""会话存储：多轮对话的轻量持久化

设计取舍（面试可讲）：
- **热存储 + 落盘**：内存 dict 做热路径，每次写操作同步写入 ``data/sessions.json``，
  进程重启后从文件恢复 —— 这才是「多轮持久化」，而不是「进程内一次性历史」。
- **单机、无锁分布式**：本项目是单用户演示，不需要分布式一致；并发写用一把
  ``threading.Lock`` 串行化，避免 SSE 并发刷新同一会话时丢轮次。
- **标题取首问前 30 字**：历史列表页不需要全文，首问即可做标题。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from src.config import get_project_root

_lock = threading.Lock()


class SessionStore:
    def __init__(self, path: Path | None = None):
        self._path = path or (get_project_root() / "data" / "sessions.json")
        self._sessions: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._sessions = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # 文件损坏等异常不应让存储不可用
            self._sessions = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._sessions, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:  # 落盘失败不影响本轮回答，仅丢持久化
            pass

    def add_turn(
        self,
        conversation_id: str,
        question: str,
        answer: str,
        domain: str = "",
        domain_zh: str = "",
    ) -> None:
        with _lock:
            session = self._sessions.setdefault(
                conversation_id,
                {
                    "id": conversation_id,
                    "title": question[:30],
                    "turns": [],
                    "updated_at": time.time(),
                },
            )
            session["turns"].append(
                {
                    "question": question,
                    "answer": answer,
                    "domain": domain,
                    "domain_zh": domain_zh,
                }
            )
            session["updated_at"] = time.time()
            self._save()

    def list_sessions(self) -> list[dict]:
        with _lock:
            items = sorted(
                self._sessions.values(),
                key=lambda s: s.get("updated_at", 0),
                reverse=True,
            )
            return [
                {
                    "id": s["id"],
                    "title": s.get("title", ""),
                    "turns": len(s.get("turns", [])),
                    "updated_at": s.get("updated_at", 0),
                }
                for s in items
            ]

    def get_session(self, conversation_id: str) -> dict | None:
        with _lock:
            return self._sessions.get(conversation_id)


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
