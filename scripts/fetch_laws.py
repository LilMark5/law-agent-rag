"""抓取国家法律法规数据库的法规正文，生成可检索语料。

数据来源：国家法律法规数据库 https://flk.npc.gov.cn （全国人大官方，公开数据）

用法：
    python scripts/fetch_laws.py --list              # 查看内置语料清单
    python scripts/fetch_laws.py --check             # 只检查能否检索到，不下载
    python scripts/fetch_laws.py --all               # 抓全部（默认跳过已存在的）
    python scripts/fetch_laws.py --only 中华人民共和国刑法
    python scripts/fetch_laws.py --all --force       # 强制重抓

产物：
    data/raw/laws/<法规名>.json      单部法规（元数据 + 条文）
    data/processed/laws.json         合并后的全部条文（检索层读取）
    data/processed/laws_meta.json    每部法规的抓取摘要
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.flk_client import FlkError, fetch_law  # noqa: E402
from src.data.law_parser import parse_law  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "laws"
PROCESSED_DIR = ROOT / "data" / "processed"

# 语料清单：按项目五个领域编排，保证路由到任一领域都有条文可检索
LAW_CATALOG: list[dict[str, str]] = [
    # —— 劳动法 ——
    {"title": "中华人民共和国劳动法", "domain": "labor_law"},
    {"title": "中华人民共和国劳动合同法", "domain": "labor_law"},
    {"title": "中华人民共和国劳动争议调解仲裁法", "domain": "labor_law"},
    {"title": "中华人民共和国社会保险法", "domain": "labor_law"},
    {"title": "中华人民共和国就业促进法", "domain": "labor_law"},
    {"title": "中华人民共和国安全生产法", "domain": "labor_law"},
    {"title": "中华人民共和国职业病防治法", "domain": "labor_law"},
    {"title": "工伤保险条例", "domain": "labor_law"},
    {"title": "职工带薪年休假条例", "domain": "labor_law"},
    {"title": "女职工劳动保护特别规定", "domain": "labor_law"},
    # —— 民法 ——
    {"title": "中华人民共和国民法典", "domain": "civil_law"},
    {"title": "中华人民共和国消费者权益保护法", "domain": "civil_law"},
    {"title": "中华人民共和国个人信息保护法", "domain": "civil_law"},
    # —— 刑法 ——
    {"title": "中华人民共和国刑法", "domain": "criminal_law"},
    # —— 行政法 ——
    {"title": "中华人民共和国行政处罚法", "domain": "admin_law"},
    {"title": "中华人民共和国行政许可法", "domain": "admin_law"},
    {"title": "中华人民共和国行政强制法", "domain": "admin_law"},
    {"title": "中华人民共和国行政复议法", "domain": "admin_law"},
    {"title": "中华人民共和国行政诉讼法", "domain": "admin_law"},
    {"title": "中华人民共和国治安管理处罚法", "domain": "admin_law"},
    # —— 诉讼程序（通用）——
    {"title": "中华人民共和国民事诉讼法", "domain": "general"},
    {"title": "中华人民共和国刑事诉讼法", "domain": "general"},
    # —— 司法解释（实务引用频率极高，且能体现"法条+解释"两层检索）——
    {"title": "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）", "domain": "labor_law"},
    {"title": "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释", "domain": "civil_law"},
]


def _safe_name(title: str) -> str:
    return title.replace("/", "_").replace("\\", "_")


def _raw_path(title: str) -> Path:
    return RAW_DIR / f"{_safe_name(title)}.json"


def _load_existing(title: str) -> dict | None:
    path = _raw_path(title)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def cmd_list() -> None:
    print(f"内置语料清单（{len(LAW_CATALOG)} 部）\n")
    for i, item in enumerate(LAW_CATALOG, 1):
        cached = "已缓存" if _raw_path(item["title"]).exists() else ""
        print(f"{i:>2}. [{item['domain']:<11}] {item['title']} {cached}")


def cmd_check() -> None:
    from src.data.flk_client import resolve_law

    ok = 0
    for item in LAW_CATALOG:
        try:
            row = resolve_law(item["title"])
            if row:
                ok += 1
                print(f"[OK] {item['title']}  ({row.get('flxz')}, {row.get('gbrq')})")
            else:
                print(f"[MISS] {item['title']}")
        except FlkError as exc:
            print(f"[ERR] {item['title']}: {exc}")
        time.sleep(0.4)
    print(f"\n可检索 {ok}/{len(LAW_CATALOG)}")


def fetch_one(item: dict, *, force: bool, delay: float) -> dict | None:
    title = item["title"]
    cached = None if force else _load_existing(title)
    if cached:
        print(f"[SKIP] {title}（已缓存 {len(cached.get('articles', []))} 条，--force 可重抓）")
        return cached

    try:
        meta, paragraphs = fetch_law(title)
        articles = parse_law(paragraphs, meta["law_name"], meta)
    except (FlkError, ValueError) as exc:
        print(f"[FAIL] {title}: {exc}")
        return None

    if not articles:
        print(f"[FAIL] {title}: 解析后无条文")
        return None

    payload = {"metadata": {**meta, "domain": item["domain"]}, "articles": articles}
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    _raw_path(title).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[OK]   {title}：{len(articles)} 条"
        f"（{articles[0]['article_number']} ~ {articles[-1]['article_number']}）"
    )
    time.sleep(delay)
    return payload


def rebuild_merged() -> tuple[int, int]:
    """把 data/raw/laws 下的单部法规合并成检索层读取的两个文件"""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    merged: list[dict] = []
    metas: list[dict] = []

    for item in LAW_CATALOG:
        payload = _load_existing(item["title"])
        if not payload:
            continue
        articles = payload.get("articles", [])
        for art in articles:
            merged.append({**art, "domain": item["domain"]})
        meta = payload.get("metadata", {})
        metas.append(
            {
                "law_name": meta.get("law_name", item["title"]),
                "domain": item["domain"],
                "category": meta.get("category", ""),
                "publish_date": meta.get("publish_date", ""),
                "effective_date": meta.get("effective_date", ""),
                "status": meta.get("status", ""),
                "bbbs": meta.get("bbbs", ""),
                "article_count": len(articles),
            }
        )

    (PROCESSED_DIR / "laws.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PROCESSED_DIR / "laws_meta.json").write_text(
        json.dumps(metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(merged), len(metas)


def cmd_fetch(titles: list[str], *, force: bool, delay: float) -> None:
    if titles:
        wanted = set(titles)
        targets = [i for i in LAW_CATALOG if i["title"] in wanted]
        missing = wanted - {i["title"] for i in targets}
        for name in sorted(missing):
            targets.append({"title": name, "domain": "general"})
    else:
        targets = LAW_CATALOG

    print(f"开始抓取 {len(targets)} 部法规\n")
    ok = 0
    for item in targets:
        if fetch_one(item, force=force, delay=delay):
            ok += 1

    total, laws = rebuild_merged()
    print(f"\n完成：{ok}/{len(targets)} 部成功")
    print(f"合并语料：{total} 条，覆盖 {laws} 部法规")


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取国家法律法规数据库法规正文")
    parser.add_argument("--list", action="store_true", help="查看内置语料清单")
    parser.add_argument("--check", action="store_true", help="只检查可检索性")
    parser.add_argument("--all", action="store_true", help="抓取全部")
    parser.add_argument("--only", nargs="+", metavar="法规名", help="只抓指定法规")
    parser.add_argument("--force", action="store_true", help="忽略缓存重新抓取")
    parser.add_argument("--delay", type=float, default=0.6, help="每次请求间隔秒数")
    parser.add_argument("--rebuild", action="store_true", help="只合并已有缓存")
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.check:
        cmd_check()
    elif args.rebuild:
        total, laws = rebuild_merged()
        print(f"合并语料：{total} 条，覆盖 {laws} 部法规")
    elif args.all or args.only:
        cmd_fetch(args.only or [], force=args.force, delay=args.delay)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
