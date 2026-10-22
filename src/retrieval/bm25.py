"""BM25 词汇检索：法条语料的零成本基线

为什么法律检索需要一路词汇检索：
    法条问句里最关键的往往是精确术语（"二倍工资""取保候审""诉讼时效"），
    向量检索对这类低频专有词并不敏感；BM25 依靠词频与逆文档频率，
    恰好补上这个短板。工业界的法律检索系统普遍是"BM25 + 向量"双路。

为什么自己实现：
    中文需要分词才能用标准 BM25。这里不引入 jieba 之类的分词依赖，
    改用**字 unigram + bigram** 作为 token——中文法律文本用二元组切分
    在实践中效果接近分词，且对未登录词（新罪名、新条款表述）更稳。

依赖：仅标准库 + langchain_core.Document（项目已有）。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

from langchain_core.documents import Document

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_RE = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文按字 + 二元组切分，英文数字按词切分

    >>> tokenize("二倍工资")[:3]
    ['二', '倍', '工']
    """
    tokens: list[str] = []
    for run in _CJK_RE.findall(text):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    tokens.extend(match.group(0).lower() for match in _ASCII_RE.finditer(text))
    return tokens


class BM25Index:
    """内存版 BM25（Okapi），语料规模到十万条以内都够用"""

    def __init__(self, documents: list[Document], k1: float = 1.5, b: float = 0.75):
        if not documents:
            raise ValueError("BM25 索引需要至少一条文档")

        self.documents = documents
        self.k1 = k1
        self.b = b
        self.term_freqs: list[Counter[str]] = []
        self.lengths: list[int] = []
        doc_freq: Counter[str] = Counter()

        for doc in documents:
            tokens = tokenize(doc.page_content)
            tf = Counter(tokens)
            self.term_freqs.append(tf)
            self.lengths.append(len(tokens))
            doc_freq.update(tf.keys())

        self.avg_length = sum(self.lengths) / len(self.lengths)
        total = len(documents)
        self.idf = {
            term: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def search(self, query: str, top_k: int = 8) -> list[Document]:
        """返回按 BM25 得分降序的文档，得分写入 metadata["bm25_score"]"""
        query_terms = [t for t in tokenize(query) if t in self.idf]
        if not query_terms:
            return []

        scored: list[tuple[float, int]] = []
        for idx, tf in enumerate(self.term_freqs):
            length_norm = 1 - self.b + self.b * self.lengths[idx] / self.avg_length
            score = 0.0
            for term in query_terms:
                freq = tf.get(term)
                if not freq:
                    continue
                score += self.idf[term] * (freq * (self.k1 + 1)) / (
                    freq + self.k1 * length_norm
                )
            if score > 0:
                scored.append((score, idx))

        scored.sort(reverse=True)
        results = []
        for score, idx in scored[:top_k]:
            doc = self.documents[idx]
            doc.metadata = {**doc.metadata, "bm25_score": round(score, 3), "retrieved_by": "bm25"}
            results.append(doc)
        return results


@lru_cache(maxsize=2)
def _build_index(domain: str | None = None) -> BM25Index:
    """按需构建并缓存索引（同一进程内只切一次词）"""
    from src.config import load_config
    from src.data.collector import load_cases, load_laws
    from src.retrieval.vector_search import build_documents

    docs = build_documents(load_laws(domain), source_type="law")

    # 案例默认不进词汇检索。接入 CAIL 后案例有 1.7 万条，事实里全是
    # 「盗窃」「数额较大」这类词，会成批挤进 top-K 把法条顶出去；
    # 而类案本来就该由图谱通道按罪名/条号精确召回，不该靠全文相似度碰运气。
    include_cases = bool(
        (load_config().get("retrieval") or {}).get("include_cases_in_text_search", False)
    )
    if domain is None and include_cases:
        docs += build_documents(load_cases(), source_type="case")

    return BM25Index(docs)


def bm25_search(question: str, top_k: int = 8, domain: str | None = None) -> list[Document]:
    """BM25 检索入口

    Args:
        question: 用户问题
        top_k: 返回条数
        domain: 限定领域（如 labor_law），None 为全语料
    """
    return _build_index(domain).search(question, top_k=top_k)


def clear_cache() -> None:
    """语料变更后清缓存（抓取脚本/测试用）"""
    _build_index.cache_clear()
