# Vibe Coding 提示词包

> 用法：新开一个 AI 编程会话（Codex / Cursor / Claude Code / 其他），**先把 A 段整段贴进去**，
> 再贴 B 段里对应的一条任务模板。不用每次重新解释项目。
> 需要更深的架构细节时看 [AGENTS.md](AGENTS.md)；这份文件只求「贴了就能干活」。

---

## A. 项目上下文（每次新会话先贴这段）

```text
你要在这个仓库里做开发。先读下面这些，再动手。

【项目】
Law Agent RAG：中文法律咨询助手。多智能体编排 + GraphRAG 三路检索。
用途是简历项目 + 面试 AI Agent 岗，所以优先做「能体现 Agent 工程能力」的东西，
纯 UI 装饰优先级最低。

【技术栈】
Python 3.11 + FastAPI（SSE 流式）/ LangGraph 编排 / Neo4j 知识图谱 / FAISS 向量
前端 Next.js 15 + React 19 + TypeScript，手写 CSS（纸本案卷风）
LLM: deepseek-chat；Embedding: text-embedding-v3（1024 维）

【目录速记】
src/agents/graph.py        多智能体编排（identify → retrieve → 5 领域 → review 条件回边）
src/agents/domain_agent.py 上下文拼装 + 结构化溯源 build_sources_detail()
src/retrieval/fusion.py    hybrid_search() 唯一检索入口，加权 RRF
src/retrieval/graph_search.py  条号/罪名 → Cypher → 二跳 → 案例
backend/routers/           chat(SSE) / graph(真实子图) / system(运维统计) / health
frontend/components/chat/  ChatContainer / AgentTimeline / AssistantMessage
frontend/lib/routes.ts     唯一导航源 primaryNavItems，新页面必须在这里挂入口
config/settings.yaml       唯一配置源（改检索参数的唯一入口）

【6 条硬规则（违反就会掉指标或引入假功能）】
1. 案例不进 BM25/向量语料，只由图谱按条号/罪名召回。
2. 检索 top_k 只算法条名额，类案由 reserve_case_slots() 额外附加。
3. 图谱收集顺序固定：直接命中 → 二跳 → 案例。
4. 条号查询必须带法名收窄（24 部法规条号重名：「第二百六十四条」可能是刑法也可能是民法典）。
5. 前端禁止写死数据。所有数字必须来自 /api/*；这个项目清过 4 处「伪 AI」，不要重新引入。
6. SSE 事件必须构造成 {"event":..., "data": "<json字符串>"} 的 dict，不要返回拼好的字符串。

【本机环境坑】
- 没装 uv，一律用 .venv/Scripts/python.exe
- 系统代理不常在线：本地 curl 必须加 --noproxy '*'
- 启动前端必须清 NODE_OPTIONS：cd frontend && NODE_OPTIONS= npx next dev -p 3000
- headless Chrome 截图要加 --no-proxy-server
- 端口：后端 8000，前端 3000（next.config 把 /api/* 代理到 8000）

【常用命令】
.venv/Scripts/python.exe -m pytest -q
cd frontend && NODE_OPTIONS= npx tsc --noEmit
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000 --reload
.venv/Scripts/python.exe scripts/eval_retrieval.py --mode hybrid --top-k 5

【交付标准】
改完必须实际执行并贴出输出：pytest 全绿、tsc 0 错误、curl 真实请求能看到预期字段。
不要只说「应该可以」。不要顺手重构无关代码。提交信息用 Conventional Commits，正文中文。
```

---

## B. 任务模板（挑一条，替换 `<>`）

### B1 · 加一个小功能

```text
按上面的项目约定，实现：<功能一句话>。

要求：
- 数据必须来自真实接口或真实计算，不许 mock/硬编码。
- 新增前端页面 → 同时在 frontend/lib/routes.ts 的 primaryNavItems 加入口，用 <AppShell> 包裹。
- 新增 SSE 字段 → 后端 streamer.py 加参数（非空才写）+ chat.py 传入 + lib/api.ts 类型 + ChatContainer 收集。
- 先告诉我改哪几个文件、为什么，再动手。

验收：pytest / tsc / curl 三条输出贴给我。
```

### B2 · 「点了没反应」类排查

