# AGENTS.md — Law_Agent_RAG 工作手册

> **想直接干活？看 [VIBE-CODING.md](VIBE-CODING.md)**——那里是可以整段粘贴给 AI 的提示词包。
> 本文件是深入版：架构细节、每条硬约束的「为什么」与实测现象，出问题时来查。
> 最后更新：2026-10-22

---

## 1. 项目定位

**法律咨询助手**：基于多智能体编排 + GraphRAG 的中文法律问答系统。

- **用途**：简历项目 + 面试 AI Agent 开发岗（不是论文、不是答辩）。取舍标准：优先做能体现 Agent 工程能力的东西（编排、检索、可解释性、评测），纯 UI mock 页面优先级最低。
- **一句话卖点**：LangGraph 编排「意图识别 → 五领域专家 → 审查反思回边」，BM25 + FAISS + Neo4j 三路召回经加权 RRF 融合，回答带**可点开的结构化引用**（法条章节 / 案号 / 罪名 / 判决 / 检索通道）。
- **仓库**：https://github.com/LilMark5/law-agent-rag （public，main 分支）

### 当前规模（都是真实数据，不是 mock）

| 项 | 数值 | 来源 |
|---|---|---|
| 法条 | 3,942 条 / 24 部法规 | Neo4j `Law` 节点 |
| 刑事案例 | 17,131 条（CAIL2018 valid） | Neo4j `Case` 节点 |
| 案例-法条关系 | 19,645 条 `APPLIES` | Neo4j 边 |
| 向量索引 | FAISS，1024 维，15.4 MB | `data/embeddings/` |
| 测试 | 103 passed / 12 个测试文件 | `pytest` |
| 检索质量 | Recall@5 **0.879** / MRR **0.741** / 449ms | 33 条 gold |

---

## 2. 架构地图

### 分层

```
frontend (Next.js 15)  ←HTTP/SSE→  backend (FastAPI)  →  src/ (核心逻辑)  →  Neo4j / FAISS
   展示层                              接口层                领域层            存储层
```

业务逻辑**全部**在 `src/`，backend 只做「参数校验 + 调函数 + 拼 SSE 事件」，frontend 只做渲染。
**不要在 backend 或 frontend 里写检索/提示词逻辑。**

### 关键文件

| 路径 | 职责 | 改动风险 |
|---|---|---|
| `src/agents/graph.py` | LangGraph StateGraph 定义、节点、条件回边（recursion_limit=25） | 高 |
| `src/agents/coordinator.py` | 意图识别（领域 + 意图 + 关键词）、`ask_agent()` 入口 | 中 |
| `src/agents/domain_agent.py` | 领域 Agent：`build_context_blocks()` 拼上下文、`build_sources()` 行文本、`build_sources_detail()` 结构化溯源 | 高 |
| `src/agents/reviewer.py` | 规则审查（正则，零成本）/ LLM 审查，区分「编造 vs 未召回」 | 中 |
| `src/retrieval/fusion.py` | `hybrid_search()` 唯一检索入口、加权 RRF、`reserve_case_slots()` | **最高** |
| `src/retrieval/graph_search.py` | 实体抽取（条号正则 + 罪名词典）→ Cypher → 二跳 → 案例 | 高 |
| `src/retrieval/vector_search.py` | FAISS 建库 / 查询 | 中 |
| `src/retrieval/bm25.py` | 字符级 BM25 | 低 |
| `backend/routers/chat.py` | `POST /api/chat`，astream 逐事件转发 | 中 |
| `backend/services/streamer.py` | SSE 事件构造函数（**必须返回 dict**，见第 6 节） | 中 |
| `backend/routers/graph.py` | `/api/graph/stats`、`/api/graph/subgraph` | 低 |
| `backend/routers/system.py` | `/api/system/stats` 运维统计（绝不回传 Key） | 低 |
| `frontend/components/chat/ChatContainer.tsx` | 对话状态机：消息、trace、sources_detail、history 构造 | 高 |
| `frontend/components/chat/AgentTimeline.tsx` | 4 步编排时间线 + 三路检索 chip + 每步耗时 | 中 |
| `frontend/components/chat/AssistantMessage.tsx` | 可展开引用卡片（法条红徽 / 类案绿徽） | 中 |
| `frontend/components/graph/GraphExplorer.tsx` | 真实子图 + 手写力导向布局（60 轮 FR 迭代） | 中 |
| `frontend/lib/api.ts` | 所有类型定义 + fetch 封装 + SSE 解析 | 中 |
| `frontend/lib/routes.ts` | **唯一**导航源（`primaryNavItems`） | 中 |
| `config/settings.yaml` | 唯一配置源（检索参数、权重、审查、prompt 截断） | **最高** |

