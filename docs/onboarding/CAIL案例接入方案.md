# CAIL 案例接入方案

> 结论：**已接入。** 17,131 条真实刑事案例、19,645 条「案例-法条」边进了 Neo4j，
> 类案检索与二跳扩展都已跑通，法条检索指标无回退（Recall@5 0.879）。
>
> 关键前提是映射比预期干净：`relevant_articles` 转成中文条号后，
> 对本地刑法语料的覆盖率是 **183/183 = 100%**。
> 而项目里 `Case` 节点和 `APPLIES` 关系的代码早就写好了，只是一直没有数据。

---

## 一、CAIL 是什么

**CAIL2018（中国法研杯司法人工智能挑战赛）** 是 THUNLP 和最高法信息中心联合发布的
大规模法律判决预测数据集，也是国内法律 NLP 最常被引用的公开基准。

它解决的任务是：给一段案件事实（`fact`），预测**罪名**（`accusation`）、
**适用法条**（`relevant_articles`）、**刑期**（`term_of_imprisonment`）。
这三样正好就是我们要给 `Case` 节点填的字段。

对本项目的意义不是"再做一个判决预测"，而是：

| 项目现状 | 接入后 |
|---|---|
| Neo4j 里 `Law 3942 / Case 0` | 有 1.7 万真实案例节点 |
| `APPLIES` 关系不存在，图谱二跳是空转 | 「法条 ↔ 案例」双向可达，GraphRAG 名副其实 |
| 只能答"法条怎么规定" | 还能答"这类案子法院一般怎么判" |
| 引用只有条文 | 引用可以是"条文 + 真实判例" |

---

## 二、实测：包里到底有什么

全量包 `CAIL2018_ALL_DATA.zip` 共 **939 MB / 12 个成员**（2018-10-07 最后更新）：

| 成员 | 压缩后 | 解压后 | 说明 |
|---|---:|---:|---|
| `first_stage/train.json` | 535.1 MB | 1995.0 MB | 一阶段训练集，约 150 万条 |
| `restData/rest_data.json` | 228.1 MB | 856.4 MB | 补充数据 |
| `first_stage/test.json` | 73.4 MB | 270.9 MB | 一阶段测试集 |
| `exercise_contest/data_train.json` | 70.0 MB | 235.8 MB | 练习赛训练集 |
| `final_test.json` | 12.6 MB | 48.3 MB | 决赛测试集（无标注） |
| `exercise_contest/data_test.json` | 13.1 MB | 44.6 MB | 练习赛测试集 |
| **`exercise_contest/data_valid.json`** | **6.6 MB** | **23.6 MB** | **练习赛验证集，本次采用** |

> 下载提示：`https://` 直链在 Windows 上会因 schannel 证书吊销检查失败报
> `CRYPT_E_REVOCATION_OFFLINE`；换 **`http://`** 即可（实测 206 Partial Content，
> 205 KB/s 左右）。939 MB 全量按这个速度要一个多小时，**没必要下全量**——
> zip 的中央目录在文件末尾，用 Range 读出目录后单独拉需要的成员就行
> （`C:/Users/Lil Mark/.workbuddy/tmp/remote_zip.py` 是这个临时工具，没进仓库）。

实测环境已落盘：`data/raw/cail/data_valid.json`（24,702,198 字节，CRC 校验通过）。

---

## 三、真实数据长什么样

**格式是 JSONL**，一行一条，不是 JSON 数组：

```json
{
  "fact": "公诉机关起诉指控，被告人张某某秘密窃取他人财物，价值2210元，××数额较大，其行为已触犯《中华人民共和国刑法》××之规定，应当以××罪追究其刑事责任。建议判处被告人张某某××以下刑罚，并处罚金。",
  "meta": {
    "relevant_articles": [264],
    "accusation": ["盗窃"],
    "punish_of_money": 0,
    "criminals": ["张某某"],
    "term_of_imprisonment": {"death_penalty": false, "imprisonment": 2, "life_imprisonment": false}
  }
}
```

### 字段映射到项目的 `Case` 节点

| CAIL 字段 | 项目字段 | 转换方式 |
|---|---|---|
| `fact` | `fact` | 原文 |
| `accusation[]` | `crime` | `"、".join(...)`，如 `"盗窃"` |
| `relevant_articles[]` | `applicable_law` | `刑法第{int_to_cn(n)}条`，多个用 `、` 连接 |
| `term_of_imprisonment` | `judgment` | 见下方渲染规则 |
| （行号） | `case_id` | `CAIL-{序号:06d}` |
| — | `case_type` | 固定 `"刑事"` |

刑期渲染规则（实测分布，17,131 条）：

| 条件 | 渲染 | 占比 |
|---|---|---:|
| `death_penalty = true` | 死刑 | 极少 |
| `life_imprisonment = true` | 无期徒刑 | 约 3% |
| `imprisonment > 0` | `有期徒刑{N//12}年{N%12}个月` | 约 90% |
| 三者皆否 | **留空**，不要猜 | 1,098 条 / 6.4% |

