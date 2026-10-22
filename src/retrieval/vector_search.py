"""向量检索模块：FAISS 索引构建与相似度查询"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from langchain_core.documents import Document

from src.config import load_config

logger = logging.getLogger(__name__)

_ENGINE_CACHE: dict[str, "VectorSearchEngine"] = {}
_ENGINE_LOCK = threading.Lock()


def build_documents(items: list[dict], source_type: str = "law") -> list[Document]:
    """将结构化数据转为 LangChain Document

    Args:
        items: 法规或案例的结构化数据列表
        source_type: "law" 或 "case"

    Returns:
        page_content 为可检索正文，metadata 保留溯源字段
    """
    docs = []
    for item in items:
        if source_type == "law":
            content = f"{item['law_name']} {item['article_number']}：{item['content']}"
            metadata = {
                "source_type": "law",
                "law_name": item["law_name"],
                "article_number": item["article_number"],
                "chapter_path": item.get("chapter_path", item.get("chapter", "")),
                "domain": item.get("domain", ""),
            }
        else:
            content = f"案例{item['case_id']}：{item['fact']} 判决：{item['judgment']}"
            metadata = {
                "source_type": "case",
                "case_id": item["case_id"],
                "crime": item.get("crime", ""),
            }
        docs.append(Document(page_content=content, metadata=metadata))
    return docs


class VectorSearchEngine:
    """向量检索引擎（OpenAI 兼容 Embedding + FAISS 本地索引）"""

    def __init__(self, verbose: bool = False):
        config = load_config()
        embedding_cfg = config.get("embedding", {})
        if not embedding_cfg.get("api_key"):
            raise ValueError(
                "缺少 Embedding API Key：请在 .env 填写 DASHSCOPE_API_KEY"
            )

        from src.retrieval.embedding import build_embeddings

        # 分批 + 并发：单批上限由厂商决定，一次塞 3942 条会被拒
        self.embeddings = build_embeddings(embedding_cfg, verbose=verbose)
        self.vectorstore = None

    def build_index(self, documents: list[Document]) -> None:
        from langchain_community.vectorstores import FAISS

        if not documents:
            raise ValueError("构建索引需要至少一条文档")
        self.vectorstore = FAISS.from_documents(documents, self.embeddings)

    def save_index(self, path: str) -> None:
        if self.vectorstore:
            Path(path).mkdir(parents=True, exist_ok=True)
            self.vectorstore.save_local(path)

    def load_index(self, path: str) -> None:
        from langchain_community.vectorstores import FAISS

        if not Path(path).exists():
            raise FileNotFoundError(f"FAISS 索引不存在：{path}")

        self.vectorstore = FAISS.load_local(
            path, self.embeddings, allow_dangerous_deserialization=True
        )

    def load_or_build(self, path: str, documents: list[Document] | None = None) -> None:
        """优先加载本地索引，缺失时用 documents 重建并落盘"""
        try:
            self.load_index(path)
            return
        except FileNotFoundError:
            logger.info("未找到索引，开始构建：%s", path)

        if documents is None:
            from src.config import load_config
            from src.data.collector import load_cases, load_laws

            documents = build_documents(load_laws(), "law")
            # 案例默认不入索引，理由见 retrieval.include_cases_in_text_search
            if (load_config().get("retrieval") or {}).get(
                "include_cases_in_text_search", False
            ):
                documents += build_documents(load_cases(), "case")

        self.build_index(documents)
        self.save_index(path)

    def query(self, query_text: str, top_k: int = 5) -> list[Document]:
        if not self.vectorstore:
            raise ValueError("索引未构建，请先调用 build_index 或 load_index")
        return self.vectorstore.similarity_search(query_text, k=top_k)


def get_engine(index_path: str | Path) -> "VectorSearchEngine":
    """按索引路径缓存引擎，进程内只构造一次

    构造 Embedding 客户端 + 反序列化 FAISS 索引合计约 5 秒。
    如果每次请求都重建，向量检索就成了"每次多等 5 秒"的净亏损。
    """
    key = str(Path(index_path).resolve())

    cached = _ENGINE_CACHE.get(key)
    if cached is not None:
        return cached

    with _ENGINE_LOCK:
        cached = _ENGINE_CACHE.get(key)
        if cached is None:
            engine = VectorSearchEngine()
            engine.load_index(key)
            _ENGINE_CACHE[key] = cached = engine
    return cached


def reset_engine_cache() -> None:
    """重建/替换索引后调用，避免进程继续持有旧索引"""
    with _ENGINE_LOCK:
        _ENGINE_CACHE.clear()
