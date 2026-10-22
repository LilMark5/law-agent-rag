# CLAUDE.md

> **完整工作手册见 [AGENTS.md](AGENTS.md)** —— 架构地图、硬约束、环境坑、改动菜谱、验收标准都在那里。
> 本文件只保留最短必要的约定，避免两份文档各说一套。最后更新：2026-10-22

## Project Overview

**Law Agent RAG**：中文法律咨询助手，多智能体编排（LangGraph）+ GraphRAG 三路检索。
用途是**简历项目与 AI Agent 岗面试**（不是论文/答辩）。取舍优先级：Agent 工程能力可见性 > 纯 UI 页面。

主界面是 **Next.js 15 前端**（`frontend/`），后端 **FastAPI**（`backend/`），核心逻辑在 `src/`。
`src/app/main.py` 的 Streamlit 界面是早期版本，仅作历史保留，不再是主入口。

## Tech Stack

Python 3.11+ · FastAPI + SSE · LangGraph · Neo4j 5 · FAISS · Next.js 15 + React 19 + TypeScript
LLM `deepseek-chat` · Embedding `text-embedding-v3`（1024 维）
配置唯一源：`config/settings.yaml`，密钥只走 `.env`（已被 git 忽略）

## Commands（本机没有 uv，一律用 .venv）

```bash
.venv/Scripts/python.exe -m pytest -q                                  # 103 passed
cd frontend && NODE_OPTIONS= npx tsc --noEmit                          # 0 error
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000 --reload
cd frontend && NODE_OPTIONS= npx next dev -p 3000                      # 清 NODE_OPTIONS 否则崩溃
.venv/Scripts/python.exe scripts/doctor.py --check-api
.venv/Scripts/python.exe scripts/eval_retrieval.py --mode hybrid --top-k 5
```

本地 curl 一律加 `--noproxy '*'`（系统代理不常在线，会让本地请求变 502）。

## Architecture

```
frontend → backend/routers → src/agents + src/retrieval → Neo4j / FAISS
```

| 层 | 位置 | 说明 |
|---|---|---|
| 编排 | `src/agents/graph.py` | StateGraph：identify → retrieve → 5 领域节点 → review（条件回边） |
| 领域 | `src/agents/domain_agent.py` | 上下文拼装、`build_sources` / `build_sources_detail` |
| 检索 | `src/retrieval/fusion.py` | `hybrid_search()` 唯一入口，加权 RRF，案例额外附加 |
| 接口 | `backend/routers/` | chat（SSE）、graph（真实子图）、system（运维统计）、health |
| 前端 | `frontend/` | AppShell 统一外壳；`lib/routes.ts` 是唯一导航源 |

## Non-negotiables

1. 案例**不进** BM25/向量语料，只由图谱按条号/罪名召回。
2. 检索 top_k 只算法条名额，类案由 `reserve_case_slots()` 额外附加。
3. 图谱收集顺序：直接命中 → 二跳 → 案例。
4. 条号查询必须带法名收窄（24 部法规条号重名）。
5. 前端**不得出现硬编码假数据**；所有数字来自 `/api/*`。
6. SSE 事件必须返回 `{"event":..., "data": "<json>"}` 的 dict。

详见 [AGENTS.md](AGENTS.md) 第 3 节，每条都附了「为什么」和实测现象。