### 一次提问的完整时序

```
前端 handleSend(question)
  → buildHistory() 取最近成对 {question, answer}
  → POST /api/chat {question, history}
    → chat.py: astream_agent(question, history)
      → identify 节点：LLM 判领域 + 意图（带 history 做指代消解）
      → retrieve 节点：hybrid_search()  ← 三路并发，RRF 融合
      → <domain> 节点：build_context_blocks() → LLM 生成 → build_sources(_detail)
      → review 节点：规则审查
          passed=false 且 attempt < max_retry → 回边到 generate（反思重生成）
    → SSE: step(intent) → step(retrieve) → step(generate) → step(review) → done
  → 前端逐事件更新 trace / 流式答案 → done 时落库消息
```

SSE 事件字段（`elapsed_ms` 是**从请求开始的累计值**，前端相邻相减得每步耗时）：

| 事件 | 关键字段 |
|---|---|
| `step / intent` | `domain`、`domain_zh`、`intent` |
| `step / retrieve` | `sources_count`、`retrieved_by`（如 `["bm25","vector","graph"]`） |
| `step / generate` | `answer`（增量或全量）、`attempt` |
| `step / review` | `passed`、`score`、`mode`（rule/llm） |
| `done` | `sources[]`、`sources_detail[]`、`review{passed,score,mode}` |
| `error` | `message` |

---

## 3. 硬约束（改了就坏，每条都踩过）

1. **案例不进 BM25 / 向量语料**（`include_cases_in_text_search: false`）。
   1.7 万条案例事实里全是「盗窃」「数额较大」，进词汇检索会成批挤掉法条召回。改这个值等于要重建索引。
2. **检索 top_k 只算法条名额**，类案由 `reserve_case_slots()` **额外附加**，不占名额。
   任何「给案例留位」的改动都会直接拉低法条 Recall@K（实测 0.848 → 0.818）。
3. **图谱收集顺序固定**：直接命中 → 二跳 → 案例。
   案例必须最后收，否则热门法条的上千条案例会占满额度，二跳永远走不到。
4. **图检索不收 `CONTAINS 术语` 召回的任意法条**（等于把 BM25 重做一遍还更差：MRR 0.741→0.644）。
   只按**条号精确匹配**；`graph_use_llm_entities: false`——检索链路上每条查询多等 3~8 秒。
5. **条号必须带法名收窄**。24 部法规条号天然重名：「第二百六十四条」既可能是刑法盗窃罪、也可能是民法典合同编。`Law` 节点有 `law_article_idx` 索引，查询必须同时约束 `law_name`。
6. **融合要先深召回再截断**：每路取 20 条再融合，最后只留 `final_top_k=8`。
   每路只取 5 条时两路结果几乎重合，融合等于白做。
7. **权重不能等权**：`vector 1.0 / bm25 0.2 / graph 0.5`。等权会让弱通道的噪声提名把正确答案挤下去（等权 0.818 < 向量单路 0.848）。
8. **SSE 事件必须构造为 `{"event":..., "data": "<json 字符串>"}` 的 dict**（`streamer.py`）。
   直接返回拼好的 `"event: xxx\ndata: ..."` 字符串会被 sse-starlette 再包一层，前端收到 `data: event: step` 无效载荷。
