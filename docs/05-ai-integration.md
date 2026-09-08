# 05 · AI 受控集成规范（本项目的方法论核心）

> 阅读对象：所有实现 LLM 相关代码的人。
> 一句话原则：**教学流程是程序的状态机；LLM 是状态机里被 schema 约束的"函数"。
> 确定性系统永远保有最终裁决权（判题、进度、复习），LLM 的每一条输出都过校验才能生效。**

## 1. 为什么这样做

- 自由聊天机器人式教学：不可控、易幻觉、学无进度、无法评估——**否决**。
- 本方案 = **受控生成（constrained generation）+ 编排（orchestration）**：
  程序决定"现在该做什么"，LLM 决定"这一步怎么措辞/生成什么变体/如何评价语义"。
- LLM 永不直接修改：节点状态、掌握度、复习调度、练习对错。它只能**返回数据**，由 service 层裁决生效。

## 2. 教学会话状态机（学习闭环）

一个节点的标准会话流程（`service/session.py` 实现，状态持久化于 `sessions` 表）：

```
START
 ├─ choose: 讲解讲解稿 (LLM call #1: 按 explanation.body + 画像风格演绎讲解)
 ├─ 用户可能提问 → 答疑 (LLM call #1b: 答疑，白名单约束，见 §4)
 ├─ 例题展示（来自 content，程序直接渲染；LLM 仅解释每一步，可选 call）
 ├─ 练习循环：
 │     抽题(程序，模板渲染) → 用户作答
 │       ├─ sympy 判题 correct → 计分；可能追问"为什么这一步是对的"(轻校验)
 │       └─ wrong → 判题给出 hint；用户重试(≤2)；仍错 → 触发讲解回炉 + 答疑
 │     循环至：连续 3 对 或 达到上限(5题) 或 用户要求提示耗尽
 ├─ 费曼环节（若练习达标则进入；否则先回炉）：
 │     (Feynman flow 见 §5)
 └─ END: service 层调用 mastery.evaluate_pass → 更新状态 → 若达标则 fsrs.schedule 首次排程
```

- 状态机是**程序真源**：每次 LLM 调用由状态机触发并携带 `session_id`、`node_id`、
  白名单、阶段标签；LLM 响应只回到当前状态的处理函数，不会跳转状态。
- 会话可中断/恢复（练习进度、费曼轮次存库）。用户可在任意步骤"退出学习"，状态保留在 `learning`。

## 3. LLM 调用点清单（Call Sites）

所有调用点收敛在 `ai/calls.py`，每个调用点 = 一个纯函数：

```python
@dataclass
class CallSpec:
    name: str                  # 如 explain_node
    model_tier: str            # heavy | light（见 02 架构 §4）
    input_schema: type[BaseModel]     # 入参（含注入的 content 片段）
    output_schema: type[BaseModel]    # 出参（JSON，必须校验）
    temperature: float = 0.6
    max_retries: int = 2
```

MVP 调用点一览（后续按需增补，规则同）：

| # | name | tier | 输入注入 | 输出（JSON 要点） | 生效方式 |
|---|---|---|---|---|---|
| 1 | `explain_node` | light（R9 降档） | explanation.body、core_concepts、prereqs 标题、画像风格块、白名单 | `{lecture_md, asked_to_confirm[]}` | 仅展示；含"引导确认/提问"出口 |
| 2 | `answer_question` | heavy | 当前节点讲解稿、core_concepts、白名单、学生问题 | `{reply_md, needs_more_info: bool, out_of_scope: bool}` | 仅展示；out_of_scope(smart)→think 重生成一次 |
| 3 | `generate_practice_variant` | light | 模板 + 已出题列表（防重复） | `{param_values, prompt_md}` | 交模板渲染器**重新验算**后才可用（§4-04） |
| 4 | `hint_on_error` | light | 题目、学生错答、sympy 诊断（哪步不符） | `{hint_md, never_solution: true}` | 仅展示；禁止输出完整解答 |
| 5 | `explain_solution_step` | light | 例题步骤文本 | `{step_explanation_md}` | 仅展示 |
| 6 | `feynman_evaluate` | heavy | 节点 feynman.rubric、学生口述全文、任务 prompt | 见 §5 输出 schema + `confidence?` | service 按 rubric 权重合成分数 |
| 7 | `feynman_followup` | heavy | 学生口述、上一轮评分摘要、socratic_followups 主题 | `{question_md}` | 仅展示（最多 2 轮追问） |
| 8 | `classify_error` | light | 题目、正确答案过程、学生错答 | `{error_type}`（枚举见 03 §5） | 写入画像 |
| 9 | `draft_content` | light | 节点规格 + 04 文档 schema 说明（骨架内嵌） | 完整 .md 草稿 | 校验全过 auto 入库 / high+ 进 `_drafts/` |

