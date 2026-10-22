"""把 CAIL2018 案例导入 Neo4j

数据默认取 ``data/raw/cail/data_valid.json``（exercise_contest 验证集，
17,131 条）。该文件不随仓库分发，获取方式见
``docs/onboarding/CAIL案例接入方案.md``。

用法：
    python scripts/import_cail.py --dry-run          # 只转换、打印，不写库
    python scripts/import_cail.py                    # 转换 + 落盘 + 导入
    python scripts/import_cail.py --limit 5000       # 先导一小批试水
    python scripts/import_cail.py --clear            # 导入前清空既有 Case 节点

导入完成后 ``data/processed/cases.json`` 会被覆盖，BM25/向量语料随之变化。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def summarize(cases: list[dict]) -> dict:
    """统计转换结果，用来发现"全空"这类静默失败"""
    crimes: set[str] = set()
    articles: set[int] = set()
    for case in cases:
        crimes.update(c for c in case["crime"].split("、") if c)
        articles.update(case.get("article_numbers") or [])

    multi_article = sum(1 for case in cases if len(case.get("article_numbers") or []) > 1)
    no_judgment = sum(1 for case in cases if not case["judgment"])

    return {
        "cases": len(cases),
        "crimes": len(crimes),
        "articles": len(articles),
        "multi_article": multi_article,
        "no_judgment": no_judgment,
    }


def print_sample(cases: list[dict], limit: int = 3) -> None:
    for case in cases[:limit]:
        print(f"\n  {case['case_id']}  [{case['crime']}]  {case['judgment'] or '（刑期未标注）'}")
        print(f"  适用法条：{case['applicable_law']}")
        fact = case["fact"]
        print(f"  事实：{fact[:80]}{'…' if len(fact) > 80 else ''}")


def clear_cases(driver) -> int:
    with driver.session() as session:
        result = session.run("MATCH (c:Case) DETACH DELETE c RETURN count(*) AS n")
        return result.single()["n"]


def verify(driver) -> tuple[int, int]:
    with driver.session() as session:
        cases = session.run("MATCH (c:Case) RETURN count(c) AS n").single()["n"]
        relations = session.run(
            "MATCH (:Case)-[r:APPLIES]->(:Law) RETURN count(r) AS n"
        ).single()["n"]
    return cases, relations


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 CAIL2018 案例到 Neo4j")
    parser.add_argument(
        "--input",
        default=str(PROJECT_ROOT / "data" / "raw" / "cail" / "data_valid.json"),
        help="CAIL 数据文件（JSONL 或 JSON 数组）",
    )
    parser.add_argument("--limit", type=int, default=None, help="最多导入多少条")
    parser.add_argument("--prefix", default="CAIL", help="case_id 前缀，导入多个 split 时区分")
    parser.add_argument("--dry-run", action="store_true", help="只转换并打印，不写库")
    parser.add_argument("--clear", action="store_true", help="导入前清空既有 Case 节点")
    parser.add_argument(
        "--no-save", action="store_true", help="不覆盖 data/processed/cases.json"
    )
    args = parser.parse_args()

    from src.data.cail_loader import load_cases

    input_path = Path(args.input)
    print(f"读取：{input_path}")
    if not input_path.exists():
        print("文件不存在。获取方式见 docs/onboarding/CAIL案例接入方案.md")
        return 1

    started = time.perf_counter()
    cases = load_cases(input_path, limit=args.limit, prefix=args.prefix)
    if not cases:
        print("没有可导入的案例（事实或法条缺失的记录会被跳过）")
        return 1

    stats = summarize(cases)
    print(
        f"转换完成：{stats['cases']} 条案例 / {stats['crimes']} 个罪名 / "
        f"{stats['articles']} 个法条 / 多法条 {stats['multi_article']} 条 / "
        f"刑期未标注 {stats['no_judgment']} 条"
    )
    print_sample(cases)

    if args.dry_run:
        print("\n--dry-run：未写入任何数据")
        return 0

    if not args.no_save:
        from src.data.collector import save_data

        path = save_data(cases, "cases.json")
        print(f"\n已写入语料：{path}")

    from src.data.kg_builder import (
        ensure_constraints,
        get_neo4j_driver,
        import_cases,
        import_relations,
    )

    driver = get_neo4j_driver()
    try:
        ensure_constraints(driver)
        if args.clear:
            removed = clear_cases(driver)
            print(f"已清空既有 Case 节点：{removed} 个")

        case_count = import_cases(cases, driver)
        relation_count = import_relations(cases, driver)
    finally:
        driver.close()

    total_cases, total_relations = verify(get_neo4j_driver())

    elapsed = time.perf_counter() - started
    print(
        f"\n导入完成：本次写入 {case_count} 个 Case、{relation_count} 条 APPLIES 关系，"
        f"耗时 {elapsed:.1f}s"
    )
    print(f"库内合计：Case {total_cases} 个 / APPLIES {total_relations} 条")
    if total_cases and total_relations < total_cases:
        print(
            "提示：关系数少于案例数，说明部分条号在语料中找不到对应 Law 节点。"
            "先运行 python scripts/fetch_laws.py --all 补齐法条语料。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