9. **前端不得出现硬编码的假数据**。这个项目曾经有 4 处「伪 AI」已全部清除，**不要重新引入**：
   - 假编排时间线（5 个不存在的 agent、编造耗时）
   - 假运维指标（写死「图谱覆盖 18.4k」）
   - 假图谱节点（`lib/data.ts` 里 8 个硬编码节点）
   - 多轮对话传空 history（`sendChat(question, [])`）
   任何展示数字的地方都必须来自 `/api/*`。
10. **`.env` 绝不入库**。`.gitignore` 已排除 `.env`、`data/{raw,processed,embeddings}`、`output/`、`.workbuddy/`。
    提交前自查：`git diff --cached --name-only | grep -i env`。
11. **`config/settings.yaml` 里的 key 字段必须留空**，真实密钥只走 `.env`。给运维接口加字段时也不要回传 Key。

---

## 4. 本机环境坑（每次开发都会碰到）

| 现象 | 原因 | 处理 |
|---|---|---|
| `uv: command not found` | 这台机器没装 uv（但仓库有 `uv.lock`） | 一律用 `.venv/Scripts/python.exe` |
| `curl http://127.0.0.1:8200` 返回 **502** | 系统代理 `http_proxy=127.0.0.1:1129` 不常在线，把本地请求转发了 | 本地请求一律加 `--noproxy '*'` |
| `next dev` 崩溃 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` | `NODE_OPTIONS` 注入的 shim 拦截了 `unlink`，清理 `.next` 时命中批量保护 | 启动前清空：`NODE_OPTIONS= npm run dev` |
| Chrome headless 截图空白 / 超时 | 同上代理问题 | 加 `--no-proxy-server` |
| `print-to-pdf` 报「另一个程序正在使用此文件」 | 目标 PDF 正被阅读器占用 | 改输出新文件名，不要去等它关闭 |
| 中文路径下脚本报编码错 | Windows + 中文文件名 | 路径用绝对路径并加引号；写脚本时 `encoding="utf-8"` |

**端口**：后端 **8200**、前端 **3200**。

换过端口的原因：本机另一个项目 `lab_agent_std` 的后端固定用 **8000**、MCP 用 **8100**，两边一起开发时先起的那个会顶掉另一个（表现为 `WinError 10048`，而 `netstat | grep LISTENING` 可能看不到占用者）。现在两端口都可配置：

| 项 | 配置位置 | 默认值 |
|---|---|---|
| 后端端口 | 环境变量 `API_PORT`（`.env` 或系统变量） | 8200 |
| 前端 dev 端口 | `frontend/package.json` 的 `dev` 脚本（另有 `dev:3000` 逃生口） | 3200 |
| Next → 后端代理目标 | 环境变量 `BACKEND_ORIGIN`（需放 `frontend/.env.local` 或系统变量，Next 读不到仓库根 `.env`） | `http://127.0.0.1:8200` |
| CORS 白名单 | `backend/main.py` 按 `FRONTEND_PORT` 生成，另保留 3000 兼容 | 3200 + 3000 |

要彻底换一套端口，改 `API_PORT` + `frontend/package.json` + `BACKEND_ORIGIN` 三处即可，代码里没有别的硬编码。

---

## 5. 命令手册

