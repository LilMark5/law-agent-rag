"""部署自检：一条命令看清"现在能不能跑通、缺哪一环"

用法：
    uv run python scripts/doctor.py            # 静态检查
    uv run python scripts/doctor.py --check-api  # 额外真实调用一次 LLM / Embedding

退出码 0 表示无阻断项（可以有 warning），1 表示存在必须修复的 FAIL。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OK = "[OK]  "
WARN = "[WARN]"
FAIL = "[FAIL]"


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    def ok(self, title: str, detail: str = "") -> None:
        print(f"{OK} {title}{('：' + detail) if detail else ''}")

    def warn(self, title: str, detail: str = "", hint: str = "") -> None:
        self.warnings += 1
        print(f"{WARN} {title}{('：' + detail) if detail else ''}")
        if hint:
            print(f"       → {hint}")

    def fail(self, title: str, detail: str = "", hint: str = "") -> None:
        self.failures += 1
        print(f"{FAIL} {title}{('：' + detail) if detail else ''}")
        if hint:
            print(f"       → {hint}")


def check_python(report: Report) -> None:
    version = sys.version_info
    if version >= (3, 11):
        report.ok("Python 版本", f"{version.major}.{version.minor}.{version.micro}")
    else:
        report.fail(
            "Python 版本过低",
            f"{version.major}.{version.minor}",
            "项目要求 >= 3.11，请用 uv sync 让 uv 自动装 3.11",
        )


def check_dependencies(report: Report) -> None:
    missing: list[str] = []
    for module in ("fastapi", "uvicorn", "yaml", "openai", "neo4j", "langgraph", "faiss"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)

    if not missing:
        report.ok("Python 依赖")
        return

    inside_venv = sys.prefix != sys.base_prefix
    report.fail(
        "Python 依赖缺失",
        ", ".join(missing),
        "在项目根目录执行 uv sync" if inside_venv else "当前不在项目虚拟环境内，请用 uv run python scripts/doctor.py",
    )


def check_config(report: Report) -> tuple[dict, bool]:
    try:
        from src.config import get_project_root, load_config
    except Exception as exc:  # 配置解析失败时后续检查都没有意义
        report.fail("配置加载失败", str(exc), "检查 config/settings.yaml 是否为合法 YAML")
        return {}, False

    config = load_config()
    has_llm_key = bool((config.get("llm") or {}).get("api_key"))
    has_embed_key = bool((config.get("embedding") or {}).get("api_key"))

    env_file = get_project_root() / ".env"
    if env_file.exists():
        report.ok("配置文件", ".env + config/settings.yaml")
    else:
        report.warn("未找到 .env", "将只读取系统环境变量", "cp .env.example .env 后填入 Key")

    if has_llm_key:
        report.ok("LLM Key", f"model={config['llm']['model']}（有效性需加 --check-api）")
    else:
        report.fail(
            "缺少 DEEPSEEK_API_KEY",
            "生成节点会直接报错",
            "在 .env 填入 DEEPSEEK_API_KEY，或临时改用其他 OpenAI 兼容服务",
        )

    if has_embed_key:
        report.ok(
            "Embedding Key",
            f"model={config['embedding']['model']}（有效性需加 --check-api）",
        )
    else:
        report.warn(
            "缺少 DASHSCOPE_API_KEY",
            "向量检索不可用，hybrid 会自动降级为 BM25 + 图谱",
            "需要向量召回时在 .env 填入 DASHSCOPE_API_KEY",
        )
    return config, has_llm_key


def check_corpus(report: Report) -> None:
    try:
        from src.data.collector import corpus_stats
    except Exception as exc:
        report.fail("语料模块不可用", str(exc))
        return

    stats = corpus_stats()
    if stats["articles"] < 100:
        report.warn(
            "语料规模偏小",
            f"{stats['articles']} 条（source={stats['source']}）",
            "运行 uv run python scripts/fetch_laws.py --all 抓取 24 部法规",
        )
        return

    report.ok(
        "法条语料",
        f"{stats['laws']} 部 / {stats['articles']} 条 / {stats.get('chars', 0) // 10000} 万字",
    )


def check_index(report: Report, config: dict) -> None:
    index_path = PROJECT_ROOT / (config.get("retrieval") or {}).get("index_path", "data/embeddings")
    if (index_path / "index.faiss").exists():
        report.ok("向量索引", str(index_path))
    else:
        report.warn(
            "未构建向量索引",
            f"{index_path} 不存在",
            "有 Embedding Key 后执行 uv run python scripts/build_index.py",
        )


def check_neo4j(report: Report, config: dict) -> None:
    cfg = config.get("neo4j") or {}
    try:
        from neo4j import GraphDatabase
    except ImportError:
        report.fail("neo4j 驱动未安装")
        return

    driver = None
    try:
        driver = GraphDatabase.driver(
            cfg.get("uri", "bolt://localhost:7687"),
            auth=(cfg.get("username", "neo4j"), cfg.get("password", "")),
            connection_timeout=5,
        )
        driver.verify_connectivity()
        with driver.session(database=cfg.get("database", "neo4j")) as session:
            laws = session.run("MATCH (l:Law) RETURN count(l) AS c").single()["c"]
            cases = session.run("MATCH (c:Case) RETURN count(c) AS c").single()["c"]
    except Exception as exc:
        report.warn(
            "Neo4j 未连通",
            str(exc).splitlines()[0][:90],
            "docker compose up -d 启动数据库，再 uv run python scripts/import_sample_data.py 导入",
        )
        return
    finally:
        if driver is not None:
            driver.close()

    if laws:
        report.ok("Neo4j 图谱", f"Law {laws} 个 / Case {cases} 个")
    else:
        report.warn(
            "Neo4j 已连通但图谱为空",
            "图检索通道会返回 0 条",
            "uv run python scripts/import_sample_data.py",
        )


def check_frontend(report: Report) -> None:
    node_modules = PROJECT_ROOT / "frontend" / "node_modules"
    if node_modules.exists():
        report.ok("前端依赖", "frontend/node_modules")
    else:
        report.warn("前端依赖未安装", "frontend/node_modules 不存在", "cd frontend && npm install")


def check_api(report: Report, config: dict, has_llm_key: bool) -> None:
    print("\n--- 真实调用检查（会产生少量费用）---")

    if has_llm_key:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=config["llm"]["api_key"],
                base_url=config["llm"]["base_url"],
                timeout=30,
            )
            resp = client.chat.completions.create(
                model=config["llm"]["model"],
                messages=[{"role": "user", "content": "只回复两个字：可用"}],
                max_tokens=8,
            )
            report.ok("LLM 调用", (resp.choices[0].message.content or "").strip()[:20])
        except Exception as exc:
            report.fail(
                "LLM 调用失败",
                str(exc).splitlines()[0][:120],
                "确认 Key 有效、base_url 与 model 名称匹配",
            )

    embed_key = (config.get("embedding") or {}).get("api_key")
    if embed_key:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=embed_key,
                base_url=config["embedding"]["base_url"],
                timeout=30,
            )
            resp = client.embeddings.create(
                model=config["embedding"]["model"],
                input="test",
                dimensions=int(config["embedding"].get("dimension", 1024)),
            )
            report.ok("Embedding 调用", f"维度 {len(resp.data[0].embedding)}")
        except Exception as exc:
            report.fail(
                "Embedding 调用失败",
                str(exc).splitlines()[0][:120],
                "Key 可能已失效，换有效 Key 或先只跑 BM25",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="LilMark 部署自检")
    parser.add_argument("--check-api", action="store_true", help="真实调用一次 LLM / Embedding")
    args = parser.parse_args()

    print("LilMark 部署自检")
    print(f"项目根目录：{PROJECT_ROOT}")
    print("-" * 62)

    report = Report()
    check_python(report)
    check_dependencies(report)
    config, has_llm_key = check_config(report)
    if config:
        check_corpus(report)
        check_index(report, config)
        check_neo4j(report, config)
    check_frontend(report)

    if args.check_api and config:
        check_api(report, config, has_llm_key)

    print("-" * 62)
    if report.failures:
        print(f"阻断项 {report.failures} 个，警告 {report.warnings} 个 —— 修完再启动")
        return 1

    print(f"无阻断项，警告 {report.warnings} 个")
    print("\n启动顺序：")
    print("  1) docker compose up -d")
    print("  2) uv run uvicorn backend.main:app --reload --port 8000")
    print("  3) cd frontend && npm run dev")
    print("  4) 打开 http://localhost:3000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
