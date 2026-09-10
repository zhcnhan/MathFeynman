# 06 · 后端 API 草案与数据模型
> 适用范围：范围：API 现状（math 形态端点）。subject 命名空间改造见 docs/14 Phase A

> 供前后端联调与实现参考。签名可微调，但**语义与状态流转必须符合 docs/03、docs/05**。
> 所有端点默认前缀 `/api`，JSON 通信。**错误响应统一嵌套体**（2026-09-09 起，R19 块2）：
> `{"detail": {"error": {"code": ..., "message": <中文人话>}}}`；校验错误与未捕获 500 均走全局
> 处理器输出中文 message（不暴露英文堆栈）；前端对无文案/网络错误另有中文状态兜底（docs/13 §2）。

## 1. REST 端点草案

### 图谱与仪表盘
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/graph` | 全图（节点+边+状态），前端渲染图谱（C3：停用学科内容节点/边按 subject.enabled 隐藏） |
| GET | `/nodes/{node_id}` | 节点元数据 + content 摘要（不含答案） |
| GET | `/dashboard` | 今日复习队列、当前推荐节点、累计统计、断点清单（捡拾结果）；C3：推荐/统计/复习仅在启用学科节点内收敛（停用学科隐藏）；**R36 L1**：新增 `preset_subject: {id,label,enabled}\|null`——预置学科生命周期状态**直出**（前端据此显示"预置学科已停用"中文横幅，不再从 `/subjects` 反推） |

### 学科与大纲（docs/14 Phase A A1 起；math 为预置学科，通用学科=用户自建）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/subjects` | 学科列表（含大纲摘要：revision/status/units/组） |
| POST | `/subjects` | 创建自定义学科（body: label/description/subject_id?，id 须 `^[a-z][a-z0-9-]*$`） |
| GET / DELETE | `/subjects/{subject_id}` | 学科详情 / 删除自定义学科（preset 不可删） |
| GET | `/subjects/{subject_id}/outline` | 当前大纲全文（审阅；无大纲 404） |
| PUT | `/subjects/{subject_id}/outline` | 采纳/整份重生成（custom；revision+1；结构校验：唯一/自指/环/引用/**R36 P1 难度不得倒置（roadmap 源豁免）**）；**R36 D3**：服务端按各单元 `materials[].title` 反查 material_id 写入 `source_materials`（引用不存在的材料 → 中文 422）；**R37 S2/S7**：**教材章节全覆盖校验**（地图条目未映射 → 中文 422"教材覆盖不全"）、材料文本层不合格 → 中文 422 |
| POST | `/subjects/{subject_id}/outline/validate` | 校验候选大纲（不落盘，返回问题清单，UI 预览用；按 `source` 生效 P1——roadmap 源豁免） |
| PATCH | `/subjects/{subject_id}/outline/units/{unit_id}` | 单元局部改（custom 任意白名单字段；preset 仅 concept_tags 等附加字段） |
| POST | `/subjects/{subject_id}/outline/regenerate` | 大纲重生成：math=roadmap 派生 revision+1；custom=重新起草候选（不落盘，采纳 PUT 才 +1；**同样注入引用材料**） |
| POST | `/subjects/{subject_id}/outline/draft` | AI/启发式起草大纲候选（body: brief/count/group_hint；LLM_API_KEY 时走 CALL_OUTLINE_DRAFT，否则离线启发式；不落盘，供审阅后 PUT 采纳）（A4）；**R36 D1–D4**：注入该学科引用材料，要求逐单元 `materials:[{title,section}]` 溯源并服务端校验（不成立 → 驳回重生成一次 → 仍不成立则剔除并记问题）；**R37 S1/S2/S8**：默认**不设注入预算**（`MF_MATERIAL_INJECT_MAX_CHARS=0`；>0 时它是**单次调用预算**，只改"每批装多少"、**不丢章节**——R38 §3 共存口径），按 `outline.bookmap` 的**章→节地图**注入**完整正文**，书太大按 `MF_MATERIAL_BATCH_CHARS` 在章/页边界**分批**（绝不"前 N 字"）；单元由书序派生并按书序重排/重编号（`notes` 记录规范化决定）；每个章/节条目必须映射到 ≥1 个单元（未映射者先确定性回捞、再按教材目录补齐并记 `problems`）；**扫描/图片版（文本层不合格）→ 中文 422**；响应含 `source_materials`、`material_usage{count,used_chars,per_call_chars,batch_count,dropped(=恒空),truncated(=恒 false),batches,blocked}`、`coverage{total,covered,uncovered}`、`notes` |
| POST | `/subjects/{subject_id}/units/{unit_id}/content` | 懒生成单元内容（source:auto 落盘 + 库/DB 同步，幂等；仅 custom 学科；math 走 roadmap 流水线）（A4）；**R37 S3/S4/S5**：注入该单元对应教材章/节的**完整正文**；事实句与题目引文必须**逐字出自教材**，否则丢弃该题 / 整单元失败（`status="uncovered"`，中文 note，**不落盘**）；响应含 `coverage{status:完整\|部分\|未覆盖, grounded_facts, dropped_facts, dropped_exercises, sources, note}` |
| GET | `/subjects/{subject_id}/coverage` | **R37 S6 覆盖账本**：`total/covered/uncovered`（章/节条目 ↔ 单元映射）+ `materials[{healthy,structure_kind,structure_note}]` + `entries[]` + `units[{sources,status,note,grounded_facts,dropped_exercises}]`（大纲页同源展示）；**R38 B1**：增 `by_material[]`（**按材料分组**的已覆盖节/总节 + 未覆盖清单）、`uncovered_by_material[]`、`uncovered_materials[]`（整份未纳入）、`order_basis`（顺序依据：角色/导入顺序）、`page_total/page_covered`（**章级统计、页级可下钻**）、`entries[].pages[]` |
| GET | `/subjects/{subject_id}/budget` | **R38 材料注入预算视图**（学科管理卡材料区）：`batch_chars{value,source,source_zh,set}`（单次调用预算＝滑块 A）、`inject_max_chars{…}`（总注入上限＝滑块 B；0=不限）、`per_call_chars`、`tiers{batch,inject}`（档位）、`last_usage{used_chars,batch_count,per_material[],not_injected[],order_basis,summary_zh,note_zh}`（"共注入 X 字，分 N 批"）、`context_valve{applied,context_tokens,limit_chars}`、`materials[]` |
| PUT | `/subjects/{subject_id}/budget` | **R38 两个滑块改值**（body `{batch_chars?, inject_max_chars?}`；单位＝字符，**0=不限**；落 `subjects.meta_json`，**不新建表**）；**立即生效**且回读一致；非法值 → **中文 422**；优先级：单次请求参数 > 学科滑块 > `.env` > 内置默认 |
| PUT | `/subjects/{subject_id}/materials/{material_id}/role` | **R38 B2 材料角色**（body `{role: main\|supplement}`）：主教材定顺序与范围、补充材料只补细节与例题；未标注 → 按**导入顺序**并在覆盖账注明 `order_basis=导入顺序`；非法角色 → 中文 422 |
| GET | `/subjects/{subject_id}/ledger` | **R39 §1 学科就地账目**（材料页/大纲页/单元页"看全部"入口）：该学科的账目（时间倒序）+ `counts`（按类别计数） |
| GET | `/subjects/{subject_id}/progress` | 学科进度视图（单元 达成/等效/开放 + 内容节点状态；A2） |
| POST | `/subjects/{subject_id}/progress/recompute` | 幂等重算概念掌握证据（= 数学历史掌握迁移入口；A2） |
| POST | `/subjects/{subject_id}/progress/reset` | 显式重置学科进度（清概念层 + 学科内容掌握；body `{mode: all}`；A2） |
| GET / PUT | `/subjects/{subject_id}/policy` | 内容来源策略（ai/import/web/mixed，默认 ai；B3） |
| POST | `/subjects/{subject_id}/materials/upload` | 本地导入文本 → 本地引用库（B3；粘贴文本入口保留） |
| POST | `/subjects/{subject_id}/materials/upload-pdf` | **PDF/文档上传**（multipart：title? + file）→ pypdf 分页/分节文本 → 引用库（kind=pdf；≤20MB 等限制、失败中文 422；C2）；**R37 S7**：响应含 `text_health{pages,chars,healthy,checked,note}`——无文本层/极稀疏 → `healthy=false` + 中文告知"请先 OCR 或改用文本版"（**不再静默**；该材料会被起草/采纳拒绝） |
| GET | `/subjects/{subject_id}/materials` | 引用材料列表（含 kind：local/web/pdf、源文件名、**R37 `text_health`**、**R38 `role/role_explicit/role_zh`**；B3+C2） |
| DELETE | `/subjects/{subject_id}/materials/{material_id}` | 删除单条材料（B3） |
| POST | `/subjects/{subject_id}/materials/search` | 联网候选清单（C1 provider 抽象：默认未启用 → `{items:[], note:中文提示, backend:{configured:false}}`（UI 标注"未配置检索后端"）；配 SearXNG → 检索 →（配 LLM_API_KEY）LLM 整理候选） |
| POST | `/subjects/{subject_id}/materials/select` | 勾选候选 → 本地化引用；`items[].fetch=true` 时抓取该公开网页正文入库（text/html、大小上限；失败回落摘要；不整本下载书籍）（B3+C1） |
| POST | `/subjects/{subject_id}/enable` | 重新启用被移除（停用）学科（B4） |
| GET | `/subjects?include_removed=1` | 含停用学科列表（管理"移除可恢复"；B4/C3） |
| DELETE | `/subjects/{subject_id}?hard=true` | 学科移除：默认=停用（隐藏+清进度——**math 亦清其全部学段内容节点进度**，大纲/内容/roadmap 留盘可恢复）；`hard=true` 仅 custom 连同文件删除（math 拒 hard）（B4/R22/C3） |

### 学习会话
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/session/start` | body `{node_id}` → 创建/恢复会话，返回状态机当前步与首批内容（讲解稿演绎结果可选异步）。**R18 总序门禁**：无既有会话而新建时校验蓝图总序（docs/09 R18）；越级 → `409 invalid_state`，detail 含"请先完成：<前置条目标题>"。既有会话恢复 / 练习·费曼续走 / 复习不受门禁影响 |
| POST | `/session/step` | body `{session_id, action, payload}`；action ∈ `ask_question / next / submit_exercise / request_hint / regen_explain / reissue_after_regen / feynman_submit / feynman_answer / challenge_start / challenge_begin / challenge_submit / challenge_cancel / challenge_abandon / finish / quit`（`next` = 阶段前进：讲解→例题→练习，见 docs/09 R1）。**R27 双提交分离**：`feynman_submit` = 完整稿（首讲/整合重讲）→ 整体评分；`feynman_answer` = 补答（只答当前追问，payload `answer`）→ 轻量缺口补答评估。**R35 S3 挑战题池**：`challenge_*` 五个动作（见 §2.2），**永不出现在默认流程**、不设额度/不计轮次/不影响任何进度。返回：下一步 UI 状态 + 新内容 + 状态机事件流 |
| GET | `/session/{id}` | 恢复会话全状态（**不含**挑战题：挑战题只随 `challenge_*` 动作下发） |

### 练习与判题（幂等，供前端直接调用或经由 step）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/exercises/check` | body `{exercise_id, params_seed, user_answer, session_id?}` → 该学科判题器结果（math=sympy）+ hint（不泄答案） |
| POST | `/exercises/next` | body `{node_id, exclude_ids}` → 下一道题（模板渲染或 AI 变体） |
| POST | `/exercises/unanswerable` | **R35 S7**：「这题我没法答（讲解里没有）」→ 复用 `feedback` 表加 `kind=answerability`（不建表）；**不计失败/不扣分**，进护栏统计；auto 内容走既有重生成闭环 |

### 复盘（attempts 回看；**同一张表、同一套读法**，不新建存储）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/history/feynman` | 费曼口述历史（逐字转写 + 评分卡，docs/07 §2.3） |
| GET | `/history/challenge` | **R35 S3**：挑战题复盘（`attempts.kind="challenge"`；含 `verdict=abandoned` 的明确放弃记录）。仅复盘用，**不计入任何进度** |

### 复习
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/review/queue` | 到期复习列表（含堆积警示） |
| POST | `/review/submit` | body `{node_id, rating(1-4), answers[]}` → 更新 FSRS 状态，返回下个到期日 |

### 画像与配置
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/profile` | 画像（错误类型、风格偏好） |
| PATCH | `/profile` | 用户手动调整偏好（解释深度等） |
| GET | `/config/models` | 当前模型分级配置（供设置页显示，不改密钥） |

### 内容管理（开发工具，MVP 阶段 CLI 为主）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/content/validate` | 运行全库校验并返回报告 |
| GET | `/content/drafts` / POST `/content/drafts/{id}/promote` | 审核 drafts（见 04 §6） |

### 一切显性 / 提示词 / 审计（**R39**）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ledger` | **总账（「一切显性」铁则的"一处看全部"）**：query `subject_id?/category?/limit?/offset?`；类别 ∈ `material\|generation\|model_call\|coverage\|other`（中文标签随响应给出）；时间倒序 + `counts`（类别计数）；类别非法 → `note` 中文提示（不 500） |
| GET | `/ledger/cats` | 类别计数（筛选项徽标） |
| GET | `/ledger/snapshot/{subject_id}` | 某学科账目快照（就地提示的"看全部"入口） |
| POST | `/ledger` | 手动补记一条（前端动作也可入账；类别非法 → 中文 422） |
| GET | `/prompts` | **全部提示词调用点**：中文名 + 用途 + `is_default` + `updated_at` + 当前值 + 与默认的差异 `system_diff` + 必填占位符/硬约束清单；`changed` 列出已改的调用点 |
| GET | `/prompts/{call_name}` | 单条（含 `raw_template` = **可编辑模板原文**（带 `{占位符}`）；`default_system` = 渲染后的可读默认值） |
| PUT | `/prompts/{call_name}` | 保存（body `{system?, user?}`）；**改动立即生效**；缺必填占位符/硬约束、或模板花括号不合法 → **中文 422 拒绝保存**；成功 → 记入账本 |
| POST | `/prompts/{call_name}/reset` | 单条恢复默认（body `{field: ""\|system\|user}`） |
| POST | `/prompts/reset-all` | 全部恢复默认（前端恢复前确认） |
| GET | `/settings` | 应用设置：`developer_mode`（**调试模式开关**）+ `ai_trace{dir,keep_days}` |
| PUT | `/settings` | 改开关（body `{developer_mode}`）；**审计本身默认记录**，开关只决定界面入口是否出现 |
| GET | `/ai-traces` | **AI 对话审计列表**（query `subject_id?/call_name?/outcome?/only_failed?/limit?/offset?`）：时间倒序、**失败与丢弃置顶**；每条含 时间/调用点/档位/模型/token/耗时/重试/结局/`trace_path`+`trace_chars`+三段预览+`prompt_versions` |
| GET | `/ai-traces/{id}` | 单条完整对话：`full{system,user,response,parse_result,meta}`（**上=发给 AI 的完整内容，下=AI 返回的完整内容**，读全文文件；文件缺失 → `note` 如实说明 + 预览兜底）；**非流式** |
| POST | `/ai-traces/cleanup` | 按保留期清理审计全文文件（body `{keep_days?}`）；**先记账（清理了哪几条）再删除**（不静默消失） |

## 2. `/session/step` 的响应协议（前后端契约要点）

```jsonc
{
  "step": "practice",            // 状态机当前阶段 explain|example|practice|feynman|done
  "payload": { /* 依阶段而定：讲解文本 / 例题 / 题目对象 / 费曼任务或追问 */ },
  "events": [                    // 供 UI 展示的流水（也用于测试断言）
    {"type": "exercise_correct", "node_id": "...", "consecutive_correct": 2},
    {"type": "hint_given", "count": 1},
    {"type": "feynman_passed", "score": 0.83},
    {"type": "node_mastered", "node_id": "..."}
  ],
  "session": {"id": "...", "state": "learning", "attempts_left": 3}
}
```

前端**无状态判断逻辑**：所有"下一步显示什么"由后端状态机裁决（防止前端逻辑分支漂移）。

### 2.0 费曼阶段 payload（R27 v3 混合制，docs/09 R27）

费曼阶段的 `payload` 恒带**缺口账本视图**（前端实时得分条数据源）：

```jsonc
"ledger": {
  "dimensions": [{"key": "correctness", "score": 0.88, "best": 0.88, "latest": 0.88,
                  "weight": 0.4, "evidence_quote": "…", "comment": "…", "updated_round": 1}],
  "combined": 0.69,      // 实时综合分 = Σ(w·账本维度最高分)/Σw
  "threshold": 0.7,
  "gaps": [{"key": "evidence", "description": "还差：说出任意一种观测/探测方法", "score": 0.1}]
},
"combined": 0.69, "threshold": 0.7,
"evals_done": 1, "eval_budget": 3,       // 整体稿评分：首讲 + ≤2 次终验
"answers_done": 0, "answer_budget": 2,   // 补答：≤2（须有未答缺口）
"next_action": "answer" | "submit",      // 有定向追问 → answer；否则 submit（交整合完整稿）
"followup_question": "…", "followup_gap": {"key": "evidence", "description": "…"},
"followup_quote": "…",                   // R35 S4：**逐字引用学生刚说的话**（服务端包含校验通过）
"followup_missing": "…"                  // R35 S4：这句话缺了什么（学生视角）
```

- `verdict`：`fail`（完整稿未达标，附本轮 `dimension_scores`）/ `gap`（补答结果，附
  `gap_filled`、`gap_key`、`gap_update`）/ `pass`（由 `mastered` + `feynman_passed` 事件体现）
  / `deferred`（评分服务不可用，进人工复核）/ **`reteach`（R35 S4：退回讲解补讲，见下）**。
- `dimension_scores[].evidence_valid`：服务端**包含校验**结论（引文必须逐字出自本轮提交文本，
  且归一化后 **≥6 字**——极短引文视为无效，R30 F5）；
  `false` 时该维度分数已降级（×0.5），并带 `evidence_reason`。
- **通过判定**：只有完整稿（`feynman_submit`）评分 ≥ threshold 才 pass → mastery；
  补答只涨账本与展示进度，不能单独过关（R27 §5）。
- **边缘带复评（R30 F6）**：完整稿单轮综合分落 `[threshold−0.05, threshold+0.08]`（0.7 → [0.65,0.78]）
  且本轮档位非 think → 以 think 档**复评一次**，取两次综合分较高者为本轮结果（每次提交最多 1 次额外
  heavy 调用；复评失败保留首次、不 500）。两次分与采用结论写入 `attempts.meta.recheck =
  {used, first_combined, second_combined, taken}`；响应 `strategy` / `strategy_reason` 为**实际采用**那次
  （复评被采用时 `strategy_reason="edge_recheck=think"`）。
- 事件：`feynman_followup`（定向追问，带 `target_gap`）、`feynman_reteach`（R35 S4：无可引用内容 →
  退回讲解补讲，带 `reason`）、`feynman_gap_filled` / `feynman_gap_open`、`feynman_evidence_flagged`、
  `feynman_relearn`（额度尽/3 次未过回炉）、`feynman_edge_recheck`（`{first, second, taken}`；
  复评失败时 `second=null`）。

### 2.0.1 追问纪律 `reteach`（R35 S4，docs/09 R35 §3 S4）

**追问必须先逐字引用学生刚说过的话**，并指出"这句话缺了什么"（`followup_quote` / `followup_missing`）；
学生**没有可引用的实质内容**（如只写"我不知道"）时**禁止硬造发散题**，返回：

```jsonc
"verdict": "reteach",
"next_action": "reteach",
"reteach": {
  "reason": "no_quotable_content | quote_not_verbatim | missing_not_stated | model_says_reteach | question_empty",
  "message_md": "📖 退回讲解补讲：…（中文说明，含「答不出不会逼你想」）",
  "lecture_md": "讲解原文（当场可回看）",
  "missing_dimensions": [{"key": "evidence", "description": "…"}]
}
```

- **不消耗额度**：`reteach` 不增 `evals_done`/`answers_done`、不动账本（敷衍回答不该吃掉评分预算）；
- **不翻转状态机**：阶段保持原样（练习已通过时"回到讲解"会**重新出题**并再次计入练习账目——
  等于用一次敷衍回答污染练习记录）；改为随响应下发讲解原文 + `next_action="reteach"`；
- socratic 主题**只有在 `socratic_basis` 逐字成立时**才作为追问语料下发（模板套话不得兜底）。

### 2.2 挑战题池（R35 S3，docs/09 R35 §3 S3）

**两个池**：核心题池（计入掌握与费曼）与**挑战题池（完全不上算）**。挑战题**永不出现在默认流程**，
由「挑战一下」按钮**用户主动触发、单独调模型生成**（`challenge_exercise` 调用点）。

```jsonc
// 五个动作（POST /session/step）：
// challenge_start    → 生成一道挑战题（payload 可带 think_deep）
// challenge_begin    → 开始作答（纯 UI 状态推进，无任何后果）
// challenge_submit   → 提交作答（payload {answer}）→ 单独判分
// challenge_cancel   → 取消本次（丢掉这题，**不写 attempts**）
// challenge_abandon  → 明确放弃（"我不会/我不感兴趣"，只记复盘）
"challenge": {
  "notice": "挑战题：需要讲解之外的知识，答不出不影响任何进度",   // UI 必须显式展示
  "phase": "idle | offered | answering | graded",
  "question": {"prompt_md": "…", "answer_hint_md": "…", "why_hard_md": "…", "difficulty": 3} | null,
  "last": {"correct": true, "score": 0.6, "feedback_md": "…", "better_md": "…"} | null,
  "asked": 1, "answered": 1,      // **仅展示计数**：不限额、不计轮次、不做任何门禁
  "degraded": false,
  "counts_nothing": true          // 契约位：前端不得据此渲染任何进度/分数影响
}
```

- 事件：`challenge_offered` / `challenge_begin` / `challenge_graded` / `challenge_cancelled` /
  `challenge_abandoned`。
- **红线（实现即验收）**：挑战题作答后 **mastery / 费曼账本（含整体稿与补答额度）/ 掌握统计
  四项均不变**，只写 `attempts.kind="challenge"`（复盘）。`/api/dashboard` 的 `today_done`
  按 `models.PROGRESS_KINDS` 白名单统计，**挑战题不计入**。
- **学科无关**：与核心题池走同一套链路（`context_block` 注入 + schema 校验 + 降级），
  无任何学科分支；挑战题**允许且要求**超出讲解（这正是它与核心题池的区别）。
- 生成与判分 = 两个独立调用点 `challenge_exercise` / `challenge_check`（均为 light 档）。

### 2.1 流式协议（R12-b，SSE 可选）

`POST /session/step?stream=1`（body 与普通 step 相同）返回 `text/event-stream`：

- `event: start` → `{"session_id", "action"}`；
- 处理期间每 ~1s 心跳：`event: ping` → `{"seconds"}`；
- 结束：`event: result` → **与普通响应完全一致的完整 JSON**（上文 §2 结构，契约不变）；
- 失败：`event: error` → `{"code", "message"}`（code 同 §4 错误码）。

约定：前端把流的 `result` 当作普通 step 响应处理；流不可用/解析失败/`error` 事件时
**自动回退普通 `POST /session/step`**；服务端同步逻辑跑在工作线程，不占事件循环，
LLM 等待前仍按 R7 先提交事务释放写锁。长文本（讲解/答疑回复/追问）由前端做打字机展示。

## 3. SQLite 表结构草案

```sql
subjects     (id TEXT PK, label TEXT, kind TEXT,       -- Phase A：kind=preset(math)|custom
              description TEXT, meta_json TEXT,        -- meta_json.source_policy（B3：ai/import/web/mixed）
              enabled INTEGER DEFAULT 1, removed_at DATETIME,  -- B4：停用标记（移除可恢复）
              created_at)   -- 大纲文档在 content/subjects/<id>/outline.yaml；材料在 <id>/materials/