```bash
# 后端（开发）
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8200 --reload

# 前端（开发）——必须清 NODE_OPTIONS；端口已写进 dev 脚本（3200）
cd frontend && NODE_OPTIONS= npm run dev

# 类型检查 / 测试
cd frontend && NODE_OPTIONS= npx tsc --noEmit
.venv/Scripts/python.exe -m pytest -q

# 环境自检（Key / 语料 / 图谱 / 索引）
.venv/Scripts/python.exe scripts/doctor.py --check-api

# 数据导入
.venv/Scripts/python.exe scripts/import_sample_data.py        # 法条 → Neo4j
.venv/Scripts/python.exe scripts/import_cail.py --dry-run      # 预览
.venv/Scripts/python.exe scripts/import_cail.py --clear        # 重导（清旧 Case）
.venv/Scripts/python.exe scripts/build_index.py                # 重建 FAISS

# 检索评测
.venv/Scripts/python.exe scripts/eval_retrieval.py --mode hybrid --top-k 5
.venv/Scripts/python.exe scripts/eval_retrieval.py --mode hybrid --no-graph   # 消融
.venv/Scripts/python.exe scripts/sweep_fusion.py --depth 20    # 权重扫描

# 端口占用 / 停服务
#   注意：占用者可能是 Bound 而非 Listen 状态，grep LISTENING 会漏掉它
powershell -Command "Get-NetTCPConnection -LocalPort 8200,3200 | Select-Object LocalPort,State,OwningProcess"
taskkill //PID <pid> //F
```

---

## 6. 常见改动菜谱

### 加一个 SSE 字段（例：`retrieval_ms`）
1. `backend/services/streamer.py`：在对应事件构造函数里加 kwarg（保持「非空才写」的向后兼容风格）。
2. `backend/routers/chat.py`：从 `latest` 取值传入。
3. `frontend/lib/api.ts`：在事件类型里加可选字段。
4. `frontend/components/chat/ChatContainer.tsx`：在 `event.type === "step"` 分支里收集。
5. 渲染组件消费（时间线 / 卡片）。
6. 验收：`curl -N` 抓一次真实事件，确认字段出现。

### 加一个法律领域
1. `src/agents/config/new_domain.yaml`（照抄 `civil_law.yaml` 的结构：system prompt + 领域约束）。
2. `src/agents/coordinator.py` 的 `DOMAINS` / `DOMAIN_MAP`。
3. `config/settings.yaml` 的 `agents.domains`。
4. `src/agents/graph.py` 里注册新节点的**路由映射**（注意条件边）。
5. 验收：问一个该领域的问题，看 `step/intent` 的 `domain` 是否命中。

### 加一个前端页面
1. `frontend/app/<route>/page.tsx`。
2. **必须**在 `frontend/lib/routes.ts` 的 `primaryNavItems` 加上入口，否则是只能手敲 URL 的孤儿页。
3. 用 `<AppShell>` 包（对话页用 `<AppShell fill>`），**不要**自己造顶栏——历史上就是因为独立顶栏导致切页视觉断裂。
4. 数据必须走 `lib/api.ts`，不要在组件里硬编码。

### 改检索融合（高风险）
1. 先跑基线：`eval_retrieval.py --mode hybrid` 记下 Recall@5 / MRR / 耗时。
2. 改 `fusion.py`，**保持 `reserve_case_slots` 的语义**（案例额外附加）。
3. 再跑评测对比；退步就回滚，别靠感觉。
4. 结论写进 `config/settings.yaml` 的注释（现有注释里那几条「反直觉结论」就是这么来的）。

---

## 7. 前端约定

- **统一外壳**：全站 `AppShell`（左侧栏 + 顶栏 + 内容区）。对话页 `<AppShell fill>`，内部 `.chat-panel` 自己管滚动。
- **导航唯一源**：`lib/routes.ts` 的 `primaryNavItems`（10 项：对话/工作台/咨询/分析/图谱/证据/历史/运维/设置/关于）。
- **视觉风格**：纸本案卷风。宣纸底色 + 墨色文字 + 朱砂强调色，细边框、小圆角、克制留白。
  颜色一律用 CSS 变量（`--color-ink` / `--color-cinnabar` / `--color-rule` / `--color-jade` 等），不要写裸十六进制。
- **文案**：简体中文，专业书面语气，不用感叹号，不用 emoji（除非明确要求）。
- **金额/涨跌**：本项目不涉及行情。

