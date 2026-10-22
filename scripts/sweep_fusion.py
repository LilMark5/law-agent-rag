"""融合权重扫描：找出加权 RRF 的最优配比

等权 RRF 不一定优于单路——当某一路明显更弱时，它的"噪声提名"会和强通道的
有效提名等值累加，融合结果反而变差。这个脚本把每一路的结果先算一次缓存起来，
再在权重网格上重算指标，避免重复调用 Embedding 接口。

用法：
    uv run python scripts/sweep_fusion.py
    uv run python scripts/sweep_fusion.py --top-k 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.documents import Document  # noqa: E402

from src.config import load_config  # noqa: E402
from src.retrieval.bm25 import bm25_search  # noqa: E402
from src.retrieval.fusion import fuse_many  # noqa: E402
from src.retrieval.vector_search import get_engine  # noqa: E402


def hit(doc: Document, item: dict) -> bool:
    meta = doc.metadata or {}
    law_name = str(meta.get("law_name") or "") or doc.page_content
    targets = [(item["law"], item["article"])] + [
        (alt["law"], alt["article"]) for alt in item.get("also_accept") or []
    ]
    article = str(meta.get("article_number") or "").replace(" ", "")
    for law, art in targets:
        if law not in law_name:
            continue
        if article and article == art:
            return True
        if not article and art in doc.page_content:
            return True
    return False


def metrics(gold: list[dict], ranked: dict[str, list[Document]], top_k: int) -> tuple[float, float]:
    recalls, rrs = [], []
    for item in gold:
        rank = None
        for i, doc in enumerate(ranked[item["id"]][:top_k], start=1):
            if hit(doc, item):
                rank = i
                break
        recalls.append(1.0 if rank else 0.0)
        rrs.append(1.0 / rank if rank else 0.0)
    return sum(recalls) / len(recalls), sum(rrs) / len(rrs)


def main() -> int:
    parser = argparse.ArgumentParser(description="加权 RRF 权重扫描")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--gold", default=str(PROJECT_ROOT / "data" / "eval" / "gold.json")
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=0,
        help="每路先取多少条再融合（默认读配置）。融合要'深召回、浅截断'，"
        "只取 5 条就融合，两路几乎重合，融合等于白做",
    )
    args = parser.parse_args()

    cfg = load_config().get("retrieval", {})
    rrf_k = int(cfg.get("rrf_k", 60))
    bm25_k = args.depth or int(cfg.get("bm25_top_k", 8))
    vec_k = args.depth or int(cfg.get("vector_top_k", 5))

    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    engine = get_engine(PROJECT_ROOT / cfg.get("index_path", "data/embeddings"))

    print(f"预计算 {len(gold)} 条用例的三路结果（只算一次，供网格复用）…")
    channel_cache: dict[str, dict[str, list[Document]]] = {}
    for item in gold:
        channel_cache[item["id"]] = {
            "vector": engine.query(item["question"], top_k=vec_k),
            "bm25": bm25_search(item["question"], top_k=bm25_k),
        }

    # 单路基线
    print(f"\n{'配置':<34}{'Recall@' + str(args.top_k):<12}{'MRR':<8}")
    print("-" * 56)
    for name in ("vector", "bm25"):
        ranked = {iid: ch[name] for iid, ch in channel_cache.items()}
        r, m = metrics(gold, ranked, args.top_k)
        print(f"{name + ' 单路':<34}{r:<12.3f}{m:<8.3f}")

    # 等权融合
    ranked = {
        iid: fuse_many(ch, top_k=args.top_k, rrf_k=rrf_k)
        for iid, ch in channel_cache.items()
    }
    r, m = metrics(gold, ranked, args.top_k)
    print(f"{'等权 RRF (1.0 / 1.0)':<34}{r:<12.3f}{m:<8.3f}")

    # 网格：vector 固定 1.0，扫 bm25 权重
    print(f"\n{'vector':<8}{'bm25':<8}{'Recall@' + str(args.top_k):<12}{'MRR':<8}")
    print("-" * 36)
    best = (0.0, 0.0, None)
    for bm25_w in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0):
        weights = {"vector": 1.0, "bm25": bm25_w}
        ranked = {
            iid: fuse_many(ch, top_k=args.top_k, rrf_k=rrf_k, weights=weights)
            for iid, ch in channel_cache.items()
        }
        r, m = metrics(gold, ranked, args.top_k)
        mark = ""
        if r > best[0] or (r == best[0] and m > best[1]):
            best = (r, m, bm25_w)
            mark = "  ←"
        print(f"{1.0:<8.1f}{bm25_w:<8.1f}{r:<12.3f}{m:<8.3f}{mark}")

    print(f"\n结论：vector=1.0 / bm25={best[2]} 时最佳，Recall {best[0]:.3f}、MRR {best[1]:.3f}")
    print("注意：33 条 gold 上做 8 组扫描有过拟合风险，正式结论应扩充到 100+ 条后复核。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
