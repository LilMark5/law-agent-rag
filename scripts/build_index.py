"""离线构建 FAISS 向量索引

必须单独执行，不要指望服务启动时自动建：
3942 条法条会产生上千次 Embedding 调用，放在请求线程里会把首屏拖到几分钟。

用法：
    uv run python scripts/build_index.py
    uv run python scripts/build_index.py --force   # 已有索引也重建
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 FAISS 向量索引")
    parser.add_argument("--force", action="store_true", help="索引已存在时也重建")
    args = parser.parse_args()

    config = load_config()
    index_path = PROJECT_ROOT / (config.get("retrieval") or {}).get(
        "index_path", "data/embeddings"
    )

    if (index_path / "index.faiss").exists() and not args.force:
        print(f"索引已存在：{index_path}")
        print("如需重建请加 --force（会覆盖现有索引）")
        return 0

    if not (config.get("embedding") or {}).get("api_key"):
        print("缺少 Embedding Key：请在 .env 填入 DASHSCOPE_API_KEY")
        print("不建索引也能启动服务，检索会自动降级为 BM25 + 图谱")
        return 1

    from src.data.collector import corpus_stats
    from src.retrieval.fusion import build_vector_index

    stats = corpus_stats()
    print(f"语料：{stats['laws']} 部法规 / {stats['articles']} 条条文")
    print(f"开始构建索引 → {index_path}（会调用 Embedding 接口，可能需要几分钟）")

    started = time.perf_counter()
    try:
        count = build_vector_index()
    except Exception as exc:
        print(f"构建失败：{exc}")
        print("常见原因：Key 无效（401）、额度不足、网络不通")
        return 1

    elapsed = time.perf_counter() - started
    print(f"完成：{count} 条文档，耗时 {elapsed:.1f}s")
    print(f"索引位置：{index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