---

## 8. 质量门（改完必须过，缺一不可）

```bash
.venv/Scripts/python.exe -m pytest -q          # 必须 103+ passed，0 failed
cd frontend && NODE_OPTIONS= npx tsc --noEmit  # 必须 0 error
curl -s --noproxy '*' http://localhost:8200/api/health   # {"status":"ok"}
```

涉及前端可见改动的，再加一次真实端到端：用 headless Chrome 截图（`--no-proxy-server`），
确认 DOM 里的数量与后端返回一致。**不要只看编译通过就交差。**

提交信息用 Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:`），正文中文。

---

## 9. Vibe coding 实录（2026-10-22 这一天做了什么）

### 9.1 里程碑

| # | 需求 | 关键改动 | 验证方式 |
|---|---|---|---|
| 1 | 项目能不能跑通 | 体检 doctor / pytest / SSE | 9 项 doctor 通过、64 passed、5 事件完整 |
| 2 | 修 3 个硬伤 | `graph_search.py` 未定义变量 `terms`、`/api/health` 路由缺失、README 环境变量优先级写反 | 新增回归测试，66 passed |
| 3 | 接 CAIL 数据集 | `cail_loader.py`（多法条、刑期三态、int↔中文条号归一化）+ `import_cail.py`；`kg_builder.parse_applicable_law` 改 `finditer` 支持多法条 | 条号 183/183 命中率 100%；导入 17,131 Case / 19,645 APPLIES |
| 4 | 案例要能进回答 | `reserve_case_slots()` 案例额外附加 + 图谱二跳先于案例 + prompt 分「法条/类案」区块（事实截断 400 字，最多 2 条） | Recall@5 保持 0.879 未回退 |
| 5 | 前端很多按钮点了没反应 | 逐页排查：约 30 个死按钮，数据全来自 `lib/data.ts` 硬编码 | 盘点清单 |
| 6 | 要能看出多智能体在干活 | `AgentTimeline.tsx` 4 步时间线 + 三路检索 chip；ChatContainer 聚合 trace | 真实 SSE 驱动渲染 |
| 7 | 导航断裂、对话页像另一个网站 | 对话页并入 `AppShell`（新增 `fill` prop），删除 `Header.tsx` / `StatusBar.tsx` | CDP 逐页验证布局一致 |
| 8 | 盘点哪些前端是空壳 | 产出 `docs/onboarding/前端空壳盘点与改进方案.md`：14 项后端能力仅 5 项前端可见 | — |
| 9 | 修多轮对话（P0-1） | `buildHistory()` 成对构造 + `messagesRef` 快照 + `sendChat(question, history)` | 追问「那试用期最长…」正确路由到劳动法 |
| 10 | 引用要能点开核对（P1-8） | `build_sources_detail()` + `done.sources_detail` + `AssistantMessage` 卡片（法条/类案双徽章 + 检索通道 chip） | 10 张卡片与后端一致，案号/判决真实 |
| 11 | 时间线要有工程感（P1-9） | SSE `elapsed_ms` 相邻相减 → 每步耗时；`fmtMs` 三态配色 | 5.2s / 487ms / 9.2s / 15ms |
| 12 | 图谱页是假的（P2-13） | 新增 `/api/graph/{stats,subgraph}` + `GraphExplorer` 重写（力导向布局） | 60 节点 / 59 边，点节点显示真实罪名判决 |
| 13 | 运维页 4 个假指标 | 新增 `/api/system/stats` + admin 页重写（法规分布条形图 + 配置行） | 3942/17131/19645/15.4MB 全真实 |
| 14 | 简历 + 开源 | 单页简历（两个项目差异化）、GitHub 建仓推送、README 重写 | 远端 139 文件，`.env` 404 |

### 9.2 这一天学到的三个元规律

1. **「能跑」不等于「真的在跑」**。多轮对话代码写得再完整，前端传空 `history` 就是零；图谱页画得再好看，节点是硬编码就是零。判断标准是**数据是否从真实源头流到像素**。
2. **指标必须能复现**。融合权重、召回深度这类改动，先跑基线再改，改完再跑；配置注释里那两条「反直觉结论」都是评测出来的，不是拍脑袋。
3. **先修数据流，再修 UI**。这一天所有有价值的改动，都是把某条断掉的数据流接通（SSE 字段 → 前端状态 → 组件渲染），而不是加新页面。

---

## 10. 给 Codex 的提示词模板

> 用法：把下面模板整段贴给 Codex，替换 `<>` 里的内容。前提是它已经能读到本文件。

### 模板 A：加一个小功能

```
读 AGENTS.md 第 3、4、6 节，然后实现：<功能一句话>。