users        (id TEXT PK, profile_json TEXT, created_at)            -- MVP 恒为 'local'
nodes        (id TEXT PK, yaml_path TEXT, title, level, topic,
              objectives_json, core_concepts_json, feynman_json,
              content_hash, enabled INTEGER)
edges        (node_id TEXT, prereq_id TEXT, PK(node_id, prereq_id))
             -- 内容库加载时由 `content validate` 写库，确保与文件一致（content_hash 校验）
user_nodes   (user_id, node_id, state TEXT,           -- locked/available/learning/mastered/reviewing
              consecutive_correct INT, attempts_total INT,
              last_error_type TEXT, mastered_at, PK(user_id,node_id))
sessions     (id TEXT PK, user_id, node_id, state TEXT,  -- 状态机当前步
              flow_json TEXT,           -- 会话内累积数据（练习计数、费曼轮次等）
              created_at, updated_at)
attempts     (id INTEGER PK, session_id, node_id, kind TEXT,   -- exercise|feynman|challenge
              exercise_id, params_json, user_input TEXT,
              verdict TEXT,             -- correct|wrong|score|pass|fail|deferred|gap_filled|gap_open|abandoned
              error_type TEXT NULL, meta_json, created_at)
              -- R35 S3：kind="challenge" = 挑战题（**只进复盘**）；进度统计一律按
              -- `models.PROGRESS_KINDS`（exercise|feynman）白名单过滤，挑战题不计入今日完成等任何统计
