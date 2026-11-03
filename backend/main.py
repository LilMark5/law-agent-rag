"""FastAPI 入口"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 支持 `cd backend && python main.py` 与 `uvicorn backend.main:app` 两种启动方式
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import chat, graph, health, history, system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)


def warm_up() -> None:
    """启动时预热向量索引

    FAISS 索引 + Embedding 客户端首次构造约 5 秒。不预热的话，这个代价会落在
    第一个提问的用户身上（实测首问检索 6.7s、之后 0.3s）。预热失败不影响启动：
    没索引就没向量路，检索会自动降级为 BM25 + 图谱。
    """
    try:
        from src.config import load_config
        from src.retrieval.fusion import _resolve_index_path
        from src.retrieval.vector_search import get_engine

        cfg = load_config().get("retrieval", {})
        index_dir = _resolve_index_path(cfg.get("index_path", "data/embeddings"))
        if not (Path(index_dir) / "index.faiss").exists():
            logger.warning("向量索引不存在（%s），检索将走 BM25 + 图谱", index_dir)
            return
        get_engine(index_dir)
        logger.info("向量索引预热完成：%s", index_dir)
    except Exception as exc:
        logger.warning("向量索引预热失败，检索将自动降级：%s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    warm_up()
    yield


app = FastAPI(title="LilMark API", version="0.2.0", lifespan=lifespan)

# 端口集中在这里配置，避免与本机其它项目（常见占用 8000 / 8100）打架。
# 优先级：环境变量 > 默认值；前端 dev 端口同理（见 frontend/package.json），
# 但浏览器实际走 Next 的同源 rewrite，CORS 只是给「前端直连后端」的场景兜底。
# 先显式加载 .env：端口写在 .env 里也要生效（load_env_file 不会自动触发）
from src.config import load_env_file

load_env_file()

API_PORT = int(os.environ.get("API_PORT", "8200"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "3200"))

_cors_origins = [
    f"http://localhost:{FRONTEND_PORT}",
    f"http://127.0.0.1:{FRONTEND_PORT}",
]
# 兼容改端口前开着的旧页面（3000），刷新后即走新端口
for _legacy in (3000,):
    if _legacy != FRONTEND_PORT:
        _cors_origins += [f"http://localhost:{_legacy}", f"http://127.0.0.1:{_legacy}"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
# 兼容早期脚本/监控里写死的 GET /health；不进 OpenAPI，免得文档里出现两个同名端点
app.include_router(health.router, include_in_schema=False)
app.include_router(chat.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(system.router, prefix="/api")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=API_PORT, reload=True)
