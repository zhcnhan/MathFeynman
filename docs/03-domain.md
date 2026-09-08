# 03 · 确定性核心（domain）：知识图谱 / 掌握度 / 复习 / 画像

> 本章是**纯逻辑规范**。`domain/` 实现零 LLM 依赖、零 FastAPI 依赖，
> 只依赖 Python 标准库 + 少量纯计算库（sympy 用于判题时除外——判题归 content/service 层调用亦可，
> 但 domain 定义规则本身不调 LLM）。

## 1. 知识图谱（Knowledge Graph）

- 图 = `nodes`（知识点）+ `edges`（依赖：`prereq_of`），**DAG**，不允许环（入库校验拒绝环）。
- 节点最小粒度 = 一个可独立学习、可独立判定的概念（如"一元一次方程求解"，而非"方程"整章）。
- 每个节点带 `level`（学段）：`primary / middle / high / college / ai` 及 `stage_tag`（如 `代数/方程`）。

### 节点状态机（用户侧，按节点维护）

```
locked ──(前置全部 mastered)──▶ available
available ──(开始学习会话)──▶ learning
learning ──(达标规则通过)──▶ mastered ──(FSRS 到期)──▶ reviewing(复习队列)
learning ──(放弃/未达标)──▶ learning（可随时重进，进度保留）
mastered ──(复习多次失败/退化)──▶ learning（降级回炉，见 §3）
```

- `available`：前置（直接依赖）全部 `mastered` 且自身未 `mastered`。
- 推荐顺序：`available` 集合中按图谱层序（topological order）取最浅者。

> **R18 修订（蓝图总序权威，2026-09-08）**："能否学"不再由内容文件手写 prereq 单独决定，而是由
> **课程蓝图总序门禁**（docs/09 R18；实现 `service/path.py`）驱动：内容节点可学 ⟺ 其所属蓝图条目
> 的全部蓝图前置（同文件 + 跨学段已落地部分，跨学段未落地不阻塞、学段顺序兜底）已**达成**（达成 =
> 覆盖节点 mastered；覆盖 = 锚点节点或该条目 auto 节点），首领(boss) 另需其归属蓝图主题组全部条目
> 达成；学段解锁 = 前序（有蓝图内容的）学段已落地条目全部达成（primary 恒开）。图谱手写 prereq 仍作
> 内容结构参考/展示；复习与已掌握/学习中节点不受门禁限制。推荐顺序仍为 available 集合内
> 学段 → 图谱层序 → 编号。

### 三框架 = 图谱上的三条路径（同一张图）

| 框架 | 机制 |
|---|---|
| **捡拾** | 诊断模式：从用户自报起点或图谱根部开始，对每个候选节点出 2–3 道"筛选题"（不进入学习流程）。答错 → 该节点置 `available` 并沿依赖反向找出最近断裂点（首个未掌握的祖先链节点），加入"待捡拾"队列。答对 → 直接 `mastered` 并前进。结果 = 断点清单。 |
| **学习** | 正常主路径闭环（见 §2 与 docs/05）。 |
| **AI 进阶** | 在 `college` 之上的子树：线性代数 → 概率统计 → 优化 → 信息论 → 机器学习数学 → 量化专题（随机过程/时间序列/金融数学）。通过依赖边自然衔接，前置完成即解锁。 |

## 2. 掌握度模型（Mastery）

**MVP 采用 Mastery Learning 规则**（确定、可解释、无数据依赖）：

一次"达标判定"需同时满足：
1. 本节点连续答对 ≥ 3 道**练习**（难度不低于基础档；穿插在会话中，非一次性三连简单题）；
2. 本节点**费曼评估通过**（Rubric 综合分 ≥ 及格线，见 docs/05 §5）。

未达标原因要**分类记录**到用户画像（见 §4），这是自适应的数据来源。

升级路径（P2，数据积累后）：引入贝叶斯知识追踪（BKT）按节点维护 `p(mastered)`，
与 FSRS 记忆概率联合决策。**当前不实现，但 domain 接口需预留**（如 `mastery.get(node_id)` 抽象）。

## 3. 复习调度（FSRS）

- 采用 **FSRS** 算法族（比 SM-2 现代）。Python 侧优先使用开源 `fsrs` pip 包或其等价算法实现；若引入不便，允许自实现 FSRS-4.5 核心（需单测对齐已知卡片行为的抽查用例）。
- 复习项 = 节点（而非单个题目）。复习时从该节点题库抽题重练 + 一次轻量费曼自述（可选开关）。
- 接口：`review.schedule(node_id, rating) -> next_review_at, state`，rating 分级：
  - `again`（完全忘）/ `hard` / `good` / `easy`（与 FSRS rating 对齐 1–4）。
- 行为规则：
  - 复习 rating 为 `again`/`hard` 累计 2 次 → 节点从 `mastered` 降级 `learning`（回炉重学，需重新走达标判定）。
  - 每日仪表盘显示到期复习队列；超过 3 天未复习的到期项进入"堆积警示"（敦促，见 P0 仪表盘）。

## 4. 用户画像（Profile）

存储于 `profile` JSON（或分表），字段：

```jsonc
{
  "user_id": "local",
  "preferred_explanation_depth": 2,        // 1 直觉类比 → 5 严格推导（随反馈调整）
  "preferred_examples": ["生活类比", "几何直观", "纯代数"],
  "error_profile": {                        // 按错误类型计数（识别来源见 §5）
    "arithmetic_slip": 3,
    "concept_confusion": 7,
    "step_omission": 2,
    "sign_error": 5
  },
  "styling_notes": [],                      // AI 从费曼交互中提取的风格观察（人工确认后入列）
  "session_counts": {"explain": 12, "feynman": 9}
}
```

- 画像特征在每次调用 AI 讲解/追问时以"教学风格块"注入 prompt（见 05 §4 注入模板）。
- 错误类型识别：练习判题时若错误，用轻模型对"错答+正确过程"做一次分类（schema 化），或由费曼环节 rubric 同时产出。计数入库。

## 5. 错误类型定义（判题/费曼共用枚举）

| 类型 | 含义 |
|---|---|
| `arithmetic_slip` | 思路对，计算笔误（含符号抄错，与 sign_error 区分：符号错但在变换环节） |
| `sign_error` | 正负号系统性错误 |
| `concept_confusion` | 概念理解错位（如把乘法分配律用到加法上） |
| `step_omission` | 跳过必要步骤导致推导断裂 |
| `procedure_misuse` | 方法用错（如该因式分解却展开） |
| `notation_error` | 表达式/记号书写不合法 |
| `unknown` | 轻模型无法归类（人工可订正） |

## 6. domain 接口草图（实现参考，不强制签名一致）

```python
# domain/graph.py
class KnowledgeGraph: available(user_id) -> list[Node]; path_to(node_id) -> list[Node]
# domain/mastery.py
class MasteryEngine: evaluate_pass(node_id, user_id, stats) -> bool
# domain/fsrs.py
class FsrsScheduler: schedule(node_id, rating) -> ReviewState; due(user_id, day) -> list[Node]
# domain/profile.py
class ProfileStore: get(user_id) -> Profile; record_error(node_id, etype); adjust_depth(delta)
```
