"""将法条语料与案例导入 Neo4j 知识图谱

语料优先取 data/processed/laws.json（scripts/fetch_laws.py 抓取），
缺失时回退到内置示例。

用法：
    python scripts/import_sample_data.py
    python scripts/import_sample_data.py --limit 200   # 只导前 200 条，用于快速验证
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.collector import corpus_stats, load_cases, load_laws  # noqa: E402
from src.data.kg_builder import build_knowledge_graph  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="导入法条与案例到 Neo4j")
    parser.add_argument("--limit", type=int, default=0, help="只导入前 N 条法条")
    args = parser.parse_args()

    stats = corpus_stats()
    print(
        f"语料来源：{stats['source']}｜{stats['laws']} 部法规｜"
        f"{stats['articles']} 条条文"
    )

    laws = load_laws()
    cases = load_cases()
    if args.limit:
        laws = laws[: args.limit]

    result = build_knowledge_graph(laws, cases)
    print(f"导入完成: {result}")


if __name__ == "__main__":
    main()