reviews      (user_id, node_id, state_json,            -- FSRS 状态
              due_at, last_rating, lapse_count, PK(user_id,node_id))
ai_logs      (id INTEGER PK, call_name, model, tier, prompt_tokens, completion_tokens,
              ok INTEGER, error TEXT, latency_ms, created_at,
              -- R39 §3：审计扩字段（旧库由 db._migrate_columns 幂等补列）
              subject_id, unit_id, retries INTEGER, outcome TEXT,   -- adopted|degraded|dropped|failed
              prompt_versions TEXT,                                 -- "哪次生成用的哪版提示词"
              trace_path TEXT, trace_chars INTEGER,                  -- 全文落 .runtime/ai_trace/
              system_preview TEXT, user_preview TEXT,
              response_preview TEXT, parse_result TEXT)
relearn_logs (user_id, node_id, reason TEXT, created_at)   -- mastered→learning 降级留痕
-- R39（新数据建表正当）：
content_ledger(id INTEGER PK, subject_id, unit_id, category TEXT,   -- material|generation|model_call|coverage|other
              object TEXT, reason TEXT,      -- 对象 / **中文原因**
              impact TEXT, remedy TEXT,      -- 影响面 / 可否补救
              detail_json TEXT, created_at)  -- 「一切显性」铁则的唯一落库点（service/ledger.py）