最后一行是坑：`imprisonment = 0` 且非死非无期，可能是免予刑事处罚、管制或拘役，
CAIL 没区分。**不要硬编成"有期徒刑0月"**，留空比编错好。

`int_to_cn()` 项目里已经有了（`src/retrieval/graph_search.py`），直接复用，
它已经处理过 `第二百三十二条` 这类写法和「之一」条。

---

## 四、三个必须知道的实测结论

### 1. 条号 100% 对得上，不需要做映射表

CAIL 的 `relevant_articles` 是纯整数（264），本地语料存的是中文（第二百六十四条）。
用 `int_to_cn()` 转换后，**183 个不同条号全部命中本地刑法 505 条语料**：

```
CAIL 涉及条号 183 个，语料能对上 183 个 = 100.0%
对不上的条号: []
```

这说明 CAIL2018 的条号体系和 `flk.npc.gov.cn` 抓的现行刑法是一致的，
**不需要维护"旧条号 → 新条号"的对照表**，也不用担心刑法修正案导致错位。

### 2. `××` 掩码遮的是法条引用，不是案件事实

练习赛数据里 60.9% 的 fact 含 `××`，但看上下文就明白它在遮什么：

```
... 其行为已触犯《中华人民共和国刑法》××之规定，应当以××罪追究其刑事责任 ...
... 致一人轻伤二级，其行为触犯了《中华人民共和国刑法》×××× ...
```

遮的是**罪名和法条**，而这些本来就是 `meta` 里的标注答案。
时间、地点、行为方式、伤情、金额全都保留。对检索来说这是**好事**：
答案没有泄漏在输入文本里，做类案召回才测得准。

### 3. 两个 split 的字段类型不一致

| 文件 | `relevant_articles` 元素类型 |
|---|---|
| `exercise_contest/data_valid.json` | `int`（`[264]`） |
| `first_stage/test.json` | `str`（`["234"]`） |

导入器必须 `int(a)` 归一化，否则换个 split 就静默失败。

另外 `first_stage/test.json` 的事实叙述更完整（法条引用处才掩码），
代价是 73 MB 压缩。**建议先用 6.6 MB 的 valid 集跑通，再决定要不要换大的。**

### 数据集规模速览（valid 集）

| 指标 | 数值 |
|---|---|
| 案例数 | 17,131 |
| 罪名种类 | 202 |
| 涉及法条 | 183 条（Top：347 条 1,614 次、264 条 952 次、383 条 733 次） |
| 多罪名案例 | 1,324（7.7%） |
| **多法条案例** | **2,003（11.7%）**；另有 1,641 条重复列了同一条号，去重后不影响边数 |
| 事实长度 | 中位 323 字，最长 39,586 字 |

---

## 五、接入设计

```
CAIL2018_ALL_DATA.zip
   │  ① HTTP Range 只拉需要的成员（不下 939 MB）
   ▼
data/raw/cail/data_valid.json          ← JSONL，17,131 行
   │  ② 新增 src/data/cail_loader.py
   │     · 逐行解析，int/str 条号归一化
   │     · relevant_articles → 「刑法第二百六十四条」
   │     · term_of_imprisonment → judgment（三态渲染，0 留空）
   ▼
data/processed/cases.json              ← 与现有 load_cases() 同一个出口
   │  ③ 新增 scripts/import_cail.py
   ▼
Neo4j
   · (:Case {case_id, case_type, crime, fact, judgment, applicable_law})
   · (:Case)-[:APPLIES]->(:Law)        ← 多法条逐条建边，别只取第一条
   ▼
graph_search()
   · CASE_QUERY   罪名/事实 CONTAINS → 捞类案
   · EXPAND_QUERY 命中法条 → 经案例 → 相邻法条（二跳终于有东西可走）
```

### 代码改动清单

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/data/cail_loader.py` | **新增** | 解析 + 归一化 + 渲染刑期，纯函数，好测 |
| `scripts/import_cail.py` | **新增** | CLI：`--input`、`--limit`、`--dry-run`、`--clear` |
| `src/data/kg_builder.py` | 改 `import_relations` | 现在 `pattern.search` **只取第一个条号**，17.4% 的多法条案例会丢边；改成 `finditer` |
| `src/data/collector.py` | 改 `load_cases()` | 已经只读 `data/processed/cases.json`，**不用改**，天然兼容 |
| `src/retrieval/graph_search.py` | 不改 | `CASE_QUERY` / `EXPAND_QUERY` 已经能用了 |

### 为什么必须改 `import_relations`

现在的实现：

```python
match = pattern.search(raw)      # 只抓第一个「第X条」
if not match:
    continue