约束：
- 不要引入任何 mock / 硬编码数据，数据必须来自真实接口或真实计算。
- 如果新增前端页面，必须同时在 frontend/lib/routes.ts 的 primaryNavItems 加入口，
  并用 <AppShell> 包裹（对话类页面用 <AppShell fill>）。
- 如果新增 SSE 字段，按 AGENTS.md 第 6 节「加一个 SSE 字段」的五步走，保持向后兼容。

验收（必须实际执行，把输出贴给我）：
1. .venv/Scripts/python.exe -m pytest -q
2. cd frontend && NODE_OPTIONS= npx tsc --noEmit
3. curl -s --noproxy '*' 真实请求，贴出关键字段
```

### 模板 B：排查「点了没反应」

```
读 AGENTS.md，然后排查：<页面/按钮> 点击后没有预期效果。

要求：
1. 先判断是「前端没接」还是「后端没提供」还是「数据是硬编码」——分别列证据（文件:行号）。
2. 前端请求一律用 curl 加 --noproxy '*' 验证。
3. 给出最小修复方案，不要顺手重构无关代码。
4. 修复后用 headless Chrome 截图（--no-proxy-server）确认 DOM 与接口数据一致。
```

### 模板 C：调检索效果（高风险改动）

```
读 AGENTS.md 第 3 节和第 6 节「改检索融合」，然后：<改动目标>。

流程（顺序不能变）：
1. 先跑基线并记录：eval_retrieval.py --mode hybrid --top-k 5（Recall@5 / MRR / 耗时）。
2. 改动，注意保留 reserve_case_slots 语义、案例不进文本检索语料。
3. 再跑评测对比，退步就回滚。
4. 把结论写进 config/settings.yaml 的注释（说清「为什么」和实测数字）。
```

### 模板 D：更新文档

```
读 AGENTS.md 和 README.md，把 <改动> 同步到文档。
只写真实数据（跑命令取数，不要凭印象），不要写未来时态的功能。
```

---

## 11. 已知未完成项

- [ ] CAIL 全量导入（270 万条，需先换 fulltext index，当前按条号精确匹配撑不住）
- [ ] 类案检索评测（目前评测集只覆盖法条，案例召回没量化）
- [ ] 对话历史持久化（现在只在内存，刷新即丢）
- [ ] 应用容器化（`docker-compose.yml` 目前只跑 Neo4j）
- [ ] 延迟指标接入运维面板（要做真实采样，不能写死）
- [ ] 用户认证与多租户

---

## 12. 文档索引

| 文档 | 内容 |
|---|---|
| `README.md` | 对外门面：特性、架构、快速开始、API、评测 |
| `docs/deployment/本地部署指南.md` | 详细部署、环境变量优先级、排错 |
| `docs/onboarding/CAIL案例接入方案.md` | 数据集获取与字段说明 |
| `docs/onboarding/前端空壳盘点与改进方案.md` | 前端哪块是真哪块是壳（P0/P1/P2 分档） |
| `docs/onboarding/数据源与扩充方案.md` | 法条语料来源与扩充路径 |
| `docs/superpowers/specs/` | 早期设计规格（历史存档，部分已过时） |