prompt_overrides(call_name TEXT PK, system_text TEXT, user_text TEXT, updated_at)
              -- R39 §2「所有提示词可在程序内修改」；空串 = 该字段用默认（删行 = 恢复默认）
              -- 不塞 subjects.meta_json（那是学科元数据）
app_settings (key TEXT PK, value TEXT, updated_at)
              -- R39 §3 运行时设置（developer_mode 调试开关；审计本身**默认记录**，与开关无关）
-- Phase A 概念层（A2 已落地，docs/14 §1/§2.2）：
concepts     (subject_id, concept_id, label, aliases_json, created_at,
              PK(subject_id, concept_id))          -- 概念标签注册表（归一化 concept_id）
user_concepts(user_id, subject_id, concept_id,      -- 掌握证据挂 (subject, concept)
              evidence_json,  -- 提供证据的内容节点 id 列表（派生，非人工）
              mastered_at, updated_at, PK(user_id, subject_id, concept_id))
```

- **subject 命名空间迁移方案（Phase A A1 已落地，docs/14 §1/§5）**：学科注册 = 新增 `subjects` 表
  （math 为 kind=preset 预置学科，启动幂等注册；custom 由 API 创建）；大纲文档按
  `content/subjects/<subject_id>/outline.yaml` 持久（schema v1，整份重生成 revision+1 原子替换）；
  **现有关键表（nodes/edges/user_nodes/sessions/attempts/reviews）不加 subject 列**——既有 content 节点
  隐含归属 math（level 语义保留，零 ALTER 兼容现库），subject 归属由大纲 ↔ 内容 id 映射反查
  （自定义学科内容节点 id 强制 `<subject>.` 前缀，全局唯一）。概念层与 (subject, concept) 掌握证据
  为新增独立表（A2）。
- 迁移策略：MVP 用 SQLAlchemy `create_all`（新表自动创建）；表结构变化时人工写 `ALTER` 迁移脚本放 `backend/migrations/`（不上 alembic，但结构保持文档同步）。
- 并发：本地单机单用户，无并发问题；但仍建议 SQLite `WAL` 模式。

## 4. 错误码（约定）

| code | 含义 |
|---|---|
| `not_found` / `invalid_state` | 会话已结束或状态非法（前端应刷新会话）；`/session/start` 的 `invalid_state` = **越级进入未解锁节点（R18 总序门禁）**，detail 含前置提示 |
| `ai_unavailable` | LLM 降级已发生（响应中带 `degraded: true`） |
| `exercise_broken` | 模板不可渲染（应触发 content 告警，不计入用户失败） |
| `validation_error` | 入参格式错 |