```

`applicable_law = "刑法第二百六十四条、第三百一十二条"` 时只会建一条边，
掩掉了 2,003 条多法条案例（合计 2,514 条边）里的关联。而**多法条关联正是图谱
二跳的价值来源**——只连一条边的话，二跳等于没跳。

---

## 六、方案已落地（2026-10-22）

三个取舍按下面的选择实施完毕：

| 取舍 | 决定 | 结果 |
|---|---|---|
| 导多少 | valid 集全量 17,131 条 | 14.3 秒导完，19,645 条 `APPLIES` 边，Neo4j 占用约 30 MB |
| 案例是否进 prompt | 进，但严格受限 | 每问最多 2 条，单条事实截断 400 字，单独成段 |
| 是否建类案评测 | 暂不建 | 先保证链路通，评测另开一轮 |

**实测验收**

| 项 | 数值 |
|---|---|
| `MATCH (c:Case) RETURN count(c)` | 17,131 |
| `MATCH (:Case)-[r:APPLIES]->(:Law) RETURN count(r)` | 19,645（17,131 + 多法条加成 2,514） |
| 每条案例关联法条数 | 1 个：15,128 / 2 个：1,581 / 3 个：346 / 4 个：63 / 5 个：13 |
| 被引用最多的法条 | 第264条 951 次、第347条 850 次、第234条 574 次 |
| 法条检索 Recall@5（hybrid） | **0.879**（接入前 BM25 基线 0.727，无回退） |
| 法条检索 MRR | 0.741 |

**端到端效果**（问「故意伤害致人轻伤，法院一般怎么判？」）

```
retrieved_by: ["bm25", "graph", "vector"]
sources: 6 条法条 + 案例 CAIL-000356 (故意伤害) + 案例 CAIL-000362 (故意伤害)
```

回答里出现独立的「四、类案参考」段落，逐案写明案号、事实与判决，
并说明「同为轻伤二级，作案方式和情节差异会导致量刑不同」——正是想要的效果。

---

## 七、实现要点

| 文件 | 改动 | 为什么 |
|---|---|---|
| `src/data/cail_loader.py` | 新增 | 条号 int/str 归一化、中文条号转换、刑期三态渲染 |
| `scripts/import_cail.py` | 新增 | `--dry-run` / `--limit` / `--prefix` / `--clear` / `--no-save` |
| `src/data/kg_builder.py` | `import_relations` 改分段解析 | 原实现只取第一个条号，2,003 条多法条案例丢边 |
| `src/data/kg_builder.py` | 加 `article_number` 索引 | 复合约束首列是 `law_name`，按条号反查用不上，2 万条逐行扫全表 |
| `src/retrieval/graph_search.py` | 调整收集顺序 + 条号取类案 | 热门法条挂着上千案例，先收案例会把二跳挤出上限 |
| `src/retrieval/fusion.py` | `reserve_case_slots` | 法条两路加分永远压过只走图通道的案例，不额外附加就进不了上下文 |
| `src/agents/domain_agent.py` | `build_context_blocks` | 法条/类案分区、事实截断、限定条数 |
| `config/settings.yaml` | 3 个新参数 | `graph_case_limit` / `include_cases_in_text_search` / `prompt.*` |

### 两个容易踩的坑

**1. 案例不能进 BM25 和向量语料。** 1.7 万条事实里全是「盗窃」「数额较大」，
进词汇检索会成批挤进 top-K 把法条顶出去。配置项
`retrieval.include_cases_in_text_search` 默认 `false`，类案只由图谱通道按
条号/罪名精确召回。因此**不需要重建 FAISS 索引**（现有索引仍只有 3942 条法条）。

**2. 案例必须在融合后额外附加，不能占法条名额。**
在融合结果里给案例留位会挤掉排名靠后的法条，直接拉低 Recall@K；
改成 `top_k` 条法条 + 最多 2 条类案，法条指标不受影响（实测 0.879 与接入前持平）。

### 重新导入

```bash
python scripts/import_cail.py --dry-run     # 先看转换结果
python scripts/import_cail.py --clear       # 清空旧案例后重导
python scripts/import_cail.py --limit 5000  # 只导一小批试水
```

---

## 八、合规与表述

- CAIL2018 是**赛事公开数据，明确允许学术研究使用**，比爬裁判文书网安全得多。
  使用时按数据集要求引用两篇论文（CAIL2018 论文 + Overview 论文）。
- 数据本身已做当事人匿名化（"张某某"），不含真实身份证号、住址。
- `data/raw/cail/` 与 `data/processed/cases.json` **不要提交到公开仓库**，
  让使用者自己跑脚本拉取。
- 简历/答辩表述建议：
  > 接入 CAIL2018 公开刑事判例集，构建 1.7 万条案例的知识图谱；实现案例-法条多边关联，
  > 支撑「法条 → 类案 → 相邻法条」二跳检索；在 183 个法条、202 个罪名上验证条号映射
  > 覆盖率 100%。

---

## 附：本次实测的环境事实

- 直链：`http://cail.oss-cn-qingdao.aliyuncs.com/CAIL2018_ALL_DATA.zip`（HTTP 可用，HTTPS 在 Windows 下证书检查失败）
- 已落盘：`data/raw/cail/data_valid.json`，24,702,198 字节，CRC32 校验通过
- 语料侧：刑法 505 条（含 53 条「之一」），来自 `data/processed/laws.json`
- Neo4j：`Law 3942 / Case 17,131 / APPLIES 19,645`（接入前是 `Law 3942 / Case 0 / 无 APPLIES`）
- 案例语料：`data/processed/cases.json`，25 MB，**不要提交到公开仓库**（`.gitignore` 已排除 `data/`）
