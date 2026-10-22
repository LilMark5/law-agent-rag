"""Embedding 客户端：OpenAI 兼容协议 + 显式分批 + 并发 + 重试

为什么不用 langchain 社区的 ``DashScopeEmbeddings``：
它把整个文档列表塞进**一次**请求，3942 条法条必然超出厂商的单批上限
（text-embedding-v3 单批最多 10 条），建索引直接失败。

这里做三件它不做的事：
1. 显式分批（默认 10 条/批），并记录批次进度
2. 有限并发（默认 4 线程），把 3942 条的建库时间从十几分钟压到几分钟
3. 指数退避重试，命中限流时不会整批报废

同时因为是 OpenAI 兼容协议，换成硅基流动 bge-m3、OpenAI、通义千问任何一家
只要改 ``config/settings.yaml`` 的 ``base_url`` / ``model`` 即可，代码不动。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from langchain_core.embeddings import Embeddings
from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbeddings(Embeddings):
    """把 OpenAI 兼容的 /embeddings 接口包装成 LangChain Embeddings"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        dimensions: int | None = None,
        batch_size: int = 10,
        concurrency: int = 4,
        timeout: int = 60,
        max_retries: int = 3,
        verbose: bool = False,
    ) -> None:
        if not api_key:
            raise ValueError(
                "缺少 Embedding API Key：请在 .env 填写 DASHSCOPE_API_KEY"
            )
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, int(batch_size))
        self.concurrency = max(1, int(concurrency))
        self.max_retries = max(0, int(max_retries))
        self.verbose = verbose
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._done = 0

    # ---- 对外接口 -------------------------------------------------
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        batches = [
            texts[i : i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]
        total = len(texts)
        self._done = 0

        if self.concurrency == 1 or len(batches) == 1:
            results = [self._embed_batch(batch) for batch in batches]
        else:
            # 保持顺序：executor.map 按提交顺序返回
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                results = list(pool.map(self._embed_batch, batches))

        vectors = [vec for batch in results for vec in batch]
        if len(vectors) != total:
            raise RuntimeError(
                f"Embedding 数量不匹配：期望 {total}，实际 {len(vectors)}"
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]

    # ---- 内部实现 -------------------------------------------------
    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload: dict = {
            "model": self.model,
            "input": batch,
            "encoding_format": "float",
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.embeddings.create(**payload)
                # 兼容模式返回的 index 不一定有序，按 index 还原
                ordered = sorted(response.data, key=lambda item: item.index)
                vectors = [item.embedding for item in ordered]

                self._done += len(batch)
                if self.verbose:
                    logger.info("Embedding 进度：%d 条", self._done)
                return vectors
            except Exception as exc:  # 网络抖动 / 限流 / 超时
                if attempt >= self.max_retries:
                    raise RuntimeError(
                        f"Embedding 请求失败（已重试 {self.max_retries} 次）：{exc}"
                    ) from exc
                wait = 2**attempt
                logger.warning(
                    "Embedding 批次失败（第 %d 次），%ds 后重试：%s",
                    attempt + 1,
                    wait,
                    str(exc)[:160],
                )
                time.sleep(wait)

        raise RuntimeError("unreachable")


def build_embeddings(embedding_cfg: dict | None = None, verbose: bool = False):
    """按 settings.yaml 的 embedding 段构造客户端"""
    if embedding_cfg is None:
        from src.config import load_config

        embedding_cfg = load_config().get("embedding", {})

    return OpenAICompatibleEmbeddings(
        model=embedding_cfg.get("model", "text-embedding-v3"),
        api_key=embedding_cfg.get("api_key", ""),
        base_url=embedding_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        dimensions=embedding_cfg.get("dimension") or None,
        batch_size=int(embedding_cfg.get("batch_size", 10)),
        concurrency=int(embedding_cfg.get("concurrency", 4)),
        timeout=int(embedding_cfg.get("timeout", 60)),
        verbose=verbose,
    )