```text
排查：<页面或按钮> 点击后没有预期效果。

要求：
1. 先判定属于哪一种，并给出证据（文件:行号）：
   前端没接请求 / 后端没提供接口 / 数据是写死的常量 / 组件没渲染。
2. 用 curl --noproxy '*' 直接打后端，确认接口真实返回。
3. 给最小修复方案，不要重构无关代码。
4. 修完用 headless Chrome（--no-proxy-server）截图，确认 DOM 数量与接口一致。
```

### B3 · 调检索效果（高风险，先跑基线）

```text
按项目约定调整检索：<目标>。

顺序不能变：
1. 先跑基线并记录 Recall@5 / MRR / 耗时：eval_retrieval.py --mode hybrid --top-k 5
2. 再改 fusion.py / graph_search.py / settings.yaml
   —— 保留 reserve_case_slots 语义，案例不进文本检索语料。
3. 再跑评测对比，退步就回滚。
4. 把结论写进 config/settings.yaml 的注释（要写「为什么」和实测数字，别写空话）。
```

### B4 · 文档同步

```text
把 <这次改动> 同步到 README.md / AGENTS.md。

要求：只写真实数据（跑命令取数），不要写「计划中」的功能当已实现，不要编数字。
```

---

## C. 每轮收尾验收提示词

```text
这轮改动收尾，请执行并贴出结果：
1. .venv/Scripts/python.exe -m pytest -q
2. cd frontend && NODE_OPTIONS= npx tsc --noEmit
3. 若有接口改动：curl -s --noproxy '*' 打一次真实请求，贴关键字段
4. 一句话说明「这次改动让哪条数据流接上了」
```

---

## D. 这个项目的 vibe coding 记录（简版）

| # | 原始需求 | 做了什么 | 怎么验证的 |
|---|---|---|---|
| 1 | 项目能不能跑通 | 体检 + 修 `terms` 未定义、补 `/api/health`、改 README | doctor 9 项、pytest 66 |
| 2 | 接真实案例数据 | `cail_loader.py` + `import_cail.py`，导入 17,131 案例 / 19,645 关系 | 条号命中率 183/183 |
| 3 | 案例要进回答 | 案例额外占位 + 图谱二跳先于案例 + prompt 分区块 | Recall@5 保持 0.879 |
| 4 | 很多按钮没反应 | 逐页排查：约 30 个死按钮，数据全是硬编码 | 盘点清单 |
| 5 | 要看出多智能体在干活 | 编排时间线（4 步 + 三路检索 chip） | 真实 SSE 驱动 |
| 6 | 对话页像另一个网站 | 并入 AppShell，删独立 Header/StatusBar | 逐页截图对比 |
| 7 | 多轮对话是假的 | `buildHistory()` + 真实 history 传参 | 追问「那…」正确路由劳动法 |
| 8 | 引用要能点开核对 | `sources_detail` 结构化来源卡片（案号/罪名/判决/通道） | 10 张卡片与后端一致 |
| 9 | 时间线没有工程感 | `elapsed_ms` 相邻相减 → 每步耗时 | 5.2s / 487ms / 9.2s / 15ms |
| 10 | 图谱页是假的 | `GET /api/graph/{stats,subgraph}` + 力导向渲染 | 60 节点 / 59 边 |
| 11 | 运维页 4 个假指标 | `GET /api/system/stats` + 页面重写 | 3942 / 17131 / 19645 真实 |
| 12 | 简历与开源 | 单页简历、建仓推送、README 重写 | 远端 139 文件，`.env` 未上传 |

### 三条经验（比上面那张表更值钱）

1. **「代码写了」不等于「功能在跑」**：多轮逻辑写全了，前端传空 history 就是零；图谱画得再漂亮，节点是硬编码就是零。判断标准只有一条——**数据是不是从真实源头流到了像素**。
2. **指标必须能复现**：先跑基线再改，改完再跑；退步就回滚。别靠感觉说「应该会更好」。
3. **先接数据流，再加页面**：所有有价值的改动都是把断掉的链路接通（SSE 字段 → 前端状态 → 组件渲染），而不是多画一个页面。

---

## E. 换软件新开会话的交接语

```text
接手一个已有项目，先读仓库根目录的 AGENTS.md（深度版）和 README.md。
当前状态：前后端都在跑（8000 / 3000），pytest 103 passed，检索 Recall@5 0.879。
最近做完的：多轮对话、结构化引用溯源、逐节点耗时、真实 Neo4j 子图、运维真实统计。
下一步候选：类案检索评测 / 对话历史持久化 / 应用容器化。
先从 <具体任务> 开始，改动前先告诉我你会动哪些文件。
```
