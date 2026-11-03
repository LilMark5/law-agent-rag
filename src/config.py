import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_ENV_FILE_LOADED = False


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _mask(value: str) -> str:
    """日志里只展示 Key 的头尾，避免把凭据写进日志文件"""
    if not value:
        return "<空>"
    if len(value) <= 12:
        return value[:3] + "***"
    return f"{value[:7]}...{value[-4:]}(len={len(value)})"


def load_env_file(env_path: Path | None = None) -> None:
    """把项目根目录的 .env 读入 os.environ，.env 优先于系统环境变量

    只支持 ``KEY=VALUE`` 与 ``#`` 注释两种语法，够用且不必为此引入 python-dotenv。
    进程内只执行一次。

    优先级刻意设为 **.env > 系统环境变量 > settings.yaml**：
    这个项目的约定是"改配置就改 .env"。若沿用 setdefault，系统里一个残留的
    旧变量就会静默覆盖 .env，表现为"我明明填了新 Key 却一直 401"，极难定位。
    因此这里以 .env 为准，并在两者不一致时打一行警告说明。
    """
    global _ENV_FILE_LOADED
    if _ENV_FILE_LOADED:
        return
    _ENV_FILE_LOADED = True

    path = env_path or (get_project_root() / ".env")
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        # 空值不覆盖已有系统变量：让"注释掉 Key"退回到系统变量，而不是变成空串
        if not value:
            os.environ.setdefault(key, value)
            continue

        previous = os.environ.get(key)
        if previous and previous != value:
            logger.warning(
                "环境变量 %s 与 .env 不一致（系统=%s / .env=%s），以 .env 为准",
                key,
                _mask(previous),
                _mask(value),
            )

        os.environ[key] = value


def load_config() -> dict:
    load_env_file()

    config_path = get_project_root() / "config" / "settings.yaml"

    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

        deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
        if deepseek_api_key:
            config["llm"]["api_key"] = deepseek_api_key

        dashscope_api_key = os.environ.get("DASHSCOPE_API_KEY")
        if dashscope_api_key:
            config["embedding"]["api_key"] = dashscope_api_key

        neo4j_password = os.environ.get("NEO4J_PASSWORD")
        if neo4j_password:
            config["neo4j"]["password"] = neo4j_password

        return config