**调用策略（R12 落地）**：调用点 1/2/4/6/7 每次由 `ai/tier` 决策 `fast|think`（service 计算后随
`strategy` 传给网关 → provider 选 light/heavy 模型）；`model_mode=deep` 全 think、`light` 关触发、
单次 `payload.think_deep` 覆盖；ai_logs.tier 记录实际策略档。费曼评分未达与边缘区间等触发详情见 docs/09 R12。

## 4. 防幻觉与概念白名单（每次注入的公共约束）

每个生成类调用点（1/2/3/4）的 system prompt 统一包含 **ContextBlock**：

```
[角色] 你是本学习系统的数学导师，面向[当前学段]学生。
[教学内容真源] 以下是本节点官方讲解稿，只能在此基础上演绎，不得改动事实：
<explanation.body + worked_examples 原文>
[概念白名单] 允许涉及的概念：<core_concepts + prereqs.title 列表>。
[禁令] 禁止引入白名单之外的新名词/公式/方法；如果学生问题超出范围，
       回答"这属于后面的 X 部分，我们先专注当前内容"并给出继续学习的建议。
[风格] <profile 风格块：解释深度档位、偏好例子类型、最近错误类型提示(如"注意符号")>
[输出纪律] 只输出 JSON，字段见 schema；数学用 LaTeX；不得输出学生尚未学的结论。
```

- 白名单由程序从图谱取 `node.prereqs ∪ node.core_concepts`，**LLM 无权扩白**。
- 学生问超纲问题（常见于好奇提问）：按禁令礼貌截断，记入画像 `styling_notes`（可成为后续学习的钩子）。

## 5. 费曼流程与评分（Feynman Flow）

```
1. service 出任务：feynman.task_prompt（含 rubric 说明"请像对老师讲解"）
2. 学生口述（打字；语音是 P2）→ 完整存库（attempts 表）
3. feynman_evaluate 调用：
   输出 schema:
   {
     "dimension_scores": [{"key":"correctness","score":0.0..1.0,"evidence_quote":"学生原话片段",
                            "comment":"为什么给这个分"}],
     "overall_note": "...",
     "misconceptions_found": [{"concept":"...","evidence":"..."}],
     "recommend_action": "pass|followup|relearn"
   }
   —— evidence_quote 必须逐字引用学生原话，禁止无据评分
4. service 合成综合分 = Σ(weight×score)；对比 pass_threshold。
   - 未过且轮次 <2 → feynman_followup 生成 Socratic 追问（针对 misconceptions），学生回答后回到 3（重评，但把首轮评分作为二轮 context）。
   - 3 轮仍不过 → recommend_action=relearn → 节点不达标，回到练习/讲解回炉（计入画像 concept_confusion）。
5. 费曼通过 → 若练习也已达标 → mastery 达标，FSRS 首次排程（rating 默认 good）。
6. 全部费曼评估保留记录供用户复盘（"我当时哪里讲错了"回看）。
```

评分防作弊要点：
- rubric 逐维输出 + 原话引文，让评分可审计；
- 学生口述若过短（< 20 字）→ 服务层直接判"敷衍"，提示重讲，不进评分；
- 评分结果不直接驱动状态：状态由 service 按阈值裁决。

## 6. Provider 与失败处理

`ai/provider.py`：

```python
def chat_json(call: CallSpec, *, messages) -> dict:
    # 1. 拼 OpenAI 兼容请求（base_url/model 按 tier 从配置取）
    # 2. response_format={"type":"json_object"} 或强提示 + 后处理剥离围栏
    # 3. pydantic 校验输出 → 失败重试 ≤ max_retries（重试可附错误信息要求修正）
    # 4. 仍失败 → 抛 AiCallError
```

- service 层捕获 `AiCallError`：生成类调用点降级为**内容库兜底**（如直接展示讲解稿原文、
  不生成变体只用模板、费曼评分降级为人工复核队列）；**绝不**让降级破坏状态一致性。
- 所有调用记录 `ai_logs` 表：model、tokens、耗时、校验结果——成本与质量可审计（对预算管理必要）。
- 预算/成本开关：设 `LLM_MAX_TOKENS_PER_DAY` 之类限额（可选），超限时自动切轻模型/本地兜底并提示。

## 7. 边界与红线（实现审查清单）

- [ ] domain 无任何 `import` ai/LLM。
- [ ] 任何 LLM 输出在被持久化/生效前都过 pydantic 校验。
- [ ] 判题结果只来自 sympy（`manual_review` 模式除外，且进人工复核队列）。
- [ ] 白名单概念不可被 LLM 输出扩展（讲解文本可被 UI 高亮检查——阶段：文本内出现的
      概念词表若发现白名单外词，UI 给出"超纲提示"气泡，属可观测的护栏）。
- [ ] 练习 hint 永不包含完整解答（service 层字符串检查：答案表达式出现在 hint → 丢弃换模板）。
- [ ] 学生口述/作答明文存本地 SQLite（本地单机可接受；公众化时再加密）。
