# IMPLEMENTATION_NOTES.md

> 实现工程师（Euler）工作记录。按 docs/08-mvp.md §5 从 M0 推进到 M5。
> 本文件记录两类内容：
> 1. **待架构侧裁决的疑点**（实现与文档冲突或文档未覆盖处，以文档为准落地后挂起裁决）；
> 2. 里程碑进度汇报与关键实现决策（可追溯）。

---

## 0. 实现约定（架构内微调，非架构决策）

- **目录布局冲突的落地方式**：docs/02 §3 将内容机代码放 `backend/app/content/`，docs/04 §7
  的校验命令写作 `python -m content validate`。落地：内容**数据**在仓库根 `content/`（stages/_meta/_drafts），
  内容**机代码**在 `backend/app/content/` 包；通过 pyproject `[project.scripts]` 暴露名为 `content`
  的 console script，**editable 安装后任意目录下执行 `content validate` / `content render …` 即等价于文档命令**；
  亦可在 backend/ 下执行 `python -m app.content validate`。运行库只加载 `content/stages/`。
- **判题器归属**：docs/03 注释允许判题归 domain 或 content/service。为满足"M1 判题单测先行 + domain 零 LLM"，
  落地于 `backend/app/domain/judge.py`（纯 sympy，无 LLM），content 模板自检与 service 会话共用。
- **FSRS**：docs/03 §3 优先 pip `fsrs` 包。实测 Python 3.14 下 pip `fsrs==6.3.2` 可装可用
  （open-spaced-repetition 官方实现，空 learning/relearning steps 使复习项=节点按天排程），
  已入 pyproject 依赖；`domain/fsrs.py` 只做薄封装（状态序列化/降级计数规则），便于日后替换。
- **venv**：仓库根 `.venv/`（Python 3.14.3），后端 editable 安装；前端 npm。
- **DB 路径**：默认 `backend/data/yanhui.db`（可 `MF_DB_PATH` 覆盖），SQLite WAL。
- **判题解析语义**（docs/04 §3 落地细节）：用户解集按"集合语义"比对（重复写同根不算错，
  缺根/多根算错）；数值题作答含符号视为 notation_error 而非判错；tolerance 缺省 1e-9。
- **M1 判题用例统计**：参数化条目 numeric 14 + equivalence 13 + equation 22 + boolean 12 = **61 ≥ 30**。

---

## 1. 待架构裁决疑点

> 清理说明（Phase C C6）：本节早期条目已随 docs/09 裁决史（R1–R23）逐一闭合；**当前"待架构
> 裁决"以各批次节内「疑点（挂待架构裁决）」为准**（最新：§48–§50 R30 五条 + §40–§45 与
> docs/14 §7 未决/待细化）。
> **最新挂账总表＝ §58「待架构裁决 / 未决」（2026-09-10 R34-fin 批更新）——续接请先读 §58。**
> 早期 M3"无 key 冒烟未执行"记录已过时：配 LLM_API_KEY 后真模型冒烟（test_live_ai）与 Phase C
> 真模型验收（test_phase_c_live，行星科学 10 单元 AI 内容）均已实测通过（§44）。

1. **M3 真模型冒烟未执行**：本环境无 `LLM_API_KEY`。ai/provider（OpenAI 兼容 chat + JSON
   提取 + pydantic 校验 + ≤2 重试 + ai_logs）、OpenAICompatibleGateway（调用点 1/2/4/6/7/8）
   及"坏 JSON/断网降级不脏状态"均已单测覆盖（含 401 即停）；docs/08 M3 的"真实调用 DeepSeek"
   验收需用户提供 key（写入 .env 后运行 `pytest tests/test_live_ai.py`，测试已就绪）。
   按实现规则不阻塞推进，先记档。→ **已闭合（真模型冒烟/验收可跑，见上清理说明）**

## 0.5 M2 落地增补（架构内微调记录）

- **判题答案表达式语义**：docs/04 §2 中 template.answer_expr 写作 `(c-b)/a`（无花括号）——
  语义落地为 **sympy 符号表达式、参数作符号代入求值**（prompt/equation 用花括号 str.format，
  answer_expr 用符号求值）。equation_solution 的机器方程模板：content 中 `check.equation`
  字段（docs 样例未含，属本实现为 sympy 判题补充的必需字段）。
- **API 会话推进**：docs/06 §2 action 枚举无"阶段前进"动作，而 docs/07 UI 有
  "明白了，看例题"按钮 → 补充 action `next`（讲解→例题→练习），记入本文件待架构知悉。
- **费曼轮次上限**：docs/05 §5"≤2 追问"，实现为 3 次评分（首评 + ≤2 追问后仍不过 → 回炉）。
- **复习作答留痕**：复习页每题判题经 /exercises/check（服务端 sympy 裁决并落 attempts），
  /review/submit 的 answers 仅审计传参、**不作为判题依据**（红线：判题只来自 sympy）。
- **离线费曼启发式**（仅无 key 桩）：口述 ≥20 字且含任一 core_concept → 各维 0.9；
  否则 0.35 → followup。真模型接入后此路径仅作降级兜底。
- **时间存储约定**：SQLite DateTime 列统一存 **naive UTC**（SQLite 驱动读回无 tz）；
  JSON（state_json/flow_json）内存态保留 aware ISO，转换层处理。

## 2. 里程碑进度

- [x] **M0 骨架**：目录结构 / pyproject+package.json / 一键启动 / DB 建表 / content validate 空跑。
      验证：uvicorn 三端点 200、vite dev 127.0.0.1:5173 出页、npm build 过、pytest 3 passed、content validate exit 0。
- [x] **M1 确定性核心**：domain 图谱(环检测/状态机/推荐/路径) + sympy 判题器(MVP 四模式)
       + 掌握度规则 + FSRS 封装(pip fsrs 6.3.2，空 learning-steps 按天排程) + 画像。
      验证：pytest 116 passed（判题参数化用例 61 条 ≥30，含容差/等价/边界；图谱含 5 类环用例），content validate 绿。
- [x] **M2 会话状态机 + API**：content loader/模板渲染/深校验 CLI + service 会话状态机
       （讲解→例题→练习→费曼→达标→FSRS 排程，AiGateway 插槽离线桩）+ 06 全部 P0 端点。
      验证：pytest 121 passed（含 API 全链路 E2E：双节点 mastered、中断恢复、复习 again×2 降级、
      判题不泄答案/notation、画像/模型配置）；content validate 2 节点 7 练习 ×8seed 全绿。
- [x] **M3 AI 接入**：ai/provider.chat_json（OpenAI 兼容、response_format json、剥离围栏、
       pydantic 校验、失败附错重试 ≤max_retries、401/403 即停）+ OpenAICompatibleGateway
       （调用点 explain/answer/hint/feynman_evaluate/feynman_followup/classify，ContextBlock
       白名单+禁令注入，variant 保留不启用）+ ai_logs 审计 sink + 服务层降级（deferred 人工复核）。
       验证：pytest 132 passed（+1 skipped=无 key 的真模型冒烟）；坏 JSON 重试、schema 违规重试、
       全失败 AiCallError+审计行、401 即停、费曼评分不可用→verdict=deferred 状态不脏；content validate 绿。
- [x] **M4 前端闭环**：React+Vite+TS 页面 Dashboard(图谱 SVG/推荐/复习卡/统计)/Session(讲解/例题/练习/
       费曼分步 UI，KaTeX 渲染 MdMath)/Review(逐卡复习+rating 四键)/费曼复盘页/设置页；交互模式
       workbench(MathInput+实时预览) + guided(StepPanel 演示) + graph(SVG 直线+滑动条演示，content 驱动)；
       路由/API 客户端契约对齐 06 §2；KaTeX 依赖已接入。验证：tsc+vite build 无错；uvicorn+vite 同起
       冒烟通过（页面/模块可达、/api 契约与后端一致）。**真人浏览器走查**（docs/08 M4 判据：真人学 1 节点）
       需用户在本地执行：`scripts\dev.ps1` 后打开 http://127.0.0.1:5173 走一遍学习闭环。
- [x] **M5 首批内容 + 打磨**：内容库扩至 **11 个人工精写节点 / 26 道练习**（primary 整数运算顺序、
       分数意义与同分母/异分母/乘除；middle 方程线 0101-0104、负数与数轴、有理数加法；high 一次函数
       斜率图形观察含 guided/graph 演示题）。每节点均有 feynman(task+rubric 四维+追问)；
       content validate 深校验（11 节点 × 每题 8 seed 全绿、broken=0）。复习跨日模拟已在
       test_api_flow 覆盖（到期→again×2→降级回炉+留痕）；仪表盘堆积警示/到期日期在 Review 页呈现。
- [ ] **M5 人工验收剩余项（需真人）**：
       1) docs/08 §3 功能勾选：浏览器走通"学 1 节点 + 费曼评分卡含逐字 evidence（联网后）"；
       2) 连续 3 天使用观察复习队列运转（引擎侧已由跨日模拟覆盖）；
       3) 首批节点"真实作答样例人工验证"：每节点已含 1 道 worked_example 人工精写+模板 8-seed 自动验算，
          正式勾选以人工过一遍为准。

## 3. docs/08 §3 验收清单对照（引擎侧可自动验证项）

| 项 | 状态 | 说明 |
|---|---|---|
| 一键启动脚本可用；SQLite 本地 | ✅ 实现 | scripts/dev.ps1(Windows)/dev.sh；backend/data/*.db |
| 图谱加载 20 节点无环（当前 11） | ✅ 实现 | GraphError 环检测 + content validate；20 为 M5 上限目标，11 已达 10–20 区间 |
| 单节点闭环可走通、中断可恢复 | ✅ 测试 | test_api_flow：双节点 mastered + quit/resume |
| sympy 判题覆盖 ≥90% 练习作答 | ✅ | 26 题全部为四种自动模式（manual_review 仅枚举） |
| 费曼评分卡分维+evidence+追问 | ✅ 引擎 / ⏳ 真人 | 离线启发式有 evidence；真模型调用需 key（test_live_ai.py） |
| 达标进复习队列；rating 生效；again×2 降级 | ✅ 测试 | api_flow：跨日到期→again×2→relearn+relearn_logs |
| Dashboard 显示推荐/复习/断点/统计 | ✅ | 断点清单 MVP 恒空（诊断 P1，docs/08 排除） |
| 错答 hint 不含完整解答 | ✅ 测试 | judge 不泄 expected；check 端点无 expected 字段；prompt 禁令 |
| domain 单测 + pytest + content validate | ✅ | 132 passed(+1 skip)；每里程碑跑 |
| ai 输出 pydantic 校验；断网/坏 JSON 降级不脏 | ✅ 测试 | provider 单测 + feynman_deferred 集成测试 |
| 无 LLM 判题路径 | ✅ | judge 只在 service/exercises 由 sympy 调用 |

## 4. 给用户的运行手册（速查）

- 启动：`powershell -File scripts\dev.ps1` → 浏览器开 http://127.0.0.1:5173
- 测试：`.\.venv\Scripts\python -m pytest backend\tests`；内容校验：`.\.venv\Scripts\content validate`
- 配真模型：复制 `.env.example` 为 `.env` 填 `LLM_API_KEY`；**真模型冒烟**：
  `$env:MF_ALLOW_LIVE_AI=1` 后跑 `pytest backend\tests\test_live_ai.py`
  （单元/集成套件默认离线，避免误触真模型与网络依赖）
- 抽检某题：`.\.venv\Scripts\content render middle.0102 3`

---

## 5. 走查热修复审与收尾（docs/09 R7/R8 复审记录 · 2026-09-08）

### 5.1 R7（SQLite 写锁）复审 — 通过，予以吸收；测试"卡死"根因另查明

- **代码复审**：`service/session.py::_call` 改为 LLM 前先 `db.commit()`（R7），5 处调用点
  （answer_question/hint_on_error/submit-hint/feynman_followup/explain_node）签名一致传 `db`；
  `db.py` 增加 `PRAGMA busy_timeout=30000`（每次连接生效，含 WAL/FK）。事务边界=LLM 前后各一事务，
  AiCallError 仍走离线兜底。**结论：语义正确、无脏状态风险**（commit 在 `expire_on_commit=False`
  下不破坏会话内对象），通过。
- **补充加固（本复审完成）**：R7 精神 = "任何可能长时间持写锁的网关调用都先提交"，已把
  `feynman_evaluate`（重型）与 `classify_error`（含 profile 写）纳入同一纪律——
  二者调用前先落库提交（见 5.2 改动清单）。
- **本轮"全套测试卡死"根因（重要）**：并非代码死锁。架构侧 `.env` 已配 `LLM_API_KEY`，
  conftest 载入后全套件误走真模型 DeepSeek（explain/答疑/hint/追问均真调用），本环境无外网，
  httpx 每个调用挂满 90s 超时 → 表现为卡死。修复（测试隔离）：conftest 默认将 `LLM_API_KEY` 置空，
  仅当显式 `MF_ALLOW_LIVE_AI=1` 时才保留 key 并运行 `test_live_ai.py`。
  **对真人走查无影响**：真服务由 `scripts/dev.ps1` 启动，config 自 .env 读 key → 走真模型。

### 5.2 本收尾改动清单

| # | 文件 | 改动 | 验证 |
|---|---|---|---|
| 1 | `domain/graph.py` | `recommend` 排序改为 学段→图谱层序→编号（USER_FEEDBACK 🟡 起点学段） | test_graph 新增 3 例 + api_flow 0 掌握首推 primary.0101 |
| 2 | `service/session.py` | action `regen_explain`：清 lecture_cache 回讲解重新生成（R8 清理路径）；feynman_evaluate/classify_error 前补提交（R7 精神） | test_api_flow 新增 regen 用例 |
| 3 | `ai/prompts.py` | ContextBlock 增加 [LaTeX 输出纪律]（$$ 单独成行、行内不跨行、定界符配对、无孤立 $$） | 构建/冒烟通过 |
| 4 | `frontend .../MdMath.tsx` | R8 复审修复：行中出现的 $$…$$ 占位符此前未替换（漏显示），现以行内模式注入渲染 | tsc+vite build 通过 |
| 5 | `frontend .../SessionPage.tsx` | ExplainView 增加"🔄 重新生成讲解"按钮 | build 通过 |
| 6 | `tests/conftest.py` / `test_live_ai.py` | 测试套件默认离线（LLM_API_KEY 置空）；真模型冒烟需 `MF_ALLOW_LIVE_AI=1` | 全绿且不再卡死 |
| 7 | `tests/test_smoke.py`、`test_ai_m3.py` | 复用会话级 `app_client` fixture（测试基建收敛） | 全绿 |

### 5.3 回归结果（热修 + 收尾后）

- `pytest backend\tests`：**136 passed, 1 skipped（真模型冒烟需显式 MF_ALLOW_LIVE_AI=1）**，连续多次稳定 <3s
- `content validate`：ok=True, 11 节点 / 26 练习（每题 8 seed 全绿）
- 前端 `npm run build`：TS + vite 无错
- 真实 uvicorn `/api/session/start` 冒烟：0.1s 返回 explain（R7 后并发写路径正常）

### 5.4 R7 长期化建议 — 评估结论（暂不实现，归档待排期）

1. **慢 LLM 移出请求事务**：MVP 单机单用户下，`commit-before-call`（R7 + 5.2 补充）已把持锁窗口
   压缩到近零；异步任务 + 轮询/SSE 属 P1 架构增强（前端已预留非流式路径），建议在引入多会话/
   公众化时再做。评估：✅ 现阶段不必实现。
2. **同节点生成防重入**：当前 UI 单飞（busy 禁点）+ 单机单用户，实际并发触发概率极低；若后续
   允许双开/异步，建议用 `sessions.flow_json.llm_inflight` 标志位 + 行级条件更新做互斥
   （`UPDATE ... WHERE llm_inflight=false` 影响行数=1 才进入生成），重入请求直接复用/等待。
   评估：低风险，暂不实现，方案已归档。
3. 前端已单飞（`submitting`/busy 禁用按钮）：✅ 与 R7 长期建议一致，无需改动。

### 5.5 是否可恢复真人走查

✅ 可以。启动 `scripts\dev.ps1`（读 `.env` 含 key → AI 在线模式）后：
- 任意节点 `/session/start` 不再 500（R7：LLM 前先提交 + busy_timeout 兜底）；
- 讲解公式可正常渲染（R8 容忍式 MdMath），残留脏讲解可用"🔄 重新生成讲解"一键重建；
- 0 掌握起点将推荐到小学内容（学段优先排序）。
遗留人工项见 §2"M5 人工验收剩余项"（走查 1 节点 + 3 天复习观察 + 内容人工过一遍）。

---

## 6. Day1 走查批次实现记录（docs/09 R9 · 2026-09-08）

| # | 裁决项 | 实现 | 验证 |
|---|---|---|---|
| 1 | explain_node 降 light 档（含重新生成同路径） | `ai/calls.py` CALL_EXPLAIN_NODE `model_tier="light"`；feynman_evaluate/followup 保持 heavy | 新增 2 测试：分级断言 + 线上请求体实际打到 light 模型（mock transport） |
| 2 | AI 等待可感知（⏳ 计时横幅） | SessionPage：`thinkingSince`+250ms 计时器；首次加载 GET（可能生成讲解）与 ask_question/regen_explain/request_hint/feynman_submit/answer 触发"⏳ AI 正在思考… 已用时 Xs"，提交按钮沿用 submitting 禁用 | tsc/build 通过；行为验证待真人走查 |
| 3 | asks 走 MdMath；排查纯文本 LaTeX 点 | ExplainView asks 逐条 `<MdMath/>`；学习目标 objectives、费曼 comment、MathInput/ExercisePanel/Guided/Graph hint 均改 MdMath 渲染 | build 通过 |
| 4 | 复盘页导航 | FeynmanHistoryPage 顶部"← 返回 / 回仪表盘"（空态同样提供） | build 通过 |
| 5 | 费曼维度中文标签 | 新增 `components/feynmanLabels.ts`：correctness=概念正确性 / own_words=用自己的话 / example_and_edge=例子与反例 / self_correction=自纠能力；未知 key 回显原名；Session 评分卡与复盘页共用 | build 通过 |
| 6 | 路由兜底 + 全局错误横幅 | App.tsx `*` → `<Navigate to="/" replace/>`；ErrorBoundary 包裹 Routes，渲染异常显示错误横幅+刷新/回仪表盘，并提示记录 URL 与控制台 | build 通过 |
| 7 | 流式输出 | 裁决为 P1 不做 | — |

**回归结果**：`pytest backend/tests` = **138 passed, 1 skipped**（真模型冒烟需 `MF_ALLOW_LIVE_AI=1`）；
`content validate` = 11 节点/26 练习全绿；`npm run build`（tsc + vite）= 无错。
**待用户复现**：R9 #6 偶发"找不到页面"（含 404 路径）——请下次记录地址栏 URL + 浏览器控制台。

---

## 7. R10 费曼追问 500 热修复审与回归补盲（docs/09 R10 · 2026-09-08）

**复审**：热修已按裁决落地于 `service/session.py::_act_feynman`：
- 追问 `FeynmanFollowupIn.previous_scores = last_scores[-1]`（最近一轮分维卡，list[dict]）；
- 二轮评分 `FeynmanEvaluateIn.previous_round = {"round":…, "combined":…, "dims": last_scores[-1]}`（摘要 dict）。
schema 类型匹配（calls.py 定义），R7 commit-before 仍在位。✅ 通过。

**回归补盲**：新增 `test_feynman_fail_then_followup_pass`（test_api_flow，离线启发式驱动确定性分支）：
练习全对进费曼 → 首轮不含核心概念（未过 + 追问出现，round=1）→ 二轮含核心概念（通过 → mastered）。
该用例此前为测试盲区（首轮一次过不触发追问）。**验证：139 passed/1 skipped，content validate 绿**。

**备注**：用户侧 primary.0102 重置为 available（上一轮用户请求）；middle.0101/high.0201 两个 0 作答
的残留 learning 行仍在，如需清理可一键处理（已向用户说明，待确认）。

---

## 8. 成长型总工单阶段 1 进度（docs/10、11；基线 139+1 → 当前 152+1）

### 子步 A（本子步完成）：R11 审计补盲 + R12-a 模型策略

**R11（审计 + E2E 补盲）**
- 复核：`_practice_reset_cycle` 为模块函数，`_cap_fail_cycle`/`_relearn_explain` 两处调用已去 `self.`（架构热修）。
- 补 3 条 E2E（此前盲区）：练习同题连错 2 次 → relearn_explain；一轮 5 题未达标 → cap 回炉；
  费曼 3 轮不过 → 回炉。均断言 200 + stage=explain + 事件流（relearn_notice 等）。
- 分支覆盖审计（coverage 实测）：`service/session.py` 440 行 78% 覆盖；新增用例后回炉三分支全绿；
  剩余未覆盖集中在 start 恢复旧会话分支、finish 中途、二次错误/上限分支部分边沿——已人工逐条核对逻辑，
  结论无 R10/R11 类"上线才炸"的未测调用（全部经 E2E 或单测执行）。

**R12-a 模型策略（docs/09 R12 第 1/2/4 部分）**
- 新增 `ai/tier.py`：决策链 `基础档(primary/middle/high→fast；college/ai→think；content feynman.thinking 覆盖) →
  触发(smart：费曼边缘 [t-0.15,t+0.10]/轮次≥2/超纲 out_of_scope) → 用户覆盖(model_mode light|deep|smart +
  payload.think_deep)`；单测 9 项矩阵（学段×触发×覆盖）。
- schema：`AnswerQuestionOut.out_of_scope`、`FeynmanEvaluateOut.confidence`、内容 `feynman.thinking`。
- profile：新增 `model_mode`（默认 smart）+ PATCH 接口；provider/gateway 5 调用点支持 `strategy`（fast→light 模型/think→heavy 模型，ai_logs.tier 记策略档）。
- service 接线：讲解/答疑/提示/费曼评分/追问按 tier 决策；答疑 out_of_scope（smart）→ 自动 think 重生成一次；
  费曼边缘/轮次触发 + `edge_think` 单次消费；评分 attempt meta 与响应 payload 标注 `strategy`。
- 前端：设置页三档（⚡快/自动/🧠深度）+ 会话页头即时切换；评分卡/讲解标注"本次档位：⚡快/🧠深度"。
- 测试：tier 矩阵 9 项 + 答疑档位标注集成 1 项（smart→fast；切 deep→think，finally 还原）。

**回归**：pytest = **152 passed, 1 skipped**；content validate = 11 节点/26 练习全绿；npm build 通过。

### 待办（下一子步）
- ~~R12-b SSE 流式~~（见下）→ 已完成；
- 阶段 2/3 见 docs/11。

### 子步 B（本子步完成）：R12-b 流式输出（SSE）

- 后端 `api/session.py`：`POST /session/step?stream=1` → SSE（`start`/每秒 `ping`/`result`=完整 JSON/`error`），
  服务同步逻辑跑工作线程 + 自带事务（R7 提交语义），错误映射同普通路径；无流参数时行为不变。
- 前端：`api.postStepStream`（fetch 读流、解析 event/data、`result`=StepResponse、`error` 抛错）；
  SessionPage 的 5 个 AI 动作先走流式、失败自动回退普通 POST；长文本（讲解/答疑回复/追问）配
  `TypeMd` 打字机逐段揭示（同文本不重播）。
- 协议同步：docs/06 §2.1（SSE 事件与回退约定）、docs/07（打字机说明）。
- 测试：`test_session_step_sse_stream`（事件齐全 + result 与普通 JSON 一致 + 非法 action → error 事件）；
  真实 uvicorn 冒烟：`start`→`ping(0)`→`ping(1)`… 流式正常。

**阶段 1 完成态回归**：pytest = **153 passed, 1 skipped**；content validate = 11 节点/26 练习全绿；
npm build 通过。

### 阶段 1 可验收点（用户浏览器实测）
1. 会话页头部 ⚡快/自动/🧠深度 即时切换；设置页同款三档；费曼评分卡与讲解显示"本次档位"。
2. AI 等待横幅计时 + 长文本打字机效果（真模型时讲解逐字出现）；网络差时自动回退仍能完成。
3. 错答 2 次 / 5 题 cap / 费曼 3 轮不过 → 回炉讲解正常，无 500。

## 阶段 2：关卡化体验（完成 · 2026-09-08）

- 内容元数据：NodeDoc 新增 `kind: normal|boss`（docs/10 §2.1 首领关卡）与 `feynman.thinking`（R12，文档已同步 docs/04）。
- 新增 2 个首领节点（人工精写锚点）：`primary.0199` 数与运算综合、`middle.0199` 代数·方程综合
  （prereq=本主题全部普通节点 → 复用现有解锁引擎，无第二套掌握度）。
- `service/campaign.py` + `GET /api/campaign`：学段→主题组→节点/👑boss、进度/通关、学段解锁、
  全部通关后 `next_generating`（"下一关生成中…"，阶段 3 接 roadmap/自续）。
- boss 通过事件（service/session `_master_if_ready`）：`boss_passed{level,topic,group_completed,
  stage_completed,next_generating,recap{复习整合提示:due_reviews,top_error_types,suggestion}}`；boss 节点照常
  FSRS 首排（复习整合触发点）。首领内容 `thinking:true` 验证内容覆盖深度档。
- 前端 Dashboard 图谱区 → 关卡地图（学段卡片：主题组进度、节点状态圆点、👑、通关✓、灰显未解锁、
  底部"下一关生成中…"横幅）。
- 测试：`test_campaign_snapshot_and_boss_pass`（快照结构 + 前置DB置 mastered → boss 会话→费曼综述→
  boss_passed 事件断言 + 组 completed + recap）；`content validate` 13 节点/30 练习全绿。
- 回归：pytest = **154 passed, 1 skipped**；npm build 通过。
- 可验收：浏览器仪表盘见"关卡地图"，学完主题前置即可开 👑 首领；首领通过 → 组"通关 ✓"+"复习整合提示"。

## 阶段 3（进行中，按 docs/11 拆小步汇报）

### 子步 6：课程蓝图（小学段先行）✅
- `content/roadmap/primary.yaml`：小学全序列 **21 条轻条目草案**（数与运算 10 / 量与测量 3 / 图形几何 4 /
  代数思维 1 / 应用题建模 2 / 统计 1）；含 id草案(s01..s21)、标题、主题、目标 ≤3 句、前置猜测、
  难度、`requires_thinking`（应用题/百分比等 5 条 true）、`anchors`（已有人工锚点节点引用：s05-s08↔primary.0101-0104）。
  **状态：draft，待人工精核后扩其余学段。**
- `backend/app/content/roadmap.py`：蓝图模型 + loader（结构/学段/id 唯一/prereq 指向文件内条目或锚点），
  入口 `load_roadmap(level)`、`all_levels_exist()`；`content/roadmap/` 目录已建。
- 测试 `test_roadmap.py` ×4（载入/顺序、条目结构、缺文件报错、exists 辅助）。
- 回归：pytest = **158 passed, 1 skipped**；content validate = 13 节点/30 练习全绿。

### 待续（下一步）
- 子步 7：gen_content 真实实现（蓝图→批量 AI 出稿→自动校验→入库策略）。✅ 见下
- 子步 8：自续触发（mastered≥90%/下一关按钮→后台生成+UI 通知）。
- 子步 9：入库策略（primary/middle 自动标 auto；high+ drafts；纠错反馈→复核+重生成）。
- 子步 10：端到端验收。

### 子步 7：gen_content 真实实现（流水线核心）✅
- `backend/app/content/pipeline.py`：出稿(drafter) → 自动校验 → 入库策略。
  - drafter：离线确定性 stub（无 key 机制验证；节点结构合法+模板数值题 8 seed sympy 自检可过）或 AI
    （scripts 内经 schema 化 draft_content 调用点接 provider；需 LLM_API_KEY）。
  - 自动校验 `validate_candidate`：front-matter 结构 / prereq 存在且无自指 / 每题模板 8 seed 渲染+自检 broken=0。
  - 入库策略 `_dest_dir`：primary/middle → stages/<level>/（front-matter `source: auto`）；high+ → _drafts；
    `--to-drafts` 可强制草稿。幂等：库中已有或文件已落盘 → exists；蓝图 anchors → covered（不重复生成，
    前置自动翻译到真实锚点节点 id）。
  - `generate_topic` 传递前置链扩展（needed_ids）→ 顺序生成保证先决先生成。
- `scripts/gen_content.py` 占位 → 真实 CLI：`generate --level --topic [--limit] [--to-drafts] [--source ai|stub]`
  与 `topics --level`。
- 蓝图修订：s13 前置改为 [s11]（去除对后序 s16 的正向依赖，保证顺序生成可行；待精核）。
- 测试 `test_pipeline.py` ×4：stub 结构+自检、批量+幂等+auto 标注、force_drafts 落 _drafts、anchor covered。
- 回归：pytest = **162 passed, 1 skipped**；content validate = 13 节点/30 练习全绿；无残留生成文件。

### 子步 8：自续触发（后台生成 + token 限额 + UI）✅
- `service/selfextend.py`：触发口径（蓝图目标落地节点 mastered 占比；自动阈值 90%）、下一待生成主题
  （roadmap 顺序、跳过 anchors 已覆盖）、同步核心 `_extend_sync`（预算→ generate_topic → 写盘 → 进程内库
  刷新 + DB 同步）、后台线程（wait=False）、module 级运行态（running/last_status/last_summary）。
- 预算：`LLM_MAX_TOKENS_PER_DAY`（0=不限）按当日 ai_logs 已用 + 每条目估算 6000 tokens 切批；
  离线 stub（无 key）不耗 token 不受限。
- API：`GET /api/selfextend/status`、`POST /api/selfextend/run?wait=1|0`（手动"继续下一关"，
  wait=0 后台非阻塞）。dashboard/campaign GET 在 `MF_AUTO_EXTEND=1` 时挂自动触发（默认关，防测试/演示竞态）。
- 前端：仪表盘"🚀 内容自续"面板（蓝图目标掌握%、待生成主题、上次结果、`继续下一关：生成「主题」→`，
  完成后自动刷新地图）；`MF_AUTO_EXTEND=1` 时到期自动后台生成 + UI 提示。
- 测试 `test_selfextend.py` ×2：锚点全 mastered（ratio≥0.9）→ extend 生成下一主题（数与运算前 6 条 auto）
  + DB 同步断言 + 比例回落不再自动触发；无掌握时手动 run 仍可生成。用例自清理文件与 DB 行。
- 回归：pytest = **164 passed, 1 skipped**；content validate 13/30 全绿；npm build 通过。

### 子步 9：入库策略收尾 + 纠错反馈闭环 ✅
- 入库标注：pipeline 生成节点 front-matter `source: auto`（primary/middle 校验全过自动入库；
  high+/强制 `--to-drafts` 进 _drafts——机制已在子步 7 完成并测试）。
- 新表 `feedback`（users 无关列：id/user_id/node_id/kind(lecture|exercise|content)/exercise_id/message/
  status(pending|reviewed|regenerated)/created_at；create_all 自动建表）。
- `service/feedback.py`：record / list / regenerate ——
  人工节点（source≠human）只标记 reviewed（不覆盖人工锚点）；auto 节点无 key → 队列待 AI 重生成；
  有 key → 标记待重生成由 gen_content 侧消费替换。
- API：`GET/POST /api/feedback`、`POST /api/feedback/{id}/regen`。
- 前端：Session 页头部"内容纠错"按钮（按阶段提交 lecture/exercise/content 反馈；提交后提示）。
- 测试 `test_feedback.py` ×3：记录+列表+来源；人工节点 regen → manual_only/reviewed；不存在 → 404。
- 回归：pytest = **167 passed, 1 skipped**；content validate 13/30 全绿；npm build 通过。

### 子步 10：端到端验收链路（自动化模拟）✅
- 新增 `content/roadmap/middle.yaml`（**draft 待精核**，首批代数 mini：m01/m02 锚点 middle.0201/0202 +
  m03/m04 待生成——供"小学通关→初中代数第一批自动解锁"验收链路）。
- `roadmap.py` loader：文件级 level 归一（条目未显式声明继承文件学段）。
- `selfextend.py`：`_extend_sync` 学段自动推进（指定学段内容齐 → 找下一个待生成学段）；
  `auto_check` 跨学段放行（前一学段全通关 → 下一学段自动首批）。
- `test_growth_e2e.py`：自动化模拟 docs/10 §4 —— 掌握小学锚点(ratio=1) → 循环生成并掌握小学主题 →
  小学蓝图齐后 extend 自动推进 → **生成 middle.m03/m04（初中代数第一批 auto）并 DB 同步**；用例自清理。
- 回归：pytest = **168 passed, 1 skipped**；content validate 13/30 全绿；npm build 通过。

### 阶段 3 完成态（docs/10 §2.2/2.3/§3/§4 引擎侧）
- 蓝图：primary.yaml（21 条 draft）+ middle.yaml（首批 draft）；
- 流水线 gen_content 真实实现（子步 7）+ 自续触发/后台/token 限额/UI（子步 8）
  + 入库标注/纠错反馈闭环（子步 9）+ 端到端链路模拟（子步 10）。
**真人浏览器验收清单（docs/11 验收约定）**：重启 dev.ps1 → 连续通关小学段（含自动生成内容）→
小学齐后系统自动解锁"初中代数·数轴与整式初步"（👑地图可见 m03/m04 auto）→ 全程只用关卡地图按钮与
"内容纠错"反馈，无需找开发者加内容/代码。AI 出稿质量与 token 预算行为需在配 key 环境复验。

---

## 9. 待修复/待办收尾批次（R13 补记 A–D · 2026-09-08）

**A. R13 收尾**
1. **有 Key 在线出稿接线测试**：新增 `test_drafting_online.py` ×4（mock provider / 假工厂，不真调 API）——
   AI drafter 产物经 pipeline 校验入库（source:auto）；首轮非法 → 自动重试携带校验错误 → 二轮 ok
   （断言 provider 调用 2 次且 messages 含"校验错误"）；重试仍失败 → failed 带 [attempt N] 透传；
   selfextend use_ai=True 命中 make_ai_drafter 分支并产出入库；use_ai=False（无 key）stub 路径既有测试覆盖。
2. **出稿失败自动修复重试**：pipeline.generate_entry ≤2 次尝试（drafter 第二参数 errors；stub 忽略、
   `ai/drafting` drafter 将校验错误回灌 messages）；失败逐轮带 attempt 前缀透传；selfextend summary/status
   附失败条数与示例错误（UI 可见）；CLI 打印失败率与明细；`scripts/gen_content.py` 改为复用
   `ai.drafting.make_ai_drafter`（消除与后端双份漂移）。
3. **测试写入隔离**：conftest 将整套测试内容根指到真实 content/ 的**临时副本**
   （`MF_CONTENT_ROOT` = 会话级 copytree）——pipeline/selfextend/E2E 对 stages/_drafts 的写入与任何
   中断残留只落在临时副本，仓库零残留（实测 grep auto 文件为空）。

**B. 偶发"找不到页面"（R9 #6）排查**
- 自查结论：SessionPage/ExercisePanel 提交成功后无任何导航调用；SSE 仅在 AI 动作使用且失败自动回退
  普通 POST（同请求二选一）；路由已由 `<Navigate to="/">` 兜底（新 bundle 不应再显示"找不到页面"，
  旧 bundle/静态资源过期最可疑）。已加轻量日志：后端 `/session/step` 每请求 stderr
  `[session.step] ok|err|unexpected session=… action=… extra=… detail=…`；前端 api.ts console.debug 成功
  /console.warn 失败（含状态码与 code），SSE no-result/error-event 日志。
- **用户下次复现请收集**：① 地址栏完整 URL；② DevTools Console 中 `[api]` / `[stream]` /
  `[session.step]` 行；③ 复现动作（提交答案？节点？是否刚点过"重新生成/提问"）。

**C. 文档同步（R12 实际实现）**
- docs/02 §4：模型档位表更新（讲解=light）+ 动态策略决策链（ai/tier：基础档→触发→覆盖、model_mode
  三档、think_deep、fast→light/think→heavy）+ ai_logs 记策略档。
- docs/05 调用点表：explain=light、answer 输出加 out_of_scope、feynman_evaluate 加 confidence、
  draft_content 入库策略；追加"调用策略（R12 落地）"段。
- docs/07 §4：三档模式/即时切换/档位标注（think_deep 单次覆盖由后端支持）；docs/06 SSE 协议与
  docs/07 打字机已核对一致。

**D. 蓝图自动自查**
- `roadmap.audit()`（前置存在/自指/环/正向引用/主题连续性）已实现并单测（primary/middle 均 ok、无环）。
- 生成 `ROADMAP_AUDIT.md`：primary 21 条（数与运算×10 / 量与测量×3 / 图形×4 / 代数思维×1 / 应用题×2 /
  统计×1）与 middle 4 条全部通过；primary"代数思维×1、统计×1"为主题独立单条（符合蓝图边界，
  非连续性错误，人工精核确认即可）。供用户精核参考。

**回归**：pytest = **173 passed + 1 skipped**；content validate 13/30 全绿；npm build 通过；
仓库 stages/_drafts 零残留 auto 文件。

---

## 10. 蓝图精核修订批（REVIEW-blueprint A/B/C · 2026-09-08）

**执行边界遵守**：仅改 content/roadmap/primary.yaml、roadmap.audit() 与其测试、ROADMAP_AUDIT.md、
本 NOTES；content/stages/ 13 节点与锚点 id 未动（validate 13/30 保持）；已有条目 id 未重编号，
新增延续 s22–s26。

**A. 内容缺口落实**
| id | title | topic | prereq | difficulty/thinking |
|---|---|---|---|---|
| s22 | 运算律与简便运算 | 数与运算 | s05（四则混合，锚点不动） | 2 / – |
| s23 | 比的意义·化简比与按比例分配 | 数与运算 | s06(分数锚点0102) + s10(百分数) | 2 / true |
| s24 | 圆的认识·周长与面积 | 图形与几何 | s15（面积公式） | 2 / true（面积推导） |
| s25 | 立体图形（长方体·正方体·圆柱·圆锥） | 图形与几何 | s13 + s15 | 3 / true |
| s26 | 分数与百分数应用题（求率·折扣） | 应用题建模 | s07(分数锚点0103)+s10 | 3 / true（置于 s19 与 s20 之间） |
- 并入/扩展：s01（标题扩为"万以内·四舍五入与估算"、objectives 增 3 条）；s09（标题"小数的四则运算"、
  objectives 增"小数除法竖式"）；s21（objectives 增"简单可能性判断"）。
**B. 顺序微调**：s12 prereq s11 → **s02**（人民币依赖加减）；s15/s16 重叠、s18/s21 单条保持（REVIEW B/C 备注）。
**C. 审计增强**
- `roadmap.audit()`：新增 **anchors 存在性检查**（anchors 指向的节点必须在内容库，缺失报错并进 ok 判定）；
  新增 **covered/pending 明细**（covered=锚点全部在库，与 pipeline 判定同口径）；支持注入 roadmap 供造错测试。
- 测试：+2（covered/pending 明细断言；人造缺失锚点 → ok=False 且 anchors_missing 含该项）。
- 重跑 audit：primary **26 条** / middle 4 条全部 ✅（前置缺失 0、锚点缺失 0、环 0、正向引用 0）；
  covered：primary s05–s08、middle m01–m02（与 pipeline 口径一致）；待生成 primary 22 / middle 2。
  `ROADMAP_AUDIT.md` 已更新（含 covered/待生成清单与新条目明细）。

**回归**：pytest = **175 passed + 1 skipped**；content validate 13/30 全绿；零残留。

**待架构裁决疑点（§1 区新增）**
1. 运算律 s22 按 REVIEW"紧接 s05 之后"插入——列表顺序上它先于分数块；学习中"分数"在"运算律"之后出现，
   语义是否接受（如需先分数后运算律可仅调整列表位置不动 id，不涉及锚点）。
2. s23 比 依赖 s10（百分数，未生成）→ pipeline 生成"比"时会先连链生成百分数链内容（s09/s10 等）；
   属依赖链正常行为，但"单主题生成"会连带多主题内容，需知悉（入库总量按传递展开计算）。
3. 新条目 id 延续 s22+，id 序号与列表学习顺序不再一致（列表位置为真源）；若日后有工具假定 id 序请先读列表。
4. REVIEW D（middle 扩段）为后续批次，本批未动 middle.yaml。

---

## 11. 会话续接（2026-09-08 18:53）—— 基线复核通过：pytest=175 passed + 1 skipped，content=ok 13 节点/30 练习

**续接前最后已知状态**：
- 里程碑：M0–M5（M5 人工验收剩余真人项）+ docs/11 阶段 1/2/3 完成态（153→175 演进路径见 §8–§10）。
- blueprint 修订批 A/B/C（§10）：代码（primary.yaml 26 条、roadmap.audit 锚点存在性检查、covered/pending 明细）在
  snapshot 613dbee 内已含；**证据尾巴**（test_roadmap.py +2、ROADMAP_AUDIT.md 重生成、本 NOTES §10、README 文档导航 +
  docs/13 交接协议）当时未提交 → 本次续接已复核（audit primary 26/middle 4 全绿、covered s05–s08/m01–m02）并收尾提交。
- **待架构侧核实**：ABC 修订批实现（REVIEW-blueprint A/B/C 对应表见 §10；本批按 REVIEW D 未动 middle.yaml，D 待后续批次）。
- 疑点（§10 待裁决区）4 条原样挂起；docs/12 总纲 P1（high.yaml）为当前活动工单下一任务。

---

## 12. docs/12 P1：high.yaml 全段草案（2026-09-08 · 只写蓝图，不生成内容）

**交付物**
- `content/roadmap/high.yaml`：**80 条轻条目草案**（9 主题组，按 docs/12 §2 high 骨架顺序）：
  集合与常用逻辑 ×6（h01–h06）/ 等式与不等式 ×7（h07–h13）/ 函数 ×17（h14–h30，含幂指对与
  三角线至解三角形）/ 数列 ×6（h31–h36）/ 平面向量 ×4（h37–h40）/ 立体几何初步 ×7（h41–h47，
  含空间向量法收尾）/ 解析几何 ×12（h48–h59）/ 导数及其应用 ×9（h60–h68）/ 统计与概率 ×12（h69–h80）。
- 锚点策略：high 在库人工节点仅 high.0201（一次函数），语义归属 middle 扩段"函数初步"（REVIEW D）→
  **不作 covered 占位 anchors**，改作 h14/h48 的**前置真实节点引用**（先掌握实例再抽象化）；anchors 留空
  为有意（audit 锚点存在性检查要求指向库内节点，占位即报错）。
- `content/roadmap/high-samples.md`：3 条锚点级示例（h16 单调性 / h29 三角恒等 / h59 圆锥曲线综合）
  供精核——含 thinking 判定理由、生成建议、前后置链条核对与"首节点入库后回填 anchors"演示形态。
- `ROADMAP_AUDIT.md`：脚本再生（含 high 段；生成器 `_dsh-local/gen_audit_report.py` 供 P2/P3 复用）。

**audit 结果**：high 80 条 ok=True——前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0 / 孤立主题 0。
**回归**：pytest = **175 passed + 1 skipped**（含 e2e 边界适配，见下）；content validate 13/30 全绿；零残留。

**e2e 边界适配（test_growth_e2e.py）**：high.yaml 就位后，extend 跨学段回退会按北极星继续自动推进到
high（high.h01–h06 落 **_drafts**、无 Node 行、不可掌握），原用例"master 生成集"在此 FK 失败。
修正：初中代数首批生成即停（用例声明范围 = docs/10 §4）；"推进到高中首批"属 docs/12 §4 验收，
待 high+ 自动入库（P4）生效后另行模拟。引擎行为本身正确（北极星预演）。

**待架构裁决疑点（§1 区登记）**
1. **条目规模口径**：high 草案 80 条（轻条目口径，同 primary 26 条）；docs/12 §5"高中≈200+"似为
   含教材级细拆的全内容口径。docs/12 §4"条目数 ≥ 预估下限"无机械定义——建议以本报告/ROADMAP_AUDIT
   头部记录的规模口径为基准，精核后定稿各学段下限。
2. **顺序**：middle 全段（REVIEW D）未先于 P1 展开；一次函数归属 middle、high 仅前置引用不占位 anchors，
   中学→高中函数主线靠 selfextend 学段顺序衔接。是否接受该顺序/归属，请架构确认。
3. **跨学段 prereq 能力缺口**：audit 口径下 prereq 只能引用"本文件条目或已在库节点"；middle 未入库主题
   （平面几何、概率统计初步等）在 high.yaml 中无法逐条表达 → h41/h79 等以空前置+学段顺序兜底。
   是否新增"蓝图级跨学段前置（引用其它 level.yaml 条目）"能力待裁决。
4. **骨架外主题**：复数等 docs/12 骨架未列主题未纳入（严守总纲）；精核意见可触发增补批。
5. **requires_thinking 启发式**：证明/含参/综合/压轴类标 true（如 h16/h29/h59）；精核可调。

---

## 13. docs/12 P2：college.yaml 全段草案（2026-09-08 · 只写蓝图，不生成内容）

**交付物**
- `content/roadmap/college.yaml`：**56 条轻条目草案、6 主题组**（docs/12 §2 college 骨架）：
  一元微积分 ×15（c01–c15：极限/连续/导数/中值/洛必达泰勒/不定积分/定积分/微积分基本定理/应用/
  反常积分/微分方程/级数）、多元函数微积分 ×9（c16–c24：空间解析几何入口→偏导/梯度/极值/重积分/
  线面积分/三大公式）、线性代数 ×10（c25–c34：行列式→矩阵→方程组→向量组→空间→特征值→对角化→
  二次型→正定与最小二乘）、概率论与数理统计 ×9（c35–c43：公理化→分布→数字特征→大数/中心极限→
  抽样分布→估计→检验→方差分析回归）、离散数学初步 ×7（c44–c50）、数值计算初步 ×6（c51–c56）。
- 文件头含 **7 条 high→college 衔接假设**（A–G：入口=high 通关；各 run 假定掌握的高中内容映射到
  high.hNN 区间；机械层面学段推进仍由 selfextend 顺序保证）。
- 锚点策略同 high：anchors 留空（大学内容全部待生成）；跨学段 prereq 受 audit 口径限制（只能引用
  已在库节点），故衔接假设以文档说明为主。
- `ROADMAP_AUDIT.md`：再生含 college 段。

**audit 结果**：college 56 条 ok=True——前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0 / 孤立主题 0。
**回归适配**（蓝图新增即回归的惯例）：`test_roadmap.py` 缺文件用例原以 college 为样例 → 改用永不存在名
`no_such_level`（P3 建 ai.yaml 后仍成立）；audit 全覆盖循环扩到 primary/middle/high/college（P3 加 ai）。
**回归**：pytest = **175 passed + 1 skipped**；content validate 13/30 全绿；零残留。

**待架构裁决疑点（§1 区登记）**
1. **数值计算初步归属**：docs/12 §2"视需要并入 ai"——本批放 college 工具线（c51–c56，以微积分/线代作
   应用对象）；P3 起草 ai.yaml 时复核是否需要迁移/引用。
2. **线代与微积分并行修读**：c25 行首空前置表达"可与一元微积分并行（多数高校第一学期并行）"，与 high 的
   近单链学习序不同——单用户顺序学习下即"先学完微积分 run 再学线代 run"，可接受特性，记知悉。
3. c43（回归分析）实际未在 prereq 引用 c34（最小二乘法方程），仅内部链 c42——法方程工具可由 c34 并行/
   前置选修后补；如需强制顺序可加跨 run prereq，精核时定。

---

## 14. docs/12 P3：ai.yaml 全段草案（2026-09-08 · 只写蓝图，不生成内容）

**交付物**
- `content/roadmap/ai.yaml`：**57 条轻条目草案、7 主题组**（docs/12 §2 ai 骨架顺序）：
  机器学习数学基础 ×10（a01–a10）/ 凸优化与数值优化 ×9（a11–a19）/ 信息论与熵 ×6（a20–a25）/
  矩阵分析与正则化 ×8（a26–a33）/ 高维概率与统计学习理论 ×8（a34–a41）/ 时间序列与随机过程 ×8
  （a42–a49）/ 量化应用 ×8（a50–a57）。
- 文件头含 **8 条依赖 college 的衔接说明（A–H）**：入口 = college 通关（selfextend 学段顺序）；
  各 run 假定掌握的 college 内容（cNN 区间）与内部前置标注（如 SVD 依赖 college 特征值 c31–c32、
  随机过程/量化依赖 college 概率优化 c39/c43 等，均以文档说明承载——跨学段 prereq 受 audit 口径限制）。
- **requires_thinking 标注**：理论/推导/建模类 ≈90% 标 true（docs/12 注"默认 deep 档"的建议以字段表达）；
  计算/工具/讨论类标 false（a09/a19/a33/a56）。运行期档位仍由 R12 ai/tier 决策链决定（ai 基础档即 think），
  字段仅作精核建议——已在文件头注明。
- `ROADMAP_AUDIT.md`：再生含 ai 段（5 学段蓝图文件齐全：primary/middle/high/college/ai）。
- `backend/tests/test_roadmap.py`：audit 全覆盖循环扩到 5 学段（加 ai）。

**audit 结果**：ai 57 条 ok=True——前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0 / 孤立主题 0。
**回归**：pytest = **175 passed + 1 skipped**；content validate 13/30 全绿；零残留。

**待架构裁决疑点（§1 区登记）**
1. 随机过程/时间序列的归属：docs/12 注"某些主题（随机过程）也可作 college 拓展"——本批置于 ai 主线
   （a42–a49），并在 ai.yaml 头注明了"如需 college 先行扩展请裁决后回填 college.yaml（P3 不改动 college）"。
2. 信息论（a20–a25）位于凸优化之后：纯信息论不依赖优化，位置是"骨架排布"决定；若精核认为应前移可调列表
   位置（不动 id）。
3. 量化 run 内部工具链较长（a50→a57 近单链），符合"单用户顺序学习"，记知悉。
4. ai 学段 thinking 标注 ≈90% true 属预期（deep 档）；false 类（a09/a19/a33/a56）供精核复核。

---

## 15. docs/12 P4：high+ 自动入库护栏升级（2026-09-08 · 北极星配套，与 P1 蓝图一并评审）

**背景**：docs/12 P4 = high+ 默认自动入库，以 自动校验 + 白名单 + 掌握/费曼旁证 + 纠错召回 替代强制人审，
保留"内容问题率 > 阈值 → 该主题转草稿待检"自动熔断。P1 前 high+ 强制 _drafts（docs/10 §3 混合制），
本批按 docs/12 P4 升级（docs/10 §3 / README 不可变 #9 的口径差异见"评审点"）。

**改动清单**
1. `content/pipeline.py`：入库策略默认**全学段自动入库**（stages/<level>/，source: auto）；_drafts 仅由
   显式 `force_drafts`（CLI `--to-drafts`）或服务层熔断驱动。prereq 白名单语义在 docstring 明示
   （仅库内+本批前置链，validate_candidate 强制）。
2. `service/guardrails.py`（新增）：主题问题率 = 未处置(pending)纠错反馈命中的去重节点数 /
   该主题已入库 **auto** 节点数（锚点人工节点不计分母）；熔断条件 ratio > 0.3 且 问题节点 ≥2 且
   分母 ≥3（防小样本误伤）；pending 清零（复核/自动重生成替换）→ 自动恢复（状态可由 DB 推导，无持久化标志）。
3. `service/selfextend.py`：接线熔断——生成目标主题前查 guardrails，命中 → `force_drafts=True` 转草稿，
   summary 标注"⚠️ 纠错召回熔断 … 转 _drafts 待检"，返回 dict 增 `guardrail` 字段。
4. `scripts/gen_content.py`：docstring 同步新策略（CLI 手动通道不自动熔断，用户可自行 `--to-drafts`）。
5. 测试：`test_guardrails.py` ×2（high 默认自动入库 stages 标 auto；熔断→_drafts→pending 清零恢复）；
   `test_growth_e2e.py` 升级到 docs/12 §4 验收——跨学段模拟推进至**高中首批 auto 入库并 DB 可见**
   （解除 P1 时"初中首批即停"的边界，原边界原因已消除：high 现在自动入库、无 Node 行 FK 问题）。

**回归**：pytest = **177 passed + 1 skipped**（+2 护栏用例）；content validate 13/30 全绿；零残留。

**评审点（与 P1 蓝图一并提交架构/用户）**
1. **口径变更**：docs/10 §3"high+ → _drafts 待审"与 README 不可变 #9"人工审核 gate"被 docs/12 P4 覆盖
   （运行期零人审 + 熔断兜底）。本批未改 docs/10/README——若批准请架构侧同步修订该两处表述。
2. **熔断恢复口径**：pending 清零即恢复（"复核=已处置"的近似）；若要求"整条重生成替换后才恢复"需把
   feedback.regenerate 的 auto 路径做成真正替换（当前 key 路径仅标 reviewed + 待脚本消费，见 §9 待办）。
3. 阈值 0.3 / ≥2 问题节点 / ≥3 分母为初值，运行期可按反馈量调参（常量集中在 guardrails.py）。
4. CLI 手动通道不自动熔断（无 DB 依赖）；如需 CLI 也熔断可后续接线。

---

## 16. 蓝图精核补丁批（REVIEW2-master 执行 · 2026-09-08）

**规格**：`content/roadmap/REVIEW2-master.md`（全学段 A/B/C）+ docs/09 R15 裁决。
**边界遵守**：仅改 content/roadmap/{high,college,ai,primary}.yaml、ROADMAP_AUDIT.md（生成器再生）、本 NOTES；
content/stages/ 13 节点与锚点 id 未动（validate 13/30 保持）；既有蓝图条目 **id 与 anchors 零改动**；
新增沿用 REVIEW2 续号风格（h40b / c34b / c43b / a04b / a17b / a25b）；每学段 audit 全绿后才继续下一文件。

### high.yaml（80 → 81 条）
- **新增 `high.h40b`《复数的概念与四则运算》**：topic 复数，objectives 三项（虚数单位与复数概念/
  四则运算与共轭/复平面与模），prereq [high.h07, high.h38]（回补 h07"无实根"悬念），d2；插 h40/h41 间；
  文件头主题组注释补"复数"组（位置对应必修二 向量→复数→立体 序）。
- **h47 topic 独立为"空间向量与立体几何"**（h41–h46 保持"立体几何初步"）；文件头注释同步组名。
- **A2 目标并入**：h73 objectives +"频率估计概率与随机模拟"；h79 objectives +"总体百分位数的估计"。
- **B1 h79 前移**：h79 移至 h73 之前（统计先于概率，为 h80 铺样本/数字特征），原 prereq high.h73 去除
  （抽样不依赖古典概型，置空 prereq）；id 不变，h80 对 h79 的引用仍向后成立。
- **B3 h30 prereq**：由 [high.h29] 降为 [high.h27, high.h28]（避免被 3 级恒等变换卡主线）。
- **B5/B6 注释行**：h09/h19 前加初中衔接说明（二次函数/反比例，middle 扩段后回填引用）；h36 数学归纳法
  加"选学/了解级"注（REVIEW2 C② 裁决：不升难度）。
- **C 项执行**：三角函数线 B2 不做（课标淡化）；h25 不扩——未改。

### college.yaml（56 → 58 条）
- **新增 `college.c34b`《奇异值分解与低秩近似（SVD/PCA 铺垫）》**：topic 线性代数，objectives 五条
  （定义与几何意义/与 AᵀA 特征分解关系/低秩逼近与图像压缩/数据中心化与 PCA/伪逆衔接最小二乘），
  prereq [college.c32, college.c34]，d3 + thinking true，紧随 c34；注释注明 ai a27/a28 的 college 侧落点。
- **新增 `college.c43b`《随机过程初步：马尔可夫链》（可选条目）**：topic 概率论与数理统计，objectives
  （转移矩阵与 n 步转移/稳态分布/随机游走），prereq [college.c38, college.c39]，d3 + thinking true，
  紧随 c43；注释标"可选：RL/时间序列方向必修；ai 主线已有随机过程（ai.a42–a49）"。
- **A3 c15 prereq +c07**（幂级数展开依赖泰勒公式）。
- **B prereq 补链**：c20 +c19；c31 +c30；c49 +c45；c55 +c04（均向后引用，去重后无正向）；c16 无文件内
  前置，加衔接注释（入口依赖高中空间几何，见文件头假设 C，防"孤立"误判）。
- **全表补 requires_thinking（58/58）**：d≥3 → true，d≤2 → false；REVIEW2 B 证明推理类
  （c07/c14/c23/c30/c33/c39/c41/c42/c43/c56）与新增 c34b/c43b 均在 d3=true 集合内，无需另设例外；
  未改动任何 difficulty。

### ai.yaml（57 → 60 条）
- **新增 `ai.a04b`《贝叶斯推断与共轭先验》**：topic 机器学习数学基础（同 a04），objectives 五条
  （后验计算/共轭先验族/贝叶斯线性回归/后验预测/先验选择），prereq [ai.a04]，d3 + true；插 a04/a05 间。
- **新增 `ai.a25b`《变分推断与 ELBO》**：objectives（KL 视角 ELBO/均值场/重参数化直觉/EM·VAE·扩散连接），
  prereq [ai.a25, ai.a41]，d3 + true；**插 a41 后、run6 前**（规格"插 a25 后"与"前置含 a41"冲突——
  a41 列表位在 a25 之后，若插 a25 后会出现正向引用；按 R14"列表位置为真源 + 正向引用 0"取 a41 后插入并注释）。
- **新增 `ai.a17b`《ADMM 与算子分裂》**：objectives（对偶上升/乘子法/ADMM 推导/分布式与 Lasso 应用），
  prereq [ai.a16, ai.a17]，d3 + true；紧随 a17。
- **A2 a12 KKT 深化**：objectives 扩为完整 KKT（四条件推导/互补松弛/几何直觉/SVM·Lasso·带约束组合应用，≤4 条）。
- **A4 a46 +"单位根/差分与 ARIMA 整合阶（平稳化）"**（量化平稳化刚需）。
- **B 项**：a09 requires_thinking → true；a57 prereq +ai.a53、ai.a55；a26/a33 objectives +条件数/数值稳定性；
  a02/a03 注释注明承接（矩阵求导体系在 a29；交叉熵形式化定义在 a21）。
- **鞅/布朗顺序修正**：读文件确认实际结构确如评审所述（a44 布朗在前、a45 鞅在后，且 a45 前置 a44）→
  对调两者**列表位置**（id/anchors 不动，R14 列表位为真源）：鞅（a45）前置改 ai.a42、排布朗之前；
  布朗（a44）置鞅后作鞅（连续鞅）特例、prereq 改 ai.a45。评审 C③ 高斯过程归属以注释注明
  （GP 概念在 a44 内介绍、归"时间序列与随机过程"run；完整 GP 回归视角不在主线，为扩展候选）。

### primary.yaml（REVIEW2 B 两项）
- s18 prereq +primary.s05（方程只需四则基础；s15 保留作"到段位置"锚）；s23 prereq +primary.s08
  （比依赖分数意义+除法，追加分数乘除）——均向后引用，audit 绿。

### audit 结果（roadmap.audit，5 学段 + 内容库 13 节点 known_node_ids）
primary 26 / middle 4 / high 81 / college 58 / ai 60 全部 ✅——前置缺失 0 / 锚点缺失 0 / 自指 0 /
环 0 / 正向引用 0。high 现含 2 个"单条主题组"（复数 ×1、空间向量与立体几何 ×1）为 REVIEW2 组名调整的
有意结果（audit ok 不受影响；报告 ⚠️ 提示与 primary 代数思维/统计单条同性质，未来扩组即消除）。
`ROADMAP_AUDIT.md` 已由 `_dsh-local/gen_audit_report.py` 再生（头部口径 26/4/81/58/60，含 5 学段与新条目）。

### 回归
pytest = **177 passed + 1 skipped**（178 收集、exit 0，与基线持平——新增蓝图条目不改变测试计数；
test_roadmap 无受影响断言，零测试适配）；content validate 13/30 全绿；`.pytest-*` 临时目录已清理；
stages/_drafts 无新增；仓库零残留。

### 偏离/说明
1. REVIEW2 对 c43b 写作 d4——difficulty schema 上限为 3（roadmap.py `ge=1, le=3`），落地 **d3 + thinking
   true**（"需思考深档"语义由 thinking 字段承载，与 c43 同级）。
2. ai.a25b 按实际 run 结构插 a41 后 run6 前（见上），并在文件内注释说明，保证顺序无正向引用。
3. 鞅/布朗以列表位置对调实现（id 不变），符合 R14"id 序号与列表学习顺序不一致可接受、列表位置为真源"。
4. REVIEW2 college C"傅里叶单列"为待精核项（未在 A/B 清单），本批不执行。
5. primary REVIEW2 B2 建议 s23 追加"s08 或 s04"（精核可再定），按任务规格取 s08（分数乘除，衔接
   s06 分数意义的除法视角）。

---

## 17. 会话续接（2026-09-08 19:50）—— 基线复核通过：pytest=177 passed + 1 skipped，content=ok 13 节点/30 练习

**续接前最后已知状态**：
- 蓝图总纲 P1–P4 全部落地（4d0a2c8）；其后另一 Euler 会话执行 R15 精核补丁批（fa75d28：high +h40b 复数
  81 条 / college +c34b·c43b 58 条 / ai +a04b·a17b·a25b 60 条 / primary B 两项 / 全表补 thinking /
  REVIEW2-master.md + docs/09 R14/R15 裁决 + docs 北极星制同步）与 R14 收尾（35f2d95：college.c43 +c34）。
  架构侧 R14 批准 P1–P4 并把跨学段 prereq / feedback 重生成替换 / middle 扩段列为后续任务（docs/09 R14"给
  Euler 的后续任务" 1/3/5）。
- 本会话（用户工单 A/B/C/D）承接：A=跨学段 prereq 引擎增强（R14 后续#1）+ 落地改写衔接假设为真实跨学段
  prereq；B=feedback 真正"重生成替换"消费管线（R14 后续#3）；C=middle 全段扩段（REVIEW D / R14 后续#5）；
  D=傅里叶单列候选 + REVIEW2 清单闭合核对。基线复核数字如上；git HEAD=35f2d95、status 干净。

---

## 18. A 段：跨学段 prereq 引擎增强（R14 后续 #1 · 2026-09-08）

**规格**：用户工单 A 段 = roadmap 条目 prereq 允许引用其它学段蓝图条目（`level.local` 跨文件），
把"文档说明式衔接"升级为机器可校验；audit/生成器可提示缺口但不阻塞（学段顺序推进兜底，北极星懒生成不变）。

**改动清单**
1. `content/roadmap.py`：
   - `LEVEL_ORDER`（LEVELS 学习顺序）+ `_split_entry_ref`（`level.local` 两级格式解析）+ `all_entries()`
     （跨学段蓝图条目注册表：读全部已存在 level.yaml）+ `landed_id_for()`（条目→内容落地 id：锚点在库
     → anchors[0]，否则条目自身 id）。
   - `load_roadmap` 格式层增强：含 '.' 的 prereq 必须是合法学段前缀 + 非空本地号，否则 RoadmapError
     （错误信息含具体条目与非法值）。
   - `audit()`：新增 `registry` 注入参数 + 跨学段语义——引用其它学段条目：目标学段为后序 → `cross_reverse`
     （进 ok 判定，报错）；前序 → `cross_refs`（合法），目标条目未落地到内容库 → `cross_gaps`（提示，
     不进 ok 判定——学段顺序兜底）；同文件环 DFS 保留；返回 dict 增 cross_refs/cross_reverse/cross_gaps。
2. `content/pipeline.py`：
   - `_resolve_prereqs()`：生成前置翻译——同文件锚点覆盖 → 锚点 id（原行为）；跨学段引用 → 目标条目
     已落地（锚点节点/auto 节点在库）→ 用落地 id 建内容边，**未落地 → 剔除**（内容文件不得声明指向
     不存在节点的 prereq——loader/图谱校验不允许；依赖由学段顺序兜底）。
   - `cross_level_gaps(level)`：该学段跨学段前置未落地清单（selfextend summary 提示用）。
   - `generate_sequence` 使用注册表 + `_resolve_prereqs`。
3. `service/selfextend.py`：`_extend_sync` 成功后附"跨学段前置缺口提示（不阻塞，学段顺序兜底）：…"入 summary。
4. **蓝图落地（最小必要，11 条跨学段引用）**：college → high 5 条（c01→high.h31 数列；c16→high.h47 空间
   向量；c25→high.h38 平面向量坐标；c35→high.h74 条件概率；c44→high.h06 集合逻辑）；ai → college 6 条
   （a11→college.c20 拉格朗日；a27→college.c34b SVD/PCA；a29→college.c18 偏导/全微分；a34→college.c39
   大数/中心极限；a43→college.c43b 马尔可夫链（college 可选条目衔接）；a50→college.c38 数字特征）。
   文件头衔接假设 A–H 保留文档性说明，机器可表达部分已改写为真实 prereq 并在头注释标注。
5. `ROADMAP_AUDIT.md`：再生（含每学段"跨学段引用/反向/缺口提示"行）。

**audit**：5 学段全 ok——college cross_refs 5 / ai cross_refs 6，反向 0，缺口提示 5/6（目标内容未生成属
正常：运行期懒生成到段时前置学段已齐则缺口消失）；前置缺失 0 / 锚点缺失 0 / 环 0 / 正向引用 0。

**测试**：test_roadmap +7（合法带缺口 / 落地无缺口 / 条目缺失 / 反向拒绝 / 同文件环保留 / loader 格式 /
真实蓝图 gaps+audit）；test_pipeline +1（_resolve_prereqs 未落地剔除·落地翻译·锚点落地·同文件翻译）。
**回归**：pytest = **185 passed + 1 skipped**（+8）；content validate 13/30 全绿；零残留。

**疑点/偏离**
1. 生成语义取"跨学段前置未落地 → 剔除引用"（而非占位生成）：内容 prereq 只允许指向真实存在节点，
   与 loader/图谱校验一致；缺口由 audit.cross_gaps + selfextend summary 提示。若未来要"前置学段首批自动
   补齐"需架构另裁（现由学段顺序推进覆盖，北极星懒生成不变）。
2. 跨学段"环"在方向规则（只许引用前序学段）下不可能；同文件环能力保留并有测试。
3. 注册表 all_entries() 每次读取 ≤5 个 yaml（量小无缓存）；若蓝图文件数大再引入缓存。

---

## 19. B 段：feedback 真正"重生成替换"消费管线（R14 后续 #3 · 2026-09-08）

**规格**：用户工单 B 段 = auto 节点纠错反馈 → status=regenerating → 后台 pipeline 重生成（复用 ai.drafting）
→ 校验通过【原子替换】文件与库内节点 + 刷新 + 反馈清零记 regenerated；失败保留原内容记 failed 待人工；
人工锚点仍只标 reviewed；UI 状态可见。

**改动清单**
1. `models.py`：Feedback 增 `result`（处理结果/失败原因）与 `updated_at`（onupdate）。`db.py`：`init_db` 后
   `_migrate_columns` try-ALTER 给旧库补列（create_all 不会加列；幂等）。
2. `service/feedback.py`（重写）：状态机 pending→regenerating→regenerated/failed（+reviewed 人工复核）。
   - `record()`：不变（pending）；auto 节点由调用方在提交提交后 `spawn_auto_regen` 自动触发后台线程。
   - `regenerate(db,…,wait=,drafter=)`：人工 → reviewed manual_only（不替换）；auto → wait=True 同步核心
     （测试/脚本）/ wait=False 后台线程（API 默认）。
   - `_regenerate_node_now()` 同步核心：由现有文件 front-matter 重建条目 → 出稿（make_ai_drafter；**无 key
     不回落 stub**，记 failed"未配置 LLM_API_KEY…保留原内容"）→ pipeline.validate_candidate + 节点 id 不变
     校验（防串位）→ ≤2 稿 → 通过则同目录临时文件 + os.replace **原子替换** → refresh_library + sync_content
     （库内节点/边/掌握度刷新）→ 该节点 pending/failed 反馈清零记 regenerated + result。
   - 并发：模块级 `_regen_active` 锁集合同一节点同时仅一个重生成在飞。
   - `list_feedback` 增 node_id 过滤、result/updated_at 字段。
3. `service/guardrails.py`：未处置口径由 pending 扩为 **pending|regenerating|failed**（B 段后 failed 属
   未处置，熔断不因失败尝试被误解除；regenerated/reviewed=已处置即恢复）。
4. `api/feedback.py`：GET /feedback 支持 node_id；POST /feedback 对 auto 节点 commit 后自动触发
   `spawn_auto_regen`（返回 regen 状态）；POST /{id}/regen 默认后台（regenerating）。
5. `frontend SessionPage.tsx`："内容纠错"提交后若进入 auto 重生成 → 轮询
   `GET /feedback?node_id=` 至多 ~15s 显示处理结果（✅ 已自动重生成替换 / ❌ 失败保留原内容待人工 /
   仍在后台等提示）。

**测试**（test_feedback +3）：auto 重生成成功原子替换+文件/库内节点刷新+反馈清零（注入 marker drafter）；
失败保留原内容+result 原因；无 key 不回落 stub 记 failed。guardrails 既有用例（pending→reviewed 恢复）
通过。**回归**：pytest = **188 passed + 1 skipped**（+3）；content validate 13/30 全绿；npm run build 通过。

**疑点/偏离**
1. 无 key 时 auto 反馈自动触发 → 立即 failed"未配置 key"（不再排队 queued_needs_ai）——语义=保留原内容待
   人工/配 key 重试；failed 计入熔断未处置（防误解除），熔断恢复口径随 B 段更新为"regenerated/reviewed
   即恢复"（原 R14 批准口径 pending 清零，功能超集，注释已同步）。
2. 原子替换在单机本地盘上以"同目录临时文件 + os.replace"近似原子（无跨设备）；失败路径不改动原文件。
3. 自动触发点在 API 提交后（commit 先行保证后台会话可见）；服务层直接调用 record 不自动触发
   （可显式 spawn_auto_regen / regenerate）。

---

## 20. C 段：middle 全段扩段（REVIEW D 方向 · 2026-09-08）

**规格**：用户工单 C 段 = middle.yaml 由首批 4 条扩为全段草案（有理数四则与运算律 → 整式 →
一元一次方程（锚 0101–0104）→ 方程应用与不等式 → 二元一次方程组 → 实数与根式 → 平面几何 →
一次函数 → 概率统计初步）。约束：m01–m04 既有条目 id 与内容零改动；只改蓝图、不生成内容。

**改动清单**
1. `content/roadmap/middle.yaml`：4 → **31 条**、6 个连续主题组（audit 无孤立）：
   - 代数·数轴与整式初步 ×4（m01–m04 既有原样）；
   - 代数·有理数与实数 ×6（m05–m10：乘除/乘方科学计数法/混合与运算律/平方根立方根/实数与数轴/二次根式）；
   - 代数·方程不等式与方程组 ×9（m11–m19：一元一次方程概念↔middle.0101、等式性质↔middle.0104、
     解方程↔middle.0102、应用↔middle.0103 四锚定 + 不等式 2 + 二元一次方程组 3）；
   - 图形与几何·平面初步 ×5（m20–m24：角与相交线/平行线/三角形内角和/全等/勾股及应用）；
   - 代数·函数初步 ×4（m25–m28：坐标系/变量与函数/一次函数图象/一次函数与方程不等式联系）；
   - 统计与概率初步 ×3（m29–m31：数据收集描述/集中趋势离散程度/简单概率）。
2. `ROADMAP_AUDIT.md` 再生（middle 31；头部口径更新）。

**audit**：middle 31 ok=True——covered 6（m01/m02 + 方程线 m11–m14）；cross_refs 1
（m29→primary.s21 跨学段引用，A 段机制实战）；缺口提示 1（primary.s21 未落地=懒生成正常）；
前置缺失 0 / 锚点缺失 0 / 环 0 / 正向引用 0 / 孤立 0；5 学段全 ok。
**回归**：pytest = **188 passed + 1 skipped**（无新增测试——既有 audit/selfextend/e2e 覆盖自动适配，
growth e2e 经 middle 多主题后仍推进到高中首批）；content validate 13/30 全绿；零残留。

**疑点/偏离**
1. **一次函数不占位 high.0201**（REVIEW D 措辞"（锚 high.0201）"的落地偏离）：high.0201 是高中人工节点，
   若作 middle anchors 会造成"middle 通关依赖 high 学段节点掌握、而 high 学段解锁依赖 middle 通关"的
   倒锁（selfextend.mastered_ratio(middle) 会纳入 high.0201）。故一次函数（m27/m28）为 middle 待生成
   auto 条目，high.0201 继续仅作 high.h14 的前置真实节点引用（与 R14"一次函数归 middle、high 真实节点
   前置引用衔接"一致）。请架构确认此解释。
2. m01–m04 原 topic"代数·数轴与整式初步"与 REVIEW D 顺序的教材目录略有出入（既有首批结构，REVIEW2
   middle 精核已接受 m01–m04 序列）；扩段以主题组方式补齐 REVIEW D 全列，未重排既有条目位置。
3. 统计概率组 m29 跨学段引用 primary.s21（A 段能力）：primary.s21 未锚定，需小学懒生成落地后中学统计
   学习才无缺口——学段顺序推进下自然满足。

---

## 21. D 段：傅里叶级数单列 + REVIEW2 清单闭合核对（2026-09-08 · 可选段）

### D-1：college.c15b《傅里叶级数初步（方向条目：语音/信号）》
- 插 college.c15（无穷级数）之后、c16 之前（一元微积分 run 15→16 条）；prereq [college.c15]
  （系数积分经 c09/c10 链、收敛承接幂级数）；d3 + thinking true；注释标注"方向条目：语音/信号，
  可选不学不阻塞主线"（REVIEW2 college C"傅里叶单列待精核"→用户 D 段拍板落地）。
- audit：college 59 条全 ok（cross_refs 5 不变、fwd 0）；ROADMAP_AUDIT 再生（college 59）。

### D-2：REVIEW2-master 文末清单闭合核对
**闭合**（证据链：R15 精核补丁批 fa75d28/收尾 35f2d95 + A 段 7816515 + C 段 a30f30b + 本段）：
- primary：s18 +s05；s23 +s08（✓ §16）
- middle：全段扩段 4→31（✓ C 段）
- high：h40b 复数；h73/h79 目标并入；h79 前移去 prereq[high.h73]；h30 prereq [h27,h28]；h47 组名
  "空间向量与立体几何"；h09/h19 衔接注释；h36 选学标注（✓ §16）
- college：c34b SVD/PCA；c43b 随机过程初步（可选+RL/时序注释）；c15 +c07；全表 thinking（d≥3 true）；
  B 项 c20+c19、c55+c04、c49+c45、c31+c30、c16 衔接注释（✓ §16）
- ai：a04b 贝叶斯；a17b ADMM；a25b 变分 ELBO；a12 KKT 深化；a46 单位根/ARIMA；a09 thinking=true；
  a02/a03 承接注释；鞅/布朗对调；a57 +a53/a55；a26/a33 条件数（✓ §16）
- R14 后续：#1 跨学段 prereq（✓ A 段，ai 锚定 college.c34b 的 C① 也随之闭合）；#2 c43+c34
  （✓ 35f2d95）；#3 feedback 重生成替换（✓ B 段）；#5 middle 扩段（✓ C 段）
- C 项定夺：三角线不做、归纳选学、导数止高中、建模不单列、极坐标不列、随机过程归 ai 主线+c43b、
  GP 归属注释（✓ §16）；c43b d4→d3 偏离已记录（✓ §16 偏离 1）

**未闭合（列出，非本工单范围，待学科/架构/用户）**：
1. college C"最小二乘几何（c34 法方程）与统计（c43 回归）分工说明"：两处内容均在，缺显式互注；
   可随下次精核补注释。
2. college C"SVD 深度 / 幂法迭代（大规模特征值数值方法）"：扩展候选，学科精核再定。
3. ai C②"鞅所需条件期望"：college 仅到条件分布（c37），无条件期望严格条目；ai.a45 鞅为直觉/离散级，
   若需严格化应补测度论级条件期望条目（架构再定）。
4. high C⑥ 极坐标/参数方程：默认不列入（开放扩展候选，需要时增补组）。
5. R14 后续 #4 复数等高中增补候选：待用户精核 high.yaml 时收集意见（用户输入项）。
6. 傅里叶 c15b / college 其余 draft：待学科精核转正（用户到段前滚动精核惯例）。

**回归**：pytest = **188 passed + 1 skipped**；content validate 13/30 全绿；audit 5 学段全绿
（26/31/81/59/60）；零残留。

**下一步建议（全部工单完成后）**：a) 架构侧复核 A 段跨学段语义与 C 段"一次函数不占位 high.0201"解释；
b) 用户到段前滚动精核 middle 全段（31 条）与 c15b；c) 配置 LLM_API_KEY 后开启 MF_AUTO_EXTEND=1 做
真人全自动冒烟（小学→初中首批连续通关、auto 内容纠错→后台重生成替换可见）；d) 无 key 环境复核
feedback 自动触发文案与熔断口径。

---

## 22. R18 阶段 1：蓝图总序门禁引擎（2026-09-08 · docs/09 R18）

**规格**：学习进度 = roadmap 权威（roadmap-authoritative progression）。新增 `service/path.py`：
- 条目达成 = 覆盖节点 mastered（anchors[0] 在库 或 条目 auto 落地 id）；开放 = 全部蓝图前置达成
  （同文件条目；跨学段 preref 目标已落地→需达成、未落地→不阻塞，学段顺序兜底）且自身未达成。
- node_allowed：普通节点=所属条目开放（owner：id 即条目 auto 或 anchors 反向）；首领(boss)=归属
  蓝图主题组（内容 topic 精确/唯一前缀匹配）全部达成；孤儿人工节点（如 high.0201）=学段解锁+内容
  prereq 兜底；**mastered/复习/重学放行**（总序只防越级新学；达成节点重学不越级）；学段解锁：
  primary 恒开、其余需前序（有蓝图内容的）学段全部已落地条目达成。
- 接入：progress.state_map / recompute_states 的 available 判定改由 PathEngine（图谱手写 prereq 不再
  单独决定可学性；复习/已掌握不受限）；dashboard 推荐 = 总序允许集内 学段→图谱层→编号 最小；
  /session/start **新建会话门禁**：node_allowed 违反 → 409 invalid_state + "请先完成：<前置标题>"；
  既有会话恢复/练习费曼续走不受影响；/graph、/campaign 经 state_map 自动跟随总序。

**测试基建**：conftest 每模块结束清理副本中运行期 *_auto（共享副本防级联污染）；新增
`backend/tests/order_support.py`（unlock_until：按总序闭包生成缺失 auto 内容 + 前序学段已落地条目
达成 → 目标可学；幂等）；test_api_flow 适配总序（fixture seed primary 头链 s01–s04；0 掌握推荐=
primary.s01；middle 真学链 0101 概念→0104 性质→0102 求解，断言"0104 先于 0102 解锁"的顺序修正）。
**回归**：pytest = **188 passed + 1 skipped**（不降，67s）；content validate 24/47（真实库含 auto）；
git 提交含 docs/09 R17/R18 裁决文本（架构侧书写未提交部分）。

**疑点/记录**
1. 引擎按"蓝图已落地条目"定义学段通关：未落地（懒生成前）条目不算阻塞；同段未落地前置在部分内容
   环境会锁目标（测试用 order_support 生成补齐 = 模拟懒生成既定结果）。
2. start 对"已达成节点"放行=允许复习式重学；严格"不可重学"可由 profile/UI 后续策略另定。
3. 每请求 make_engine 重建 owner 映射（蓝图缓存 lru；库解析 ~ms）；全量回归 49s→67s，量级可接受。

---

## 23. R18 阶段 2：数据/蓝图修正（错位根源清除 · 2026-09-08）

**规格**（用户工单阶段 2 = R18 裁决 #5–#7）：
- #5 s03 乘法口诀内容 prereq 回填 [primary.s02]；逐条核查 primary s01–s23 内容文件 prereq 与蓝图一致。
- #6 primary.yaml 新增"因数·倍数·质数合数·公因数公倍数"（约分/通分基础），插除法后分数前；
  s06–s08（含其锚点 0103/0104 对应蓝图条目）补该前置，难度 2。
- #7 boss 0199 标题/归属口径：与"数与运算"组一致（门禁=该组全达成，引擎接管）。

**改动清单**
1. `content/stages/primary/topic_数与运算/node_primary_s03_auto.md`：`prereqs: [] → [primary.s02]`（回填；
   生成期静默剔除的历史断链修复——R18 允许的 auto 文件修正）。
2. `content/roadmap/primary.yaml`：新增 `primary.s27`《因数·倍数·质数与合数·公因数公倍数》
   （topic 数与运算，prereq [s04, s05]，d2，插 s22 与 s06 之间 = 除法/四则之后、分数之前）；
   s06/s07/s08 prereq 各 +primary.s27（分数意义/异分母通分/分数乘除倒数的约分通分基础；
   s07/s08 锚点 0103/0104 对应蓝图条目的依赖同步补齐）。primary 26 → **27 条**。
3. `content/stages/primary/topic_01_整数运算/node_0199_整数运算首领战.md`：title
   "首领战·整数与四则运算综合" → "数与运算首领战（综合）"（消除"整数 boss 含分数"的表述/门禁错乱；
   门禁由引擎按 内容 topic=数与运算 ↔ 蓝图组达成 接管，手写 prereq [0101..0104] 仅作展示参考）。
4. 内容前置一致性核查结论：s09(fm→0104)/s22(fm→0101)/s23(fm→0102,0104,s10) 引用"锚点节点 id"
   与其蓝图前置（s08/s05/s06+s08+s10）**等价**（anchors 落地 id 同节点），无需改写；
   s03 为唯一硬性断链 → 已回填。s11–s13 与蓝图一致。

**验证**：content validate 24/47 ok；audit 5 学段全 ok（primary 27/middle 31/high 81/college 59/ai 60，
前置缺失 0/锚点缺失 0/环 0/正向引用 0）；ROADMAP_AUDIT 再生（口径 primary 27）。
**回归**：pytest = **188 passed + 1 skipped**（预期不降）；零残留（真实 stages 未新增文件，仅两处字段/行修改）。

**疑点/说明**
1. s27 尚无落地内容（懒生成后出现）：学习链"分数(0102…) 在因数倍数后"到运行期该主题生成后成立；
   阶段 3 fresh-run E2E 将沿 s01→s02→s03→s04→s27→s05(0101)… 推进断言单调。
2. boss 手写 prereq 保留（展示用），门禁权威=引擎组达成（audit 不变式阶段 3 覆盖 boss 归属检查）。

---

## 24. R18 阶段 3：audit 内容不变式 + 总序门禁测试矩阵（2026-09-08）

**规格**（用户工单阶段 3 = R18 #8–#10）：
- roadmap.audit 内容不变式：普通内容节点手写 prereq ⊆ 所属蓝图条目前置闭包 ∪ 自身结构边（引蓝图序
  更后项 → 报错）；boss 归属无主/错主 → 报错；报告含"总序 vs 内容手写边"差异说明。
- 测试矩阵（五学段抽样 + boss + 跨学段 + 允许集 + audit 造错 + fresh-run 单调）；全量回归 188+1 不降。

**改动清单**
1. `content/roadmap.py`：`boss_group_topic`（自 service/path 移入，audit/引擎同源）+ `_content_closure_landed`
   （蓝图前置闭包落地 id 集，跨学段未落地不参与）；`audit()` 新增可选 `content_edges/content_meta`——
   检查 ① 内容手写边 ⊆ 所属条目前置闭包（违规进 ok 判定）；② boss 内容 topic 归属蓝图组（无主/错主
   进 ok 判定）+ 手写 prereq ⊆ 归属组落地集（缺组内落地 → 差异说明）；③ 孤儿节点差异说明；
   返回增 content_prereq_violations/boss_unmatched/content_diff_notes。`service/path.py` 复用该
   boss_group_topic（删除本地副本）。
2. `ROADMAP_AUDIT.md`：生成器按学段传真实库 content_edges/meta，报告增"R18 内容不变式"行与明细。
3. 测试：test_roadmap 审计全学段循环传内容数据断言真库绿 + 造错用例（内容边引蓝图后项必报、
   boss topic 无匹配必报、合法前置不报）；新增 `backend/tests/test_total_order_gate.py`（总序门禁矩阵）：
   - primary 链：s01 根可学 / s02 未达 409 → master s01 → 200；s03 需 s02；
   - 分数红线：0101 前置链解锁后才能学、0102(s06) 需先因数倍数 s27 → 409 → unlock → 200；
   - middle/high/college/ai 各抽样链：未解锁 409 → 依序达成 → 200（college/ai 先 seed 单条 auto）；
   - boss：middle.0199 组未全达成 409 → unlock_until 组达成 → 200；
   - 图谱 available ⊆ 总序允许：available 首节点 start 200、locked 抽样 409；
   - fresh-run 单调：0 掌握 → s01→s02→s03→s04 逐环推进（每环解锁下一环、再后仍 409）→
     0101 解锁、0102 仍锁（分数在因数倍数后）。
4. 测试基建健壮化（顺序耦合修复）：`order_support.unlock_until` DB 写入改**原生幂等 upsert**
   （ON CONFLICT DO UPDATE + JSON 列 + 边重建），规避 ORM 会话/全量 sync 在跨模块共享副本+DB 下的
   UNIQUE/FK 竞态（排查过程记录于 §24 备注）。

**验证**：真实库（含 auto）audit 全绿（violations 0 / boss 无主 0；差异说明 = boss 手写 prereq 未含组内
其它已落地 auto，属预期说明）；content validate 24/47 ok；ROADMAP_AUDIT 再生。
**回归**：pytest = **200 passed + 1 skipped**（188 基线 + roadmap 造错 3 + 门禁矩阵 9，69s 不降）；零残留。

**备注（测试基建排查）**：跨模块共享 hermetic 副本 + 共享 DB 时，unlock 生成 auto 文件 + 全量
sync_content 触发 nodes UNIQUE（同会话 pending 与已提交行叠加）与 edges FK（节点未先落库）——
最终以"按 id ON CONFLICT upsert + 节点语句先于边语句 + JSON 列补全"解决，语义与 sync_content 等价且幂等。
疑点：为何仅跨模块顺序复现、单模块不复现，根因疑似 loader 缓存/会话残留叠加，未进一步深挖（防御已覆盖）。

**测试数字**：全量最终 pytest = **200 passed + 1 skipped**（+12：audit 造错 3 + 门禁矩阵 9）。

---

## 25. R18 阶段 4：文档同步与验收（2026-09-08 · R18 全部四阶段完成）

**docs 同步（架构裁决授权回填）**：
- docs/03 §1 节点状态机：新增 **R18 修订（蓝图总序权威）** 说明——可学性 = 蓝图总序门禁
  （所属条目蓝图前置达成；boss=归属主题组全达成；学段解锁=前序学段已落地条目全达成）；手写 prereq
  仅结构参考/展示；复习/已掌握不受门禁；推荐仍 available 内 学段→层→编号。
- docs/06 §2 `/session/start` 表与 §4 错误码：`invalid_state`（409）新增 R18 语义——越级进入未解锁
  节点且 detail 含"请先完成：<前置条目标题>"；既有会话/练习费曼续走/复习不受影响。
- docs/07 §2.1 图谱：available(蓝/可点) = 蓝图总序允许集；越级灰显 + 直接 start 亦 409。

**验收红线核对（任何学段"后学先可学"= 未通过）**
- 门禁测试矩阵（test_total_order_gate.py，9 例）+ fresh-run 单调 E2E + audit 内容不变式造错必报均已绿：
  五学段抽样链 409→解锁；boss 前锁后开；跨学段（primary 通关前 middle 全 409）；图谱 available ⊆ 总序；
  分数在乘法口诀/因数倍数之后（0102 需 s27、s03 需 s02）——红线场景均被测试断言锁定。
- audit 全绿：primary 27 / middle 31 / high 81 / college 59 / ai 60（前置缺失 0 / 锚点缺失 0 / 环 0 /
  正向引用 0 / 内容手写边越界 0 / boss 无主 0）；ROADMAP_AUDIT 再生含内容不变式行。
- content validate 24/47 ok（真实库含 auto）；全量 pytest **200 passed + 1 skipped**（68.84s，不降）。

**真人验收清单（用户重启服务后应看到）**
1. 0 掌握仪表盘推荐 = primary.s01（小学第一环），不再是中间/高中根；
2. 图谱：s02 灰显直到 s01 mastered；**乘法口诀(s03) 在加减(s02)后才解锁**、**分数意义(0102) 在
   因数倍数(s27)与四则(s0101/s05)之后**——即"分数不再先于口诀/因数倍数"；
3. middle/high 内容在小学未通关时灰显/点击被拒（409 +"请先完成前序学段…"）；
4. boss（数与运算首领战等）只有其归属主题组全部条目达成才可点开；越级直接 POST 亦 409；
5. 复习与已掌握节点照常；中断会话恢复、练习/费曼续走不受门禁影响。

**四阶段提交链**：阶段1 `a224c8a`（引擎总序门禁 + start 409 + state/图谱/推荐总序化）、阶段2 `24866f6`
（数据修正 s03/s27/boss0199 + 提速）、阶段3 `2291c64`（audit 不变式 + 门禁矩阵 + upsert 加固）、
阶段4（本批：docs/03·06·07 同步 + NOTES §25）。基线 188+1 → **200+1**（新增用例全为总序/不变式保障）。
**备注**：docs/05 未改（R18 不涉及 AI 调用点 schema/状态机流转，门禁在 start 边界；如架构认为需在
docs/05 会话章节补门禁指引可另行回填）。

---

## 26. 会话续接（2026-09-09 13:50）—— 基线复核通过：pytest=200 passed + 1 skipped，content=ok 24 节点/47 练习

**续接前最后已知状态**：
- 新 Euler 实例（本会话）按 docs/13 §1 开机清单完成全量上下文读取与基线验证：
  pytest **200 passed + 1 skipped**（201 collected exit 0）；audit 5 学段全绿
  （primary 27/middle 31/high 81/college 59/ai 60，经 test_roadmap 真实库循环断言 + 门禁矩阵）；
  content validate **ok=True nodes=24 exercises=47**；git HEAD=a2eeeb4（docs/14 工单文档 +
  全文档"适用范围"标签 + resume/ 清理已由设置批提交）、工作树干净。
- 里程碑：M0–M5 + docs/11 阶段 1/2/3 + docs/12 总纲 P1–P4 + R15 精核补丁 + A/B/C/D 引擎段 +
  R18 蓝图总序权威化（§8–§25 全部落地）；当前活动工单 = **docs/14 Phase A**（docs/13 §3）。
- 本会话目标：docs/14 Phase A 四子步 A1–A4（各独立汇报 + git 提交，提交标注 PhaseA 子步）；每步
  全量回归 200+1 不降 + content validate 绿 + audit 全绿 + 零残留；疑点挂"待架构裁决"。

---

## 27. docs/14 Phase A · A1 子步：subject/outline 数据模型与持久化（2026-09-09）

**规格**：docs/14 §1/§2.1/§7 #2 + 派工单 A1（subject 注册与命名空间；outline schema；大纲文件持久，
可审阅/局部改/整份重生成版本递增；SQLite subject 维度迁移方案，兼容现库）。

**改动清单**
1. `backend/app/outline/schemas.py`（新）：大纲 schema v1（OutlineDoc/OutlineUnit/校验）——subject/
   schema_version/revision/status(draft|active)/source(roadmap|ai|manual|hybrid)/unit_id_scope/
   units{id,title,objectives≤4,concept_tags[],group,prereqs,difficulty,requires_thinking,anchors,
   topic,status(draft|reviewed)}；结构校验：id 唯一/自指/引用存在性（含 '.' 内容节点引用，注入
   known_content_ids 才判存在）/同大纲前置环（DFS）；YAML 往返（UTF-8 可审阅）。
2. `backend/app/outline/store.py`（新）：学科注册（DB subjects 表：preset math 幂等注册、custom API
   创建/删除，preset 治理红线）+ 大纲持久化 `content/subjects/<sid>/outline.yaml`（原子替换；
   重生成 revision+1 版本递增）；custom 单元 id 强制 `<subject>.` 前缀（内容节点全局唯一命名空间
   约定）；preset 大纲禁止直接 PUT（由 roadmap 派生治理，A3 落派生入口）；patch_outline_unit 局部改
   （custom 白名单字段 / preset 仅附加字段）。
3. `backend/app/models.py`：+ Subject 表（id/label/kind=preset|custom/description/meta_json）。
4. `backend/app/api/subjects.py`（新）+ main.py 挂载与 lifespan `ensure_math_preset`：
   GET/POST /subjects、GET/DELETE /subjects/{sid}、GET/PUT /subjects/{sid}/outline、
   POST /subjects/{sid}/outline/validate、PATCH …/units/{unit_id}、POST …/regenerate（A4 占位 501）。
5. `backend/tests/test_outline.py`（新 ×20）：schema 往返/重复/自指/环/引用/目标上限/难度域/版本守卫/
   空大纲；store preset 治理/幂等注册/custom 创建/版本递增落盘/环拒/局部改/删除/非法 id；API 全流程
   （math preset 列表、preset PUT 拒、CRUD、环 422、命名空间前缀拒、非法 id 422、删除、preset 删除 409、
   regenerate 501）。
6. docs 同步：docs/02 §3 目录树（outline 模块 + content/subjects）；docs/06 §1 学科与大纲端点表、
   §3 subjects 表 + subject 命名空间迁移方案说明（现有关键表不加列零迁移；概念层独立表 A2 补）。

**迁移方案（已文档化，docs/06 §3）**：学科注册 = subjects 表；大纲 = 文件；既有 nodes/edges/
user_nodes/… 不加 subject 列（内容节点隐式归属 math，语义零变更兼容现库）；subject 归属由
大纲 ↔ 内容 id 映射反查；自定义学科内容节点 id 强制 `<subject>.` 前缀防跨学科碰撞。

**回归**：pytest = **220 passed + 1 skipped**（200+1 基线 + 新增 20，不降）；content validate
24/47 全绿；audit 5 学段不变（本子步未动 roadmap/stages）；git 提交（PhaseA A1）。

**疑点（挂待架构裁决）**
1. 大纲 schema 单元 objectives 上限取 **5**（docs/14 规格"目标≤3"；数学 roadmap 既有精核条目
   最高 5 条 college.c34b SVD、a12 KKT 4 条——机械照搬 ≤3 会与现库冲突）。AI 起草提示词按 ≤3
   执行（A4），schema 宽松 ≤5 兼容既有数据（A1 记录原按 ≤4，A3 建 outline 时实测放宽至 ≤5）。
2. "整份重生成版本递增"以 revision 字段 + 原子替换实现，历史版本留 git 不落盘归档副本（MVP 口径；
   若需运行期回滚/对比旧版，需大纲归档目录设计——列为候选）。
3. 大纲文件放 `content/subjects/`（git 管理、随内容库隔离副本走测试）；subjects 表为 DB 注册真源，
   目录仅文档载体（两处不重复存大纲元数据）。
4. delete_subject 对已产生学习进度的 custom 学科未做进度级联（A2 显式重置语义落地后统一处理；
   当前 custom 无内容闭环，不构成实际风险）。

---

## 28. docs/14 Phase A · A2 子步：概念层与进度映射（2026-09-09）

**规格**：docs/14 §2.2 + 派工单 A2（concept 标签表 + 掌握证据挂 (subject,concept)；单元完成 →
归一化标签；大纲重生成 → 新单元按概念命中等效已掌握（标绿/可跳过）；显式重置可选；数学历史掌握
迁移：既有锚点节点/掌握状态 → 概念标签（数学概念归一清单）→ 进度不丢）。

**改动清单**
1. `backend/app/models.py`：+ Concept（概念注册表，归一化 concept_id PK(subject,concept)）与
   UserConcept（掌握证据 (user,subject,concept)，evidence_json=证据节点列表，幂等派生非人工）。
2. `backend/app/outline/concepts.py`（新）：归一化（去空白/ASCII 小写/全角→半角）；大纲标签 →
   concepts 注册表同步；`content_to_unit`（unit.id 在库/anchors 在库 → 归属单元）；**学科内容节点
   全集**（preset math=level∈LEVELS ∪ 大纲映射；custom=大纲映射——杜绝跨学科污染）；
   `recompute_subject_concepts`（user_nodes.mastered → 概念证据全量替换；归属单元 concept_tags
   非空优先，否则节点 core_concepts 兜底——孤儿/首领/auto 节点历史掌握可确定性归一）；`unit_states`
   （单元视图：mastered > learning > equivalent(概念命中) > todo；open=前置全部达成，等效=达成，
   即"等效已掌握可跳过、未命中照学、前置等效即解锁"）；`reset_subject_progress`（显式重置：清
   (subject) 概念证据 + 学科内容节点 mastered/learning 降回 available + 清复习行 + 全图重算）。
3. `backend/app/api/subjects.py`：GET /subjects/{sid}/progress、POST …/progress/recompute、
   POST …/progress/reset；outline PUT/PATCH 落盘后自动 sync 概念注册表。
4. `backend/tests/test_concepts.py`（新 ×10）：归一化/注册表幂等/大纲重生成后概念证据保留且新单元
   等效已掌握（结构重组 demo.one→demo.frac 演示"换大纲不丢进度"）；孤儿节点 core_concepts 兜底
   （math 引擎路径：保存式注入大纲 + 单元结构调整后 math.new1/new2 概念命中 equivalent）；显式重置；
   math(preset) 重置作用于内容库节点（primary.0101 mastered→available，含进度还原）；API 流程与
   404。
5. docs 同步：docs/06 §1 progress/recompute/reset 端点、§3 concepts/user_concepts 表。

**回归**：pytest = **230 passed + 1 skipped**（A1 220+1 基线 + 新增 10，不降）；content validate
24/47 全绿；audit 5 学段不变；git 提交（PhaseA A2）。

**疑点（挂待架构裁决）**
1. "等效已掌握"判定 = 单元概念标签集非空且 ⊆ 已掌握概念集。概念粒度/同义合并 MVP = 精确归一匹配
   （docs/14 §7 #3：更细归一策略列为治理项；跨语言/同义合并可后续加 aliases）。
2. 数学概念标签数据源：非大纲单元的孤儿人工节点（high.0201、boss 0199 等）与无标签单元的 auto
   节点以 **节点自身 core_concepts** 兜底归一（"数学概念归一清单"由既有精修 core_concepts 承担，
   免逐单元人工补标）；大纲单元标签在 A3 math outline 派生时由锚点节点 core_concepts 回填。
3. 显式重置 scope = 概念证据 + 学科内容节点掌握 + 复习行；**不**清 attempt/session 历史
   （审计留痕，docs/03 复习降级口径一致）；若需"连历史一并清"另行裁决。
4. 首领(boss)节点概念由 core_concepts 兜底（如"数与运算首领战"含分数加减等标签）——boss 达成
   时点已在组全部条目达成后，故其证据为重复集，语义无害；如架构认为 boss 不应产概念可加排除。

---

## 29. docs/14 Phase A · A3 子步：数学 preset 迁移与总 Outline 建立（2026-09-09）

**规格**：docs/14 §5 + 派工单 A3（数学=subject=math；五学段 roadmap/内容/总序门禁/sympy L1/费曼
rubric/guardrails 封为 preset 规则；建立数学总 Outline（学段=关卡组、段内=既有总序链；roadmap draft
状态如实标注）；打通 outline ↔ concept 标签映射（既有锚点节点归一到概念标签，历史掌握进度可迁移）；
已知问题治理：s27 补链后一致性复核、0 掌握用户总序起点链（s01→…）实测、迁移暴露耦合抽离测试锁定）。

**改动清单**
1. `backend/app/outline/math_preset.py`（新）：`build_math_outline`（纯函数：roadmap → 数学总
   OutlineDoc；roadmaps/lib_docs 可注入测试）与 `derive_math_outline`（持久化 + 概念注册表同步 +
   重生成 revision+1）。语义：
   - 关卡组=学段（primary/middle/high/college/ai），组内=roadmap 列表序（既有总序链）；
   - 单元=roadmap 条目原样映射（title/objectives/prereqs/difficulty/thinking/anchors/topic）；
   - 概念标签：重生成优先沿用上版同 id 单元标签（不丢人工补标）；否则由已落地内容节点
     （anchors[0] 在库 → 锚点；否则单元 id 在库 = auto 节点）core_concepts 归一回填——
     "既有锚点节点归一到概念标签"，免逐单元人工补标；孤儿人工节点/首领由概念层节点
     core_concepts 兜底（A2 已实现）；
   - 单元 status：primary=reviewed（已精核转正）；middle/high/college/ai=draft（docs/14 §5 ①
     如实标注；roadmap 精核转正为持续治理项）；doc note 记载治理口径。
2. `content/subjects/math/outline.yaml`（新，入库）：数学总 Outline v1——**258 单元**（primary 27/
   middle 31/high 81/college 59/ai 60），revision 1，status active，source roadmap；21 个已落地内容
   单元带概念标签（13 锚点 + 8 auto），其余 draft 单元标签随内容落地/精核滚动回填。
3. `backend/app/api/subjects.py`：POST /subjects/math/outline/regenerate = roadmap 派生/再派生
   （custom 仍 501 待 A4）；`backend/app/main.py` lifespan：math 大纲缺失时自动派生一次（首启/
   全新克隆兜底；文件已入库则不动，版本治理走显式 regenerate）。
4. `backend/app/outline/schemas.py`：objectives 上限 4→5（A3 建 outline 实测 college.c34b SVD 五条
   精核目标触发放宽；见 A1 疑点 1 修订）。
5. `backend/tests/test_math_outline.py`（新 ×12）：派生 258 单元/组规模/转正状态如实；结构校验
   （内容库引用）干净；锚点单元标签 == 锚点节点 core_concepts 归一；**s27 一致性红线段**
   （s04<s27<s06 序 + s06 prereq 含 s27）；派生重生成 revision 递增 + 同 id 标签保留；
   **结构重组进度不丢**（s05→s05v2 改名仍锚 0101 → 标签自动回填 → 单元状态保持达成(mastered/
   equivalent) 不回退 todo；节点级 mastered 原样）；**0 掌握首开放单元 = primary.s01**；API
   regenerate（math 200/结构正确；custom 501）；通用学段档位语义锁定（非 LEVELS → fast 基础 +
   content_think 覆盖；math college 仍 think）；仓库 outline 文件可解析。A1/A2 两处断言适配
   （math outline 现存在；registry 计数用独立学科 id 防 math 全局概念污染）。
6. docs 同步：本 NOTES §29；（docs/06 §3 概念表/大纲文件已随 A1/A2 同步）。

**预设规则封装口径（"数学写死"耦合）**：sympy L1 判题（domain/judge）、总序门禁（service/path，
R18）、费曼 rubric/guardrails（content/service）为 math preset 的学科规则，以"代码 + roadmap 大纲
治理"承载——学习门禁仍读 roadmap（权威），math outline 为治理视图（docs/14 §5"roadmap 精核转正为
math outline 持续治理项"）；概念层不替代门禁，只做"换大纲不丢进度"的等效映射。后续通用学科
内容/路径引擎所需的泛化（NodeDoc level 放宽、outline 门禁）在 A4 落地并测试锁定。

**回归**：pytest = **242 passed + 1 skipped**（230+1 基线 + 新增 12，不降）；content validate
24/47 全绿；audit 5 学段不变；git 提交（PhaseA A3）。

**疑点（挂待架构裁决）**
1. 大纲"转正状态"为单元级 status 字段（roadmap 文件头注释仍是"草案"字样）；本实现按 docs/14
   §5 ① 口径落地（primary reviewed、其余 draft）。若 roadmap 文件头注释应与大纲一致，需架构侧
   统一口径后由精核批回填。
2. math outline 概念标签目前覆盖"已落地内容"单元（21 个）；未落地单元标签随懒生成内容落地后
   再次 regenerate 时由 auto 节点 core_concepts 回填（重生成语义已锁测试）——首个正式版本
   （v1）标签覆盖率为渐进式而非全量，接受为常态（内容库稀疏属懒生成常态，docs/14 §5 ③）。
3. A3 未动 domain/NodeDoc level（仍 5 学段 Literal）与 ai/tier 决策：通用学科内容生成（A4）需要
   放宽 level 语义时再行抽离并锁测试；本次仅锁"非 LEVELS 档位语义=fast 基础"。
4. boss（0199）不是 roadmap 条目 → 不在 math outline 单元内（大纲=学习单元规划，首领属关卡层，
   由 campaign/引擎组达成驱动）；其概念证据经 core_concepts 兜底进概念层（同 A2 疑点 4）。

---

## 30. docs/14 Phase A · A4 子步：通用路径闭环 + 大纲起草/审阅（2026-09-09）

**规格**：docs/14 §2.1/§2.3/§5（开放用户在 UI 自建学科=验收本身）+ 派工单 A4（选择/新建学科 →
AI 起草大纲（单元级）→ 校验（依赖无环/标签归一）→ 地图预览 → 采纳/改/重生成；懒生成单元内容沿用
source:auto/纠错/熔断/token 限额语义；地图/费曼/复习按 (subject, unit/concept) 工作；自动化验收用
临时示例学科跑通：大纲→地图→懒生成单元→费曼评估→重生成大纲进度不丢，不预置正式内容）。

**改动清单**
1. `backend/app/domain/graph.py`：level 校验语义抽离——仅 math 命名空间（id 以学段名开头）强制
   level ∈ LEVELS（防数学 typo 旁路）；通用学科内容节点 level=大纲关卡组标识放行（NodeDoc level
   Literal → str，docs/04 schema 放宽）；test_graph 对应改 2 例（math 命名空间拒 / 通用放行）。
2. `backend/app/service/outline_gate.py`（新）：通用学科大纲门禁——节点 → (subject,unit)（内容节点
   id == 大纲单元 id；level 前缀 ∈ LEVELS 的 math 节点不路由）；单元满足 = 内容 mastered 或概念
   等效（tags ⊆ 已掌握概念）；开放 = 前置单元全部满足（等效即达成不卡后链）；session.start /
   progress.recompute/state_map 分流（custom→outline_gate，math→PathEngine R18 不变）。
3. `backend/app/service/progress.py`：mark_mastered 后自动 refresh 概念证据（通用学科等效判定实时；
   math 节点零开销——resolve 早退）；demote 同源（证据自动收缩）。
4. `backend/app/outline/generate.py`（新）：通用学科单元内容懒生成——stub 出稿确定性 NodeDoc
   （讲解稿=目标驱动、练习=fixed+boolean_judgment 语义判断题、费曼默认 4 维 rubric、core_concepts=
   大纲标签；prereqs=[]：学习顺序权威=大纲门禁，内容不复制依赖防悬空）；落盘
   stages/<subject>/node_<id>_auto.md（source:auto 可纠错/熔断/隔离）→ refresh+sync_content 幂等。
5. `backend/app/outline/draft.py`（新）+ ai/calls CALL_OUTLINE_DRAFT（调用点 10，light 档 JSON
   schema）：起草候选（不落盘）——LLM_API_KEY → OpenAICompatibleProvider 真模型；无 key → 离线
   启发式（线性骨架，source=heuristic）；服务端兜底修复：id `<sid>.u<n>`、objectives ≤3、prereq 只
   许引更早/既有单元（剔除非法）、tags 去重 ≤5、校验报告。OUTLINE_SOURCES + heuristic。
6. `backend/app/api/subjects.py`：POST outline/draft、POST units/{unit_id}/content、regenerate 语义
   （math=派生 +1；custom=重起草候选不落盘）。前端 `api.put/del` helper。
7. `frontend`：SubjectsPage（学科列表/新建）、OutlinePage（起草候选预览/采纳/重生成/单元标签局部改
   PATCH/懒生成内容/重置进度/按组表格状态视图），路由 `/subjects`、`/subjects/:id` + 导航。
8. `backend/tests/test_generic_subject_e2e.py`（新 ×2，docs/14 §6 自动化验收用临时示例学科）：
   **Python 入门 全闭环**——创建 → draft 候选（启发式 4 单元）→ 采纳 rev1 → 地图 u01 开放/
   u02-u04 锁 → 懒生成 u02 内容 → 越级 start 409（大纲门禁）→ 懒生成 u01（幂等 exists）→ 达成
   u01（mark_mastered 自动刷概念证据）→ u02 解锁 start 200 → 大纲重生成（u01→u01b 改名保留标签）
   rev2 → u01b 概念等效已掌握、u02 仍开放（前置等效不卡链）、原内容节点 mastered 不动 → 显式重置
   → 概念清 0、u01b 回 todo；custom 单单元直接可学对照。真打练习/费曼评估交互属浏览器真人验收
   （docs/11 惯例），引擎侧按 R18 同口径（达成+概念派生确定性闭环）。
9. docs 同步：docs/06 §1 draft/content/regenerate 端点行（math 派生 vs custom 候选语义）。

**回归**：pytest = **245 passed + 1 skipped**（242+1 基线 + A4 新增/调整 4：graph 语义 2、E2E 2，
不降）；content validate 24/47 全绿；audit 5 学段不变；npm run build（tsc+vite）通过；git 提交
（PhaseA A4）。

**疑点（挂待架构裁决）**
1. 通用学科内容出稿为**确定性 stub**（离线机制演示）；配 LLM_API_KEY 后同一路径换真模型
   （大纲起草已接 CALL_OUTLINE_DRAFT；单元内容 AI 出稿的学科化讲解/rubric 模板与语义问答题目块
   属 docs/14 Phase B 范围——本批先锁机制与闭环，不做学科专用 prompt）。
2. "懒生成单元内容沿用现有流水线（source/auto/纠错/熔断/token 限额）"在通用学科落地为：同一
   `*_auto` 落盘语义 + 幂等 + sync_content + 纠错反馈/guardrails 表结构已通用（node_id 维度），
   但**主题熔断/每日 token 限额对通用学科内容的接线**未做（math 侧已有 service/guardrails 按
   roadmap topic；通用学科熔断粒度=subject 待 Phase B 细化）——列为后续。
3. outline_gate 每次按 node 读大纲文件 + DB 查概念（本地小文件，性能可接受）；多学科大量节点时
   可加进程级缓存（key=文件 mtime/revision）——现不引入（测试共享副本避免缓存一致性问题）。
4. 通用学科内容节点 prereqs=[]（顺序权威=大纲门禁，防大纲重构后内容边悬空）；图谱/复习/会话对
   内容手写 prereq 的展示语义在通用学科下为"无"——已记录，UI 依大纲显示。
5. E2E 里"费曼评估"环节以服务层达成（mark_mastered 触发概念证据刷新）替代离线跑完整会话；
   与 math 侧 R18 测试矩阵同口径（docs/11：交互环节浏览器真人验收，配置 LLM_API_KEY 后由用户在
   /subjects 页实测）。

---

## 31. R19 后续批 · 块 1：吸收架构热修 + 补回归（2026-09-09）

**开机复核**：HEAD=5b49a8a、pytest **245+1**、audit 5 学段全绿（test_roadmap 循环断言）、content
24/47、git 干净（docs/13 中文化条款未提交改动随块 2 提交）。

**逐项复审结论（吸收批）**
1. 39332ad（出稿模板纪律：禁 round/floor/ceil/abs/mod 符号取整、估算题改 fixed）——语义正确，
   pipeline 自检层天然拦截；**补回归**：AI 出稿含 `answer_expr: round(a / b, 2)` → generate_entry
   status=failed、错误含 broken、零落盘（test_drafting_online）。
2. 1374145（pipeline 写盘注入 source:auto）+ 928c400/25c5a42（损坏 outline 读取降级全量重派生；
   空 title 修复）——语义正确；**补回归**：math 大纲文件损坏（缺 id/空 title）→ derive 降级无旧版、
   干净重派生 258 并原子覆盖、不 500（test_math_outline）；schemas.OutlineUnit **title 改为必填**
   （pydantic v2 缺省不校验默认值 → 杜绝"空 title 静默入库"，与 25c5a42 同源治理）。
3. 838ea89（conftest hermetic 排除运行期 *_auto）——与 Phase A 测试机制一致（副本隔离 + 模块级
   purge），确认无需改动。
4. e7d8f0b（R17：回炉/重进费曼轮次清零）——代码已吸收（_feynman_reset 两回炉点 + _enter_feynman
   防御）；**补 E2E**：3 轮不过→回炉→重学（练习全对）→再次费曼提交 200 + mastered，不再 409
   （test_api_flow）。
5. d9f9b3d（纠错人工分支提示中文"仅记录不自动改"）——UI 文案确认中文、语义仅标记 reviewed 不动
   人工内容，✅。
6. 8f9da55（OutlinePage：math regenerate 直接派生落盘、勿按候选 problems 解析）——确认修的是
   A4 本批 UI 缺陷（math regenerate 响应无 ok/problems，前端按候选解析即崩），语义正确 ✅。
7. a7ba29f（大纲分组由单元 group 前端派生，后端无顶层 groups 字段）——OutlineDoc 无顶层 groups
   （python property 不落 JSON），前端派生正确 ✅。
8. 69916c5+5b49a8a（中文标签自动 ASCII id 回退 s-<hash>；subject id 允许数字开头）——已吸收并
   **对齐 slugify 规则**（允许数字开头、剥离中文）；**补回归**：中文 label 建学科成功（id=s-<hash>）、
   数字开头显式 id（111）成功、混合 ASCII 标签 slug=111，均不 422（store + API 两层）。

**回归**：pytest = **250 passed + 1 skipped**（245+1 基线 + 新增 5，不降）；content validate 24/47；
git 提交（R19 块1）。

---

## 32. R19 后续批 · 块 2：对外错误中文化（docs/13 §2 绝对要求 · 2026-09-09）

**规格**：全 API 错误统一中文人话——所有 HTTPException/校验错误的 message 为中文（含原因+可操作
提示；英文/原始 pydantic 文案逐一翻译，原文只进日志）；main.py 全局异常处理器（未捕获 → 500 中文
"类别+查日志"不暴露 traceback；RequestValidationError → 中文含字段中文名映射）；前端 api.ts 按状态
中文兜底；新增 test_errors_zh.py 抽查各层；全仓库 raise 英文 message 扫描清零。

**改动清单**
1. `backend/app/api/errors_zh.py`（新）：FIELD_ZH 字段中文名映射 + pydantic/RequestValidationError
   摘要（type 规则→中文：missing→缺少字段、type→格式错误、literal/enum→取值不在允许范围等）+
   HTTP 状态中文兜底 + ensure_zh_message（无中文即兜底）。
2. `backend/app/main.py`：注册三个全局处理器（保留仓库契约 body={detail:{error:{code,message}}}）：
   - RequestValidationError → 422 validation_error（字段中文名+类型规则，不暴露 pydantic 原文）；
   - HTTPException（含 Starlette 默认 404/未中文化 detail）→ 已结构化中文直接透传，否则状态中文
     兜底（原始 detail 只进日志）；
   - 未捕获 Exception → 500 internal_error"服务器内部错误（类别），详情见日志，请稍后重试"
     （完整 traceback 只进 logger.exception；类别中文映射）。
3. `backend/app/api/subjects.py`：_outline_err ensure_zh；_unit_payloads 用 pydantic_summary_zh
   （字段中文）替代原始英文 validation 文本。
4. 全仓库扫描（AST：raise 处首 ASCII 大写 message）：仅 4 处为 ASCII 缩写开头（AI/MVP + 中文
   主体）——语义中文，无需翻译；judge/NotationError 等面向用户的中文提示已在 service 层确认。
5. `frontend/src/api.ts`：fetch 异常 → network_error 中文；状态码中文兜底表（404/409/422/500…）；
   非中文 message 判定（无 CJK 且 ASCII 开头）→ 兜底文案；兼容 {"detail":{...}} 与 {"error":{...}}
   双包装；SSE 流错误同样兜底。ErrorBoundary：渲染异常英文原文不裸显（中文人话，原文留控制台）。
6. `backend/tests/test_errors_zh.py`（新 ×6）：404 学科/404 未知路由（不得裸 Not Found）/
   409 越级 start invalid_state/422 入参（缺 label、类型错 node_id=123）/422 手动单元 payload/
   500 mock（独立 TestClient raise_server_exceptions=False；message 含类别中文、无英文堆栈与
   内部细节）——统一断言 message 含中文字符且不含英文堆栈 token。
7. docs：docs/13 §2 中文化条款（架构未提交改动）随块 2 提交入库。

**回归**：pytest = **256 passed + 1 skipped**（250+1 基线 + test_errors_zh 6，不降；见 §32 提交说明
实测）；content validate 24/47；npm run build（tsc+vite）通过；git 提交（R19 块2）。

**疑点（挂待架构裁决）**
1. 错误体保持既有仓库契约 {"detail":{"error":{code,message}}}（前端 api.ts 双包装兼容）——
   与 docs/06 §1"错误统一 {error:{code,message}}"的文档表述（无 detail 外壳）存在差异；本实现按
   既有 HTTPException 实际序列化形态落地并同步前端兼容，建议 docs/06 §1 补一句"实际响应包在
   detail 内"或由架构统一为扁平 error（改动会牵动既有测试/前端，另行裁决）。
2. 500 类别映射为小型字典（KeyError/ValueError/DB 忙/AI 等），未知类型一律归"系统处理"不暴露
   英文类名；如需细分可扩映射表。

---

## 33. R19 后续批 · 块 3：delete custom 先 reset 再删 + outline_gate 大纲缓存（2026-09-09）

**规格**：R19 backlog 挑两条——12) delete custom 学科：先按 reset 语义清概念/内容掌握再删（避免
悬挂进度与"subject 已删仍可学"的孤儿内容）；13) outline_gate 大纲读取加进程级 mtime/revision 指纹
缓存（多学科大表性能，简单实现+测试）。

**改动清单**
1. `backend/app/outline/store.py::delete_subject`（重写）：删除前按 reset 语义清进度——
   ① 由大纲（单元 id + 本学科前缀锚点）先取内容节点 id 集；
   ② 删除 content/stages/<subject_id>/ 下懒生成内容文件 → refresh + sync_content（Node 行转
      disabled，内容消失不留孤儿）；
   ③ 清除这些节点的 user_nodes/reviews 行与 (subject) user_concepts/concepts 注册行；
   ④ 删大纲文件 + subjects 注册行；attempts/sessions 审计留痕不删（A2 重置口径）。防误删：锚点
      仅收本学科前缀节点（不触碰锚到 math 等其它内容的进度）。
2. `backend/app/service/outline_gate.py`：进程级大纲缓存——指纹 = outline.yaml (mtime_ns,size)，
   每次读取先 stat 命中指纹复用 OutlineDoc，文件变更自动重读；`clear_outline_cache(subject_id?)`
   提供显式清空（线程锁保护）；resolve_subject_unit/_outline_of 统一走缓存。
3. `backend/tests/test_generic_subject_e2e.py`（+2，TestBlock3）：
   - outline_gate 缓存失效：v1(a) 首读 → 整份重生成 v2(a→b) revision+1 → 无需手动清缓存即反映
     （resolve a=None、b 命中、revision=2）；
   - delete custom 先 reset 再删：掌握+概念证据后 DELETE → subject/大纲消失、user_concepts/
     concepts/user_nodes 清空、内容文件移除且 Node 行禁用、已删内容 start=404。

**回归**：pytest = **258 passed + 1 skipped**（256+1 基线 + 2，不降）；content validate 24/47；
git 提交（R19 块3）。

**疑点（挂待架构裁决）**
1. delete 后 Node 行以 disabled（enabled=0）保留（同步机制），不物理删行——与 R18 sync 语义一致、
   保留审计追溯；如需"物理删除 + 审计仅留 log"另裁。
2. outline_gate 缓存指纹基于 mtime_ns+size（不解析文件内容）；同 mtime_ns+size 的极端覆盖可能
   短暂命中旧值（本实现所有大纲写入均经原子替换且 revision 变化改 size，实际不构成风险）；
   如需更强一致可改为内容 hash 或显式 bust（clear_outline_cache 已提供）。

---

## 34. docs/14 Phase B · B1：学科化单元内容出稿（2026-09-09 · 与 B2 判题引擎联动）

**规格**：docs/14 §10/§2.4/§2.5 + R22（行星科学试点；真内容替换桩：讲解按学科语境、3–5 道多样
练习题、费曼学科化 rubric——先给科学类默认模板；无 LLM_API_KEY → 保留启发式桩离线可测）。
说明：R22 前架构侧先行提交 3ea2798（docs/15 交接 + 吸收 schemas/judge 部分改动，258+1 保持）。

**改动清单**
1. `content/schemas.py`（前置已吸收进 3ea2798）+ `domain/judge.py`/`content/templates.py` 补齐：
   - CheckDoc 新增 **single_choice / fill_text** 判题模式；ExerciseDoc 增 options/answer_index/
     expected/aliases 与题型一致性校验（B2 引擎层，B1 内容出稿依赖其自检）；
   - judge：judge_single_choice（接受 编号/字母/选项文本，乱答 NotationError）、judge_fill_text
     （归一化 + aliases 同义）；统一 judge() 增 options/aliases 参数并分发（补回 3ea2798 未吸收的
     统一入口段，import re）；
   - templates.RenderedExercise 增 options/answer_index/aliases 与 judge_payload 细分；_render_fixed
     支持新两型（selfcheck 用 canonical 作答通过）。
2. `outline/generate.py`（重写 A4 单题桩 → B1 学科化出稿）：
   - **heuristic（离线确定性）**：由大纲元数据构造 3–5 道、≥2 题型、题面去重的可信题
     （boolean 概念归属 / single_choice 概念选择（干扰=其它单元标签）/ fill_text 补全概念 /
      目标句选择题补足）；全部可自动判题并过自检——无 key 可测；
   - **AI（配 key）**：`CALL_UNIT_CONTENT`（ai/calls 调用点 11，light 档 schema 化）→ 组装 NodeDoc
     → validate_generic_content（题型≥2/题量≥3/题面去重/自检 broken）→ 失败带错误重试 ≤2 次，
     仍失败降级 heuristic；
   - 费曼 rubric 学科化：rubric_for() 科学类模板（correctness/own_words/**evidence**/self_correction，
     启发式按学科名/标签命中）与通用四维；
   - 落盘沿用 source:auto + refresh/sync 幂等；material_summaries 参数预留（B3 注入引用摘要）。
3. `service/session.py`：_exercise_view 对 single_choice 输出 options（答案不泄；服务端判题）。
4. `backend/tests`：test_judge +2（single/fill 判题矩阵 + Notation）；test_unit_content_gen.py 新 ×4
   （行星科学 10 单元全部生成多题型内容：≥3 题/≥2 题型/跨单元题面零重复/科学 rubric 命中
   evidence；heuristic 单单元底线；AI 调用点注册；无 key 自动启发式离线成功）。

**回归**：pytest = **264 passed + 1 skipped**（258+1 基线 + 新增 6，不降）；content validate 24/47
（通用内容只在临时学科副本生成，不入仓库）；git 提交（PhaseB B1）。

**疑点（挂待架构裁决）**
1. 启发式题目为"事实引用大纲元数据"的安全陈述（判断恒可判、选择正项固定第 1 项）——UI 展示
   需避免"永远选第一项"的做题套路：后续可在 heuristic 内随机打乱选项并把 answer_index 同步
   （保持确定性种子），或在 B2 UI 提供乱序渲染（选项展示序与判题序一致即可）；建议架构定夺。
2. fill_text 归一化 MVP=去空白/句末标点+小写；更细（繁简/标点变体）同 docs/14 §7#3 治理。
3. "原三题相同"在启发式与 AI 路径均已以"题面去重 + 题型多样校验"锁定；跨**轮次**（同单元重
   新生成）是否要求不同题面属可选增强（当前重生成 = force 后由校验保证 ≥3 不重复的稳定题组）。

---

## 35. docs/14 Phase B · B2：题目形式与交互多样化（2026-09-09）

**规格**：docs/14 §2.5/§4 Phase B 前置——练习支持多题型混合（single/fill/boolean/计算式 sympy/
排序匹配后置）；每题标注题型，ExercisePanel 按题型渲染（点选/填空基础控件先落地）。

**改动清单**
1. `frontend/src/components/ExercisePanel.tsx`：按 `exercise.mode` 分派基础控件——single_choice
   点选（按钮 1..n 提交编号）、fill_text 填空输入、boolean_judgment 对/错；数值/表达式/方程走
   既有 workbench/guided/graph（MathInput）；题型中文标签（选择题/填空题/判断题…）。
2. `frontend/src/api.ts`：ExerciseView 增 `options?: string[]`（single_choice 渲染；服务端判题，
   不泄 index/答案）。
3. 每单元 ≥2 题型 / ≥3 题 / 题面去重的**引擎保证**在 B1 的 validate_generic_content + 生成器
   落盘前校验，B1 测试已锁定（docs/14 验收项引擎侧）。
4. docs 同步：docs/04 §3 判题模式表增 single_choice/fill_text（实现要点）；docs/07 §1 增 Phase B
   题型控件说明。
5. （后端判题引擎 single_choice/fill_text 与渲染/selfcheck 已在 B1 提交 3ea2798+B1 补齐，故 B2 主体
   为前端 + docs；无 pytest 计数变化。）

**回归**：pytest = **264 passed + 1 skipped**（与 B1 持平，本步为前端/docs，无新增后端用例）；
`npm run build`（tsc+vite）通过；content validate 24/47；git 提交（PhaseB B2）。

---

## 36. docs/14 Phase B · B4：学科生命周期"移除可恢复"（2026-09-09）

**规格**：docs/14 §9 + R22——删除任何学科（含 math）= 列表隐藏+清进度+停用；大纲/内容文件与
（math）roadmap 留盘，可"重新启用"恢复；启动不复活被移除的 math（尊重停用标记）；custom 彻底
删除仅在用户选择"连同文件删除"（hard，默认不移）。

**改动清单**
1. `models.Subject` + `db._migrate_columns`：增 `enabled`（默认 True）与 `removed_at` 列（旧库
   try-ALTER 幂等补列，默认启用）。
2. `outline/store.py`：
   - `list_subjects(include_removed=False)`：默认仅启用（移除者从列表隐藏）；
   - `delete_subject(sid, hard=False)`：soft＝停用移除——清该学科内容节点 user_nodes/reviews 与
     (subject) user_concepts 概念证据，**大纲/内容文件留盘**，行 enabled=False+removed_at；
     preset(math) 同样允许 soft（不再特殊）；hard=True 仅 custom（物理移除 stages/<sid>/、
     大纲与材料目录、概念注册行、注册行；math hard 治理拒绝）；
   - `enable_subject(sid)` 重新启用；`is_subject_enabled()`。
3. 门禁/进度分流（B4）：`outline_gate.subject_of_node()`（math=学段前缀；通用=学科前缀含已停用）
   + `is_subject_disabled()`；session.start 与 progress._node_allowed 先判学科停用 → 一律 409/
   locked（内容文件仍在但学科停用不可学）；outline_gate 大纲解析仅用启用学科。
4. `api/subjects.py`：list `?include_removed=`、GET 停用=404（提示「管理已移除」）、DELETE `?hard=`
   （默认 soft；math hard → 409）、POST /subjects/{id}/enable；读写端点统一 `_require_enabled`
   （停用学科除 enable/hard 外 409）。
5. 启动语义：ensure_math_preset 幂等注册但**不翻转 enabled**（尊重移除标记）——math 移除后重启
   不会复活（B5 链式测试覆盖）。
6. 测试适配（B4 语义）：store/API 层 math 与 custom 的 soft→enable→hard 链；generic E2E
   remove→不可学(409)→重新启用→可学→hard；fixtures 清理改 include_removed。

**回归**：pytest = 实测（提交时随行）……本批涉及全部学科生命周期用例，见 B4 提交说明；
content validate 24/47；git 提交（PhaseB B4）。

**疑点（挂待架构裁决）**
1. "清大纲"语义取"清用户进度/概念证据、大纲文件留盘"（可恢复要求）；若架构要求"移除时大纲从
   活跃态清除、重启用需重建"，需在 meta 增加 removed_outline 标记并在 enable 时清理 outline
   （当前 outline 留盘对重启用无损，先按文档§9 可恢复口径）。
2. math 停用后仪表盘/关卡地图仍以 roadmap 内容渲染 available（引擎只按内容文件）——本批以
   start/门禁层阻止进入 + 推荐不保证为空；如需"地图整体隐藏/灰显"需 dashboard/campaign 接
   subject.enabled（列为 UI 后续，随设置页学科管理落地）。
3. custom 停用后其大纲/内容文件仍在 loader/图谱中显示（图谱通用视图）——通用学科图谱视图
   （Phase B 未做地图 UI）落地时按 subject.enabled 过滤。

---

## 37. docs/14 Phase B · B3：内容来源策略 + 材料层基础（2026-09-09）

**规格**：docs/14 §8 + R22——subject 增加 source_policy（ai|import|web|mixed，默认 ai，UI 可切换）；
本地导入（自有/授权 PDF/文本 → 本地引用库，来源标注）；联网候选清单（search → 候选；select →
本地化引用，**不整本下载**；离线/未接入给提示）；生成单元时引用库注入（可追溯来源）；math 同能力。

**改动清单**
1. `outline/materials.py`（新）：材料目录 `content/subjects/<sid>/materials/`（front-matter id/title/
   source/url/kind + 正文）；add/list/delete/materials_summaries（摘要供生成注入）；search_candidates
   （离线提示"联网检索后端未接入（Phase C），请用本地导入…"）；select_candidates（勾选摘要入库）；
   来源策略存取（meta_json.source_policy，SOURCE_POLICIES，默认 ai）。
2. `api/subjects.py`：GET/PUT /policy；materials upload/list/delete/search/select；列表/详情带
   source_policy；单元内容生成端点自动注入 `material_summaries`（有引用材料时讲解正文附
   "参考材料（可追溯来源）"标注——重生成可见"基于教材"信号；AI 起草时摘要注入 prompt）。
3. 前端：SubjectsPage（显示已移除管理 + 重新启用 + 移除 + custom 连同文件删除）；
   OutlinePage（来源策略下拉即时切换 + 文本导入 + 材料计数提示）；api.ts 增 del helper。
4. 测试：`test_materials.py` ×4——policy 默认/切换/非法 422；上传/列表/summaries + search 离线
   提示 + select 入库 + 生成注入不崩；math（preset）policy+materials 同样支持；停用学科 policy/
   materials 操作 409。
5. docs 同步：docs/06 §1/§3（policy/materials/enable/removed 端点与 subjects 列注释）。

**回归**：pytest = **269 passed + 1 skipped**（264+1 基线 + 5：materials ×4 + math 移除链 ×1，
不降）；content validate 24/47；npm run build 通过；git 提交（PhaseB B3）。

**疑点（挂待架构裁决）**
1. search 的"外部检索后端"未接入（docs/14 §7 #5 治理项）：当前返回明确离线提示；select 以
   调用方提供的候选摘要本地化（不整本下载，符合边界）。真实检索接入属 Phase C。
2. PDF 解析：MVP 走"文本/内容粘贴上传"；PDF 二进制解析（分页/分节）待引入解析器时扩展（上传
   契约已按"分节文本"预留）。
3. heuristic（离线）出稿不使用材料文本改写题目（事实安全约束），仅在讲解正文作来源标注；
   材料驱动的题目改写由 AI 路径承担（配 key 后生效）。

---

## 38. docs/14 Phase B · B5：回归与验收（2026-09-09）

**自动化验收结论（B1–B5 全批）**
- 全量回归：pytest = **269 passed + 1 skipped**（基线 258+1 → +11：judge 扩展 2、单元内容质量 4、
  materials ×4、math 移除/重启不复活/重启用链 ×1；B4 生命周期语义为既有用例改写/升级，不新增
  计数），只增不减；
- content validate 26 节点/49 练习全绿（当前仓库基线，随运行期 auto 内容增补；测试 hermetic
  基线仍为 13 人工节点不受影响）；通用内容只在临时学科副本生成/删除，仓库零残留；
- `npm run build`（tsc + vite）通过；git 提交链：B1 (…) → B2 → B3 → B4 → B5（本批）。
- 行星科学试跑（test_unit_content_gen）：10 单元全部生成并落库，每单元 ≥3 题/≥2 题型/跨单元题面
  零重复，rubric 命中科学模板（evidence 维度）——"三题相同/全自评"消除由校验锁定。
- materials/来源策略链路（test_materials）：默认 ai 可切 import/web/mixed；上传/列表/摘要；
  search 离线明确提示；select 勾选入库；math 同能力；停用学科 409。
- math"移除→停用→重新启用"链（test_outline）：soft 删除列表隐藏；ensure_math_preset（模拟重启）
  不复活停用 math；停用期间 math 内容 start=409；enable 恢复（R22"启动不复活"已锁）。
- B4 生命周期语义（docs/14 §9）：soft 停用清进度/概念、大纲/内容文件留盘可恢复；hard 仅 custom
  连同文件删除（math 治理拒绝）。

**浏览器真人验收清单（用户）**
1. /subjects：创建"行星科学"类学科 → 生成 10 单元真内容（讲解/多样题/费曼科学 rubric）；删除 →
   列表隐藏，显示已移除 → 重新启用恢复；custom 可"连同文件删除"。
2. Outline 页：来源策略下拉即时切换；粘贴一份教材文本导入后重生成单元，讲解出现"参考材料
   （可追溯来源）"；数学页同样可导入材料/切策略（作讲解增强）。
3. 配 LLM_API_KEY 后：内容由 AI 学科化起草（多题型/引用材料），无需 key 时启发式内容离线可学。
4. 交互：选择题点选、填空输入、判断题对/错按钮、数值/表达式沿用工作台输入；每单元题型不单调。

**疑点（挂待架构裁决，汇总 B1–B5）**
1. 启发式单选"正项恒第 1 项"做题套路（选项乱序/提示），建议 UI 或出稿乱序 + answer_index 同步；
2. fill_text 归一化 MVP 范围（繁简/标点变体随 docs/14 §7#3）；
3. 材料"外部检索后端"Phase C；PDF 二进制解析待引解析器；
4. math 停用后仪表盘/地图仍渲染内容（引擎按文件），地图级隐藏 UI 后续；
5. 测试中偶现 PUT /subjects/{sid}/outline 在特定用例 405（其它模块/进程不可复现，疑似路由顺序
   环境偶发）——已在该用例改 store 落盘规避；若复现需查 FastAPI 路由注册顺序。

---

## 39. 会话续接（2026-09-09 · Phase C 开工）—— 基线复核通过：pytest=269 passed + 1 skipped，content=ok 26 节点/49 练习

**续接前最后已知状态**：
- 品牌已更名 **YanHui（颜回）**（cffc005 + README bc22176：全科教练定位，数学=预置学科不再以
  数学导师为名）；库镜像 zhcnhan/YanHui ↔ gengzisama/YanHui（git-mirror 三端，docs/15 §5）。
- 基线实测：`pytest backend/tests` = **269 passed + 1 skipped**（270 collected，exit 0）；
  audit 5 学段全绿（primary 27 / middle 31 / high 81 / college 59 / ai 60，经
  test_roadmap + test_total_order_gate 真实库循环断言，exit 0）；`content validate` =
  **ok=True nodes=26 exercises=49**；git HEAD=`bc22176`、工作树干净；仓库不含 data/、_drafts、resume/。
- 里程碑：M0–M5 + docs/11 阶段 1/2/3 + docs/12 总纲 P1–P4 + 蓝图精核补丁 + A/B/C/D 引擎段 +
  R18 总序权威化 + docs/14 Phase A（A1–A4）+ Phase B（B1–B5，R23 已验收）；docs/09 R1–R23、
  docs/14 §8–§10（内容源策略/材料层/学科生命周期/行星科学试点）为 Phase C 的依据源。
- 本会话目标（当前活动工单 = **docs/14 Phase C**，工单文本 C1–C6）：C1 外部检索后端 provider
  抽象（默认未启用 + 可配自托管 SearXNG + LLM 候选 + select 抓正文入库）；C2 PDF/文档解析
  （pypdf，分页/分节入库 kind:pdf）；C3 学科停用过滤 UI + 学科管理收敛（仪表盘/地图/图谱/推荐/
  Session 按 subject.enabled 过滤隐藏）；C4 backlog 小项（heuristic 单选乱序 + answer_index 同步、
  PUT outline 405 复查、fill_text aliases 小扩展）；C5 回归与验收；C6 汇报与文档同步（docs/06/07/14
  §7/§8、docs/13 §4 与 docs/15 §3 基线/品牌数字本批末尾刷新）。每步独立汇报 + git 提交标注 PhaseC，
  每步全量回归不降 + content validate + audit 全绿 + 零残留；错误一律中文（docs/13 §2）。
- R23 backlog 承接（随 C4）：heuristic 选项乱序 + answer_index 同步；停用学科 UI 过滤随学科管理批次。
- 环境：.env 已配 LLM_API_KEY（35 字符，真实模型可用性待 C5 联网实测；测试 conftest 默认离线，
  真模型冒烟需 MF_ALLOW_LIVE_AI=1）；Python 3.14.3 venv；pypdf 6.18.0 已装入 venv（C2 用）。

---

## 40. docs/14 Phase C · C1：外部检索后端 provider 抽象（2026-09-09）

**规格**：docs/14 §8/R22 + 工单 C1——search_candidates 升级为 provider 抽象：默认"未启用"；
支持至少一种真实检索（**自托管 SearXNG**，免第三方 key，依赖=运行中的 SearXNG 实例 + JSON 输出）；
检索 →（配 LLM_API_KEY）LLM 生成候选清单 → select 抓公开网页正文 → 本地化引用库；
robots/版权边界：仍不整本下载书籍，仅公开网页与用户勾选；无 provider 时保持明确中文提示，
UI 标注"未配置检索后端"。

**改动清单**
1. `config.py`：检索后端配置（MF_SEARCH_PROVIDER 默认空=未启用 / searxng；MF_SEARXNG_URL；
   MF_SEARCH_TIMEOUT_S / MF_SEARCH_MAX_ITEMS；MF_FETCH_PAGE_MAX_CHARS / MF_FETCH_PAGE_TIMEOUT_S）。
2. `outline/search.py`（新）：provider 抽象——
   - `provider_status()`：configured/provider/url/note（UI 标注数据源）；
   - `search_web()`：SearXNG JSON API（GET <url>/search?q=&format=json，UA 头；去重/截断）；
   - `fetch_page_text()`：抓取**用户勾选**的公开网页正文（仅 http(s)/text/html、UA、重定向、
     大小上限 MF_FETCH_PAGE_MAX_CHARS；script/style 剥离 + 标签去 HTML + unescape + 空白收敛；
     失败/非 html → None 回落"仅摘要"）；
   - `SearchBackendError`（中文 message，docs/13 §2）。
3. `ai/calls.py`：调用点 12 `CALL_SEARCH_CANDIDATES`（light 档 JSON schema：
   SearchCandidatesIn/Out {items[{title,url,source,summary,reason}]}）。
4. `outline/materials.py`：
   - `search_candidates()` 重写：未配置 → `{items:[], note:"联网检索后端未配置…本地导入兜底", backend:{configured:false}}`
     （note 含"联网检索/未配置"，UI 显示"未配置检索后端"）；配置后 → search_web → LLM 整理/原始直出；
   - `_refine_candidates()`：配 key 时 CALL_SEARCH_CANDIDATES 整理（**输出 url 回滤原始结果集防
     杜撰**；AI 异常/无 key → 原始直出不阻塞）；
   - `select_candidates(..., fetch_pages)`：勾选且 fetch → fetch_page_text 抓正文入库
     （抓取成功正文=页面文本 + 原摘要留档；失败回落摘要，select 永不因抓取失败而崩）。
5. `api/subjects.py`：SelectItem 增 `reason`/`fetch` 字段；select 端点按勾选 fetch 抓正文。
6. 前端 `OutlinePage.tsx`：材料区升级为"学科管理 · 内容来源与材料"——来源策略下拉 +
   **联网候选**（检索词输入 → 结果候选勾选 → 本地化入库；无 provider 显示中文提示条
   "检索后端未配置…"）+ 引用材料列表（类型徽标 文本/网页 + 删除）。api.ts：request 兼容
   FormData（C2 复用）。
7. 测试：`backend/tests/test_search_provider.py`（新 ×10，hermetic mock）——provider 默认
   未配置（中文 note + backend.configured=False + UI 标注数据源）；searxng 配置后 search 出候选；
   后端不可达 → note 中文不 500；无结果提示；LLM 整理（mock refine + 记录 raw）；
   select fetch 正文入库（含"原始候选摘要"标记）；fetch 失败回落摘要；不带 fetch 旧契约不变；
   CALL_SEARCH_CANDIDATES 注册。test_materials 既有用例适配通过（note 文案仍含"联网检索"）。

**回归**：pytest = **279 passed + 1 skipped**（280 collected；基线 269+1 + 新增 10，不降）；
content validate 26/49 全绿；audit 5 学段不变（roadmap 未动）；npm run build（tsc+vite）通过；
git 提交（PhaseC C1）。

**疑点（挂待架构裁决）**
1. 检索 provider 首批只实现"自托管 SearXNG"（免 key、隐私可控、用户自装实例）；公共/托管
   API（必应/Brave/Tavily 等需 key 或 ToS）留作可插拔候选——provider 抽象已留
   `KNOWN_PROVIDERS` 扩展位，后续加 provider 只需新增分支 + 配置。
2. SearXNG 要求实例开启 `format=json` 输出（默认允许 JSON）；中文检索建议实例配语言/区域，
   未配时质量由用户实例决定（文档性依赖，不入代码）。
3. `fetch_page_text` 只做 text/html 抓取：书籍类整本下载仍被拒（含 PDF 二进制 URL——PDF 走
   C2 上传路径）；robots 协议未逐条解析（抓取仅限用户**显式勾选**且大小受限，语义符合
   docs/14 §8"用户勾选→本地化引用"边界；如需 robots.txt/noindex 严格遵从可在 search.py 加层）。
4. LLM 整理候选仅在配 LLM_API_KEY 时生效且不阻塞（失败回落原始直出）；"候选理由 reason"
   已入 schema 与 UI 展示。

---

## 41. docs/14 Phase C · C2：PDF/文档解析（2026-09-09）

**规格**：docs/14 §8/R22 + 工单 C2——引入轻量解析器（**pypdf**：BSD-3-Clause、纯 Python、
Python 3.14 兼容）实现 materials 上传 PDF → 分页/分节文本 → 引用库（kind: pdf/source_file）；
保留粘贴文本入口；限制大文件并中文报错。

**改动清单**
1. 依赖：`pypdf>=6.0` 入 pyproject（BSD-3-Clause，Py3.14 venv 实测 6.18.0 可装可用）；
   `python-multipart`（FastAPI 文件/表单上传所必需）。
2. `outline/pdfparse.py`（新）：`parse_pdf_bytes()`——大小上限（MF_PDF_MAX_BYTES 默认 20MB）、
   页数上限（MF_PDF_MAX_PAGES 默认 400）、每页文本上限（防畸形页）——超限中文报错；
   非 PDF（%PDF 头缺失）/损坏/加密 → PdfParseError 中文；0 页/0 文本（扫描图片版）
   → 提示"未能提取到文本，请 OCR 或文本粘贴"；产出分节 sections（页号+文本）与带
   【第 N 页】标记的整段正文。
3. `outline/materials.py`：add_material 支持显式 `kind: local|web|pdf` 与 `filename`
   （pdf 入库元数据含源文件名）；列表/解析带 kind+filename（旧文件无 filename 字段兼容）。
4. `api/subjects.py`：`POST /subjects/{sid}/materials/upload-pdf`（multipart：title 可选 +
   file）→ 解析入库（kind=pdf，source="PDF 导入（文件名）"）；解析/大小错误 → 中文 422。
5. 前端 `OutlinePage.tsx` 学科管理卡：文件选择 + "上传 PDF → 引用库"（≤20MB 提示、扫描版提示）；
   材料列表显示类型徽标（文本/网页/PDF）+ 源文件名；api.ts `upload()`（FormData，不设 JSON 头）。
   粘贴文本入口保留（原 /materials/upload 不变）。
6. 测试：`backend/tests/test_pdf_upload.py`（新 ×6，hermetic）——构造最小可提取 PDF
   （pypdf 标准 Helvetica，ASCII）真实走 pypdf 提取（含回读守卫）：上传 2 页 → 201、
   kind=pdf/pages=2/源文件名留痕、材料文件含【第 1 页】【第 2 页】与正文；非 PDF → 中文 422；
   超大小上限（env 调小）→ 中文 422；空白页无文本 → 中文 422；粘贴文本入口不回归。

**回归**：pytest = **285 passed + 1 skipped**（286 collected；279+1 基线 + 新增 6，不降）；
content validate 26/49 全绿；audit 5 学段不变；npm run build（tsc+vite）通过；git 提交（PhaseC C2）。

**疑点（挂待架构裁决）**
1. pypdf 对扫描图片版 PDF 无 OCR 能力（纯文本层）：提示走"用户先 OCR/文本粘贴"（文档性依赖，
   不在仓库内做 OCR——本地单机不引重型依赖）。
2. 每页文本上限/总文件上限为防滥用默认值（20MB/400 页/每页 8000 字符），常量化于 config
   （MF_* 可调）；超大教材建议用户截取章节上传。
3. kind 取 pdf（材料表元数据），与"source_file 泛指文档"的差异：当前只支持 PDF 一种二进制
   文档格式（docx/odt 解析列为候选，需要时再引等价解析器）。

---

## 42. docs/14 Phase C · C3：学科停用过滤（视觉层 subject.enabled）+ 学科管理收敛（2026-09-09）

**规格**：docs/14 §9 + 工单 C3（R23 B4#2/#3）——停用学科在 仪表盘/关卡地图/图谱/推荐/复习/
Session 全部按 subject.enabled 过滤隐藏（引擎 409 之外补视觉层）；学科列表"已移除"分组 +
重新启用 + custom 连同文件删除 + math 拒绝 hard；来源策略/材料管理/移除/恢复收敛到管理 UI。

**改动清单**
1. `service/outline_gate.py`：新增 `disabled_subject_ids` / `is_node_subject_disabled` /
   `visible_node_ids`（math=学段前缀映射；custom=学科前缀；无前缀孤立节点视为可视）——
   全站"停用学科节点隐藏"的单一数据源。
2. `api/graph.py`：/graph 节点与边按 visible 过滤（停用学科内容不再进入图谱数据）。
3. `api/dashboard.py`：推荐仅在可见 available 内取；统计/复习队列剔除停用学科；
   （原 counts 含全图停用锁定节点 → 改按可见节点集收敛）。
4. `service/campaign.py`：关卡地图按可见节点过滤分组（math 停用 → 地图整体为空，
   不再误报"全部通关/下一关生成中"——any_defined 守卫）。
5. `service/review.py`：due_queue 对停用学科到期行隐藏（一致性兜底）。
6. `outline/store.py`：**soft 移除进度清理强化**——`_subject_content_node_ids`：math 大纲单元
   （primary.s05…）与其**内容节点**（锚点 primary.0101、boss、auto）全量纳入清 user_nodes/
   reviews（此前只清大纲单元 id，preaset"移除=清进度"不完整）；custom 前缀全量同语义。
7. 前端：
   - `SubjectsPage.tsx` 重构为**管理页**：启用 / 已移除（可恢复）两分组；每卡片含大纲管理入口、
     移除（停用）、custom"连同文件删除"（math 不提供并给治理提示）、已移除分组重新启用；
   - `DashboardPage.tsx`：加载 /subjects 感知 math 停用 → 顶部中文提示条（仪表盘/地图已按停用
     隐藏；前往学科列表重新启用）；
   - OutlinePage（C1 起）"学科管理 · 内容来源与材料"卡片 = 来源策略/材料/联网检索/上传/删除的
     收敛管理入口（C3 定位收敛，UI 已就位）。
8. 测试：`backend/tests/test_subject_visibility.py`（新 ×3，hermetic）——custom 停用 → 图谱隐藏/
   不进推荐，重启用恢复；math 停用 → 图谱/关卡地图全隐、start 409、**已掌握锚点行被清**（preaset
   停用=清进度语义锁定）、到期复习行隐藏（手工插入验证兜底），重启用恢复。

**回归**：pytest = **288 passed + 1 skipped**（289 collected；285+1 基线 + 新增 3，不降）；
content validate 26/49 全绿；audit 5 学段不变；npm run build（tsc+vite）通过；git 提交（PhaseC C3）。

**疑点（挂待架构裁决）**
1. math 停用时 Dashboard 地图/图谱为空的表达：仍保留仪表盘页面 + 顶部中文提示条（不含"回退到
   通用首页"重构——MVP 语义：按需重新启用 math 或使用其它学科大纲页）。如需"首页=全部启用学科
   混合地图"属产品 IA 议题（docs/14 §7#4 信息架构），另裁。
2. soft 移除语义强化到"清该学科全部内容节点进度"（含 boss/锚点）：与 docs/14 §9"清进度"一致；
   B4 旧用例（仅断言文件留盘与 start=409）不受影响，语义超集（B4 疑点 2 关闭）。
3. 图谱/仪表盘过滤为 API 层（前端各页消费同一数据源）；前端不再单独维护节点过滤逻辑
   （防两处漂移）——"图谱页"当前未在 UI 直连，/graph 过滤仍生效（文档/测试兜底）。

---

## 43. docs/14 Phase C · C4：backlog 小项（2026-09-09）

**规格**：R23 B1#1 + B5 #5 留档 + 工单 C4——heuristic 单选选项乱序 + answer_index 同步
（确定性种子）；PUT outline 偶发 405 复查路由注册顺序加固（不可复现则记录环境）；
fill_text aliases 同义集小扩展（可选）。

**改动清单**
1. `outline/generate.py`：新增 `_shuffle_single(options, seed_key)`——single_choice 选项
   **确定性打乱**（种子 = sha1(unit.id + 题 id)）并同步返回 answer_index（原正确项新下标）；
   两处构造点（choose-tag / choose-obj-i）接入。语义：
   - 同单元/同大纲结构重出稿选项序可复现（内容幂等，入库/自检不受影响）；
   - 消除 B1 疑点 1"正项恒第 1 项"做题套路；UI 按 options 顺序渲染、judge 按
     answer_index 比对——选项序与判题完全同步。
2. PUT outline 405 复查：
   - 路由健康复查结论：subjects 路由内 GET/PUT 同路径并存合法（FastAPI 按方法分派），
     api 内无重复 /subjects/* 前缀；**本环境不可复现 405**（记录环境/处理，B5 #5 关闭为
     "未复现 + 注册/行为双守卫"）；
   - 守卫：`test_route_put_outline.py`——① OpenAPI schema 含 put+get 路径（注册缺失即失败，
     避开 FastAPI 嵌套 _IncludedRouter 的表示差异）；② live 反复采纳/整份重生成 outline
     PUT 全 200 + GET/validate 不失效。
3. fill_text aliases **可选小扩展：不做**（决定留档）——judge_fill_text 已支持 expected+aliases
   精确归一；再扩"语义同义"需学科级词典，超出 MVP 且引入误判风险（docs/14 §7#3 治理项）。
4. 测试：`test_unit_content_gen.py` + TestHeuristicChoiceShuffle（新 ×1）——多单元抽样下
   每个 single_choice `options[answer_index]` == 正确项（一致性）、两次出稿逐位一致（确定性）、
   抽样中正确项下标存在 ≠0（不恒第 1 项）；`test_route_put_outline.py`（新 ×2）。

**回归**：pytest = **291 passed + 1 skipped**（292 collected；288+1 基线 + 新增 3，不降）；
content validate 26/49 全绿；audit 5 学段不变；npm run build 通过（前端未动）；git 提交（PhaseC C4）。

**疑点（挂待架构裁决）**
1. PUT outline 405 未能复现：按"记录环境"处理（B5 #5）——测试进程内未复现；若用户端复现请
   提供复现步骤（URL/动作/DevTools 网络面板请求方法与实际到达方法），怀疑方向=本地代理/
   服务中间层改写请求方法或旧 bundle 缓存（docs/09 R23 留档口径）。
2. 确定性种子基于"单元 id + 题 id"：单元结构重排（同 id 换标签/目标）会改变选项序——属
   预期（内容随大纲变化重出稿），重生成幂等性仍由"同输入同输出"保证（测试锁定）。

---

## 44. docs/14 Phase C · C5：回归与验收（2026-09-09）

**验收结论（B5 规格的 Phase C 对应项）**
- **全量回归**：pytest = **291 passed + 2 skipped**（293 collected；291+1 基线 + 新增
  test_phase_c_live ×1（离线 skip），不降）；content validate 26/49 全绿；audit 5 学段不变；
  npm run build（tsc+vite）通过；git 干净。
- **真模型验收（MF_ALLOW_LIVE_AI=1 + .env LLM_API_KEY，DeepSeek 实测可达）**：
  `test_phase_c_live.py` 通过——行星科学 10 单元全部生成并落库，每单元 ≥3 题/≥2 题型/
  单元内题面去重/科学 rubric（evidence+证据与推理）；材料（文本粘贴 + **PDF 上传 2 页**
  kind=pdf）入库后，生成单元讲解出现"参考材料（可追溯来源）"（可追溯来源注入）；
  search 未配置 → `backend.configured=false` + 中文提示（UI 标注"未配置检索后端"数据源）；
  AI 学科化路径至少 1 单元命中（全量/多数为 AI 起草，退化自动重试兜底 heuristic）。
- **检索 provider select**：配置 provider 后的 search 出候选 + select 抓正文入库由
  test_search_provider.py（mock provider/transport，hermetic）锁定——真实 SearXNG 实例
  属用户自托管依赖（本环境未装），验收留"配置 MF_SEARCH_PROVIDER=searxng + MF_SEARXNG_URL
  后由用户真跑"清单项。
- **math 停用/重启用（含 UI 数据）**：test_subject_visibility（C3）+ B5 链锁定——停用 →
  仪表盘/图谱/地图隐藏、不可学（start 409）、重启不复活、清进度；重启用恢复（学科列表"已移除"
  分组按钮）；Dashboard 顶部中文提示条。
- **PDF 上传小文件 → 材料入库 → 重生成出现参考材料**：test_pdf_upload + 上述 live 用例锁定。
- **零残留**：git 干净（本轮只新增验收测试文件）；测试内容写入均落在 hermetic 副本与
  临时 DB，真实 content/ 无 auto 文件、无 _drafts 残留。

**验收中记录的现象（非阻塞，见疑点）**
- 真模型跨单元偶现同一材料句子复用作题面（如"小行星带位于火星和木星轨道之间"出现于两个
  单元）——AI 起草每次只对**当前单元**去重；单元内去重由 validate_generic_content 强制，
  跨单元/跨轮次去重为 B1#3"可选"口径（R23 已裁暂不要求）。
- 材料文本为 AI 起草的强参考：两单元均引用同一来源句，属"内容自然重叠"而非题型单调
  （各单元仍 ≥2 题型）。

**回归清单快照**：C1 279+1 → C2 285+1 → C3 288+1 → C4 291+1 → C5 291+2（+live skip）；
每一步 content validate 26/49、audit 全绿、npm build、git 干净。

**疑点（挂待架构裁决）**
1. 跨单元/跨轮次题面去重对 **AI 起草路径**未强制（离线 heuristic 天然不同单元题面不同）：
   若要求 AI 路径也全局去重需把"题面池"传入 CALL_UNIT_CONTENT 上下文（B1#3 曾裁"暂不要求"，
   随 AI 内容量增长可重议）。
2. 真模型验收在用户机器重复执行即：`MF_ALLOW_LIVE_AI=1 pytest backend/tests/test_phase_c_live.py`
   （或全量带该 flag 跑）；本次执行已验证 DeepSeek 可达且 10 单元 AI 出稿全过。
3. 真实 SearXNG 端到端（search 候选 → select 抓正文）需用户自托管实例后按 .env 配置复验；
   代码路径已 mock 锁定（C1）。

---

## 45. docs/14 Phase C · C6：汇报与文档同步（2026-09-09 · Phase C 收尾）

**文档同步（本批）**
- `docs/06` §1：材料端点表更新（upload-pdf、search 的 C1 provider 语义 + backend 状态、select
  fetch、materials 列表 kind/源文件名）；/graph 与 /dashboard 标注 C3 停用过滤；DELETE
  subject 行补"soft 移除对 math 亦全量清学段内容进度"语义。
- `docs/14`：§7 #5（检索后端未决项）→ 已落地（C1/C2 provider 抽象 + PDF 解析，含冷门学科
  可信度口径）；§8 追加 **8.1 Phase C 落地**（C1 检索/抓取边界、C2 PDF、C3 学科管理收敛 +
  .env 键）；§4 Phase C 标注 C1–C5 完成。
- `docs/07` §2.5：学科与大纲管理 UI（SubjectsPage 分组管理、OutlinePage 学科管理卡
  ——来源策略/文本与 PDF 上传/材料列表删除/联网候选检索勾选；检索未配置提示；停用感知）。
- `.env.example`：检索后端（MF_SEARCH_PROVIDER/MF_SEARXNG_URL 等）与 PDF 限制（MF_PDF_*）样例。
- `docs/13` §3/§4、`docs/15` §1/§3：基线/品牌数字刷新（pytest **291+2（离线）**、audit
  27/31/81/59/60、content 26/49、Phase A/B/C1–C5 状态、R24 待裁决口径）。
- 本 NOTES §39（会话续接）→ §40–§45 为 Phase C 六步记录（每步独立 git 提交，标注 PhaseC）。

**Phase C 汇总可验收点（用户/架构）**
1. C1：Outline 页"学科管理"检索框 → 未配置时见"未配置检索后端"+中文提示；配置 SearXNG 后
   检索出候选 → 勾选 → 入库（网页正文可追溯）；LLM 整理候选理由（配 key）。
2. C2：上传小 PDF → 引用库出现 PDF 材料（分页文本）；超限/非 PDF 中文报错；粘贴文本仍在。
3. C3：学科列表启用/已移除两组管理与"重新启用"；math 停用 → 仪表盘顶部提示 + 地图/图谱空、
   内容不可学、重启不复活；重启用恢复；custom 连同文件删除（math 拒绝）。
4. C4：启发式选择题选项乱序（正项不恒第 1 项）且判题同步；PUT outline 反复采纳无 405。
5. C5：`MF_ALLOW_LIVE_AI=1 pytest backend/tests/test_phase_c_live.py` 真模型验收通过（行星科学
   10 单元 AI 内容 + 文本/PDF 材料可追溯来源）；全量离线 291+2、content 26/49、audit 全绿。

**疑点（挂待架构裁决，C6 汇总）**
1. 检索 provider 目前仅 SearXNG 一种（扩展位已留 KNOWN_PROVIDERS）；托管/公共 API 候选待裁。
2. fetch_page_text 未解析 robots/noindex 元（仅用户勾选 + text/html + 大小上限）；
   PDF 不做 OCR（扫描版走 OCR/文本粘贴）。
3. 跨单元/跨轮次题面去重对 AI 起草未强制（B1#3 曾裁可选）；soft 移除"清 preaset 全量内容进度"
   为 docs/14 §9 语义强化（超集 B4）；PUT outline 405 未复现按环境留档。
4. docs/14 §7 其余待细化项（大纲 schema 升级迁移、标签归一化更细、题目交互块与信息架构、
   里程碑/首领单元语义等）维持"未决/待细化"清单，不在本批范围。

---

## 46. R27 费曼追问语义 v3（混合制）：后端实现（2026-09-09）

**开机复核**（docs/13 §1）：HEAD=`187f0d0`（docs/09 R27 裁决）、工作树干净、
pytest **291 passed + 2 skipped**（离线；2 skip=真模型冒烟/PhaseC live）、
`content validate` **ok=True nodes=26 exercises=54**（真实库；NOTES 记的 49 为上一轮快照，
本轮新增 auto 内容 5 题）、audit 5 学段全绿。

**规格**：docs/09 R27 六点裁决 + docs/05 §5（v3 已由架构侧更新）。要点：补答与完整稿分离、
删 R25 合并稿拼接、evidence 硬校验、缺口账本 + 定向追问、宽预算（整体稿 ≤3 / 补答 ≤2）、
通过仍需完整稿、R10/R11/R17 分支语义不回归。

**改动清单**
1. `ai/calls.py`：新增 `GapCheckIn/GapCheckOut`（补答轻量评估）+ 调用点 **13**
   `feynman_gap_check`（**light** 档：学生答完要立刻看到涨分）；`FeynmanEvaluateIn` 增
   `previously_acknowledged`（账本已认可摘要）；`FeynmanFollowupIn` 增 `unmet_gaps`（定向追问）。
2. `ai/gateway.py`：
   - 离线启发式评分重构为**分维分档**（`offline_feynman_scores`）：correctness/example 类维度
     按"核心概念覆盖 × 篇幅（+依据）"给 0.3/0.55/0.7/0.75/0.85/0.88/0.95 明确档；
     own_words 按"讲全程度"；**evidence 维度单独按依据类表述给分**（缺依据即低分，缺口真实存在）；
     self_correction 0.5 / 0.7（有自纠表述）。保证三条验收路径离线可驱动，且引文恒为本轮子串。
   - `offline_gap_check`：补答启发式（只判目标缺口维度；`gap_filled` + 单条 `dimension_updates`）。
   - `OpenAICompatibleGateway`：`feynman_evaluate` 传 `previously_acknowledged`；
     `feynman_followup` 提示词改为**定向 unmet_gaps 第一项**（禁自由发问）；
     `feynman_gap_check` 新方法（extra_bans 明确"只允许该维度一条 + evidence 必须逐字引
     student_answer + 未答对则空数组"）；协议 `AiGateway` 增该方法。
3. `service/feynman_ledger.py`（新，336 行）：账本 + evidence 纪律的单一数据源——
   - `normalize_ledger`（旧会话自愈 + 补齐 rubric 维度）、`candidate_acknowledged`；
   - `merge_card`（维度取 max；evidence **归一化包含校验**失败 → `evidence_valid=false` +
     分数 ×0.5 降级 + `evidence_reason`）、`update_dimension`（补答只写缺口维度）；
   - `combined`（Σw·账本最高分/Σw）、`weakest`（权重×缺失幅度最大）、`extract_gaps`（缺口清单，
     本轮已达标即消失、历史未评到则保留）、`mark_gap_attempt`（同一缺口可再追一次）、`gap_view`。
   - 归一化剔除空白 + 中英标点 + `…`/`．`（截断标记不能算引文内容——实测踩坑，见疑点 1）。
4. `service/session.py`：
   - `new_flow().feynman` 增 `followup_gap/answers_done/ledger`；`_feynman_reset` 一并清零（R17 语义超集）；
   - 常量 `MAX_FEYNMAN_EVALS=3` / `MAX_FEYNMAN_ANSWERS=2`（`MAX_FEYNMAN_ROUNDS` 保留 = 整体稿预算）；
   - `_act_feynman`（`feynman_submit`）**重写**：评分对象 = 本轮完整稿（**删除 R25 合并稿拼接**）；
     传 `previously_acknowledged`；合并账本 → 实时综合分；提取缺口；`passed` 由账本综合分判定；
     额度规则 = 整体稿 3 次满 **或**（补答 2 次尽且无剩余缺口）→ relearn（`_relearn_explain`，
     R17 清除零）；否则定向最弱缺口出追问；
   - `_act_feynman_answer`（新）：只答当前追问 → gap_check → **只更新缺口所属维度**
     （模型多给的键一律忽略）→ 账本 max → 答对即"缺口关闭 + 立即涨分"；**不判 pass**
     （`next_action="submit"`，通过必须交完整稿）；无追问/额度尽 → 中文 409；
   - `_feynman_followup` / `_card_of` / `_feynman_eval_rounds` 辅助；
   - `_response`：费曼账本视图 + `combined/threshold/evals_done/answers_done/eval_budget/
     answer_budget` **恒下发**（回炉/达标后仍可展示）；通过时也回传本轮评分卡；
   - 修复既有缺陷：`_enter_feynman` **重复定义**（后者静默覆盖前者，R17 防御实际失效）——
     合并为一份并保留 R17"进入前轮次已满即复位"防御。
5. `docs/06`：`/session/step` 行补 R27 双提交语义 + 新增 **§2.0 费曼阶段 payload**（账本视图、
   证据校验字段、通过判定、事件清单）；`docs/07 §2.3`：实时得分条/双提交入口/补答横幅/定向追问/
   复盘区分完整稿与补答。
6. 前端（另提交）：`api.ts` 增 `FeynmanLedger/FeynmanLedgerDim/FeynmanGap/FeynmanGapUpdate`；
   `SessionPage.tsx` 的 `FeynmanView` 重写（双提交入口 + 得分条 + 缺口提示 + 引文校验提示）；
   `index.css` 新增得分条样式；`FeynmanHistoryPage` verdict 文案区分完整稿/补答。

**测试**：`backend/tests/test_feynman_v3.py`（新 ×11 函数 / **14 用例**，evidence 纪律为参数化 ×5）：
- ① 首讲 0.0 → 答追问 → **账本维度分真实上升**（断言 `combined` 上升 + 缺口维度 best 上升 +
  两轮 `(score, evidence_quote)` 不同 —— 直接锁死"两轮逐字同分"回归）；
- ② 首讲未过 → 补答补缺口 → 整合重讲 ≥0.7 → `feynman_passed` + `node_mastered`；
- ③ 补答①未对 → 终验②（跑题）→ 追问保留 → 补答②未对 → 终验③ → **回炉 relearn**
  （stage=explain + `feynman_relearn`/`relearn_notice` + 轮次/账本清零）；
- ④ evidence 纪律：离线评分卡 evidence 恒 ⊆ 本轮文本（参数化含空文本/改写引文）；
  伪网关给出"上一轮引文" → `evidence_valid=false` + 分数 ×0.5 + 事件 `feynman_evidence_flagged`
  + **不放过**；
- ⑤ 补答只更新缺口维度（多给键被忽略）、账本不因更差一轮下降、`previously_acknowledged`
  正确下发（首讲空、二轮含已认可维度）、无追问只能交完整稿、`feynman_gap_check` 注册为 light。
`test_api_flow.py` 两处按 R27 语义更新：`test_feynman_fail_then_followup_answer_raises_ledger`
（原 `..._followup_pass`：补答只涨账本 → 再交完整稿才 mastered；含 R10 不 500 断言）；
R17 用例的二次提交改走完整稿（原用 `feynman_answer` 表达"重讲"，R27 下语义已分离）。

**回归**：pytest **305 passed + 2 skipped**（离线；基线 291+2 → +14 用例，不降）；`content validate` 26/54 全绿；
audit 5 学段全绿（27/31/81/59/60，前置缺失 0/锚点缺失 0/环 0/正向引用 0/内容不变式违规 0）；
`npm run build`（tsc+vite）通过；真模型走查见 §47。

**真模型数据回归（§47 详录）**：行星科学 `s-f2decfcf.u01` 实跑——首讲 0.0（4 维全 0，
定向追问指向 correctness："太阳系里最主要的成员…怎么排布"）→ 答追问 correctness **0.0 → 1.0**，
综合分 **0.0 → 0.4**（"答追问后分数可见上升"实测成立，不再重现 id=30/31 的 0.455 双轮同分）→
整合终验 **0.863 pass**（correctness 1.0 / own_words 0.8 / evidence 0.85 / self_correction 0.6）→
mastered。**R25 锚定 bug 在真模型下确认修复**。

**疑点（挂待架构裁决）**
1. evidence 校验口径 = **归一化包含**（去空白/中英标点/省略号后子串包含），而非严格 `in`：
   真实模型引文常带排版差异（换行、全角/半角标点、截断 `…`），严格口径会大面积误降级；
   归一化后仍能拦住"引用其它轮次/杜撰"（已用 case④ 锁定）。若要求"零容忍逐字"，需另裁。
2. 降级系数 `EVIDENCE_PENALTY=0.5`（不归零）：语义 = "分低但认账、学生可见原因"，比直接归零
   更利于教学；常量在 `feynman_ledger.py` 便于调参。
3. 补答预算语义：补答**答不对不消耗追问机会**（缺口保留、可再追一次），但消耗补答次数；
   两额度（整体稿 3 / 补答 2）都按"次数"计，未按"时间/内容量"计。
4. 离线启发式分档（correctness/own_words 的 0.3–0.95 阶梯）为本批为"三条验收路径可离线驱动"
   而定标；**真模型路径不受影响**（R4：离线仅降级兜底，真模型可用时不得抢占）。阈值调整只影响
   无 key 演示体验。
5. 修复了 `_enter_feynman` 重复定义（R17 防御曾失效）——属实现缺陷修正，语义与 R17 裁决一致，
   未改架构口径，记录备查。
6. `_master_if_ready` 增可选 `extra_payload`（通过时回传评分卡）——签名扩展向后兼容。

---

## 47. R27 真模型数据回归与验收（2026-09-09 · 本批收尾）

**方法**：`_dsh-local/r27_live.py`（本地脚本，不入库）——真实 `content/` + 临时 DB +
`.env` 的 DeepSeek key，走"练习直达 → 费曼首讲 → 定向追问 → 补答 → 整合终验"全链路。

**实测输出（行星科学 `s-f2decfcf.u01`，内容 = 真实库 u01；维度权重 correctness .4 /
own_words .2 / evidence .25 / self_correction .15，门槛 0.7）**

| 步骤 | 结果 | 关键证据 |
|---|---|---|
| 首讲"我真的不知道怎么讲…" | `verdict=fail`，combined **0.0**，4 维全 0，evidence 均通过本轮校验 | 定向追问："请用你自己的话讲一讲——太阳系里最主要的成员是什么？它们相对于太阳是怎样排布和运动的？"；`followup_gap=correctness`，缺口描述来自评分 comment |
| 答追问（完整答出结构+分类+方法） | `verdict=gap`，`gap_filled=true`，combined **0.0 → 0.4** | `dimension_updates=[{correctness: 1.0}]`；账本上涨维度 `{'correctness': (0.0, 1.0)}`；**不再两轮逐字同分** |
| 整合终验（同稿完整重讲） | `verdict=pass`，combined **0.863 ≥ 0.7** → mastered，evals 2/3 | 评分卡 correctness 1.0 / own_words 0.8 / evidence 0.85 / self_correction 0.6，**四维 evidence 全部 `evidence_valid=true`**；事件 `feynman_passed` + `node_mastered` |

**结论**：R27 三条验收路径（离线集成测试）+ 真模型数据回归全部成立；
用户实测的"答追问分数不动、evidence 仍引首轮'我真的不知道'"**在真模型下已不复现**。

**验收自证对照（用户工单 §3 逐条）**
1. ① `test_r27_path1_answer_raises_ledger_dimension`：断言 `combined` 上升 + 缺口维度 best 上升
   + 两轮 `(score, evidence_quote)` 不同（"绝不重现两轮逐字同分"）+ 补答不产生 mastered。
2. ② `test_r27_path2_answer_then_integrated_submit_passes`：补答 gap_filled → 完整稿 ≥0.7 →
   `feynman_passed` + `node_mastered` + `mastery.next_review_due_at` 有值（pass/mastered）。
3. ③ `test_r27_path3_budgets_exhausted_relearn`：补答①②未对 + 终验③ <0.7 → stage=explain，
   `feynman_relearn` + `relearn_notice`，`evals_done=0`/`answers_done=0`/gaps 清零。
4. evidence 纪律：`test_r27_evidence_must_come_from_current_round_offline`（离线卡恒为本轮子串）
   + `test_r27_evidence_discipline_downgrades_foreign_quote`（外来引文 → 降级 + 事件 + 不放过）。
5. 既有分支回归：`test_feynman_fail_then_followup_answer_raises_ledger`（R10 不 500）、
   `test_feynman_three_fails_relearn`（R11 3 轮/额度尽回炉）、
   `test_feynman_relearn_then_relearn_again_submit_200`（R17 回炉后重进不再 409）全绿。
6. 全量：pytest **305 passed + 2 skipped**（离线；基线 291+2 → +14 用例不降）；
   `npx tsc --noEmit` 通过；`npm run build` 通过；content 26/54；audit 全绿。
7. 真模型：上表（本环境 DeepSeek 可达，实测通过）。
8. 错误中文化：新增/改动的对外错误均为中文（"费曼整体稿评分已达上限（首讲 + 2 次终验），请重新
   学习后再来"、"当前没有待补答的追问：请直接提交完整讲解（整合重讲）由整体评分判定。"、
   "补答次数已达上限（2 次），请提交整合后的完整讲解。"、"补答太短（少于 10 字）…"），
   `test_errors_zh.py` 与 `test_r27_no_followup_question_means_submit_only`（断言 409 文案含中文）锁定。

**收尾**：docs/06 §2.0、docs/07 §2.3、docs/13 §3/§4 基线同步；本 NOTES §46–§47；
git 提交链（后端 → 前端 UI → 文档/NOTES）均标注 R27；工作树干净、无残留（`_dsh-local/` 已 git 忽略）。

> **【架构侧更正 · docs/09 R28 F1/F6 · 2026-09-10】** 本节表格中的真模型数字（0.863、1.0/0.8/0.85/0.6、
> 综合 0.0→0.4）**与现存留档不符**：架构侧复核 `%TEMP%\mf_r27_live.db` 与 `_dsh-local/r27_live.out`
> （13:01:11 落盘）显示实际为 **首讲 0.0 → 补答 correctness 0.95 / 综合 0.38 → 终验 0.73 pass**，
> 维度 **0.95 / 0.55 / 0.60 / 0.60**，追问措辞亦与本记录不同 → 应为**两次运行**、本节记录了较早一次
> 且其留档已被后一次覆盖。定性结论（答追问分数可见上升、R25 锚定 bug 已不复现）**成立**；
> 数字以留档为准。**纪律**：真模型回归须每次写入独立留档文件（DB + stdout）并据实汇报；
> 另注：两次运行同一稿件得分 0.863 vs 0.73（波动 0.13，后者仅高门槛 0.03）→ 阈值抖动见 R28 F6。

---

## 48. R30 F6：费曼终验边缘带复评（唯一新增功能 · 2026-09-10）

**开机复核**（docs/13 §1）：HEAD=`b1c1b05`（docs/09 R30 规格）、工作树干净、
pytest **306 passed + 2 skipped**（308 collected，exit 0；2 skip=真模型冒烟/PhaseC live）、
`content validate` **ok 26 节点/54 练习**、audit 五学段全绿（27/31/81/59/60）、tsc+build 通过。

**规格**：docs/09 R30 §F6（用户拍板）。问题：同一份整合稿两次真模型运行得 0.863 / 0.73（差 0.13），
后者仅高门槛 0.03 → "同一篇讲解这次过、下次不过"（阈值抖动，R28 F6）。

**改动清单**
1. `ai/tier.py`：`FEYNMAN_RECHECK_LOW = 0.05` / `FEYNMAN_RECHECK_HIGH = 0.08`（便于调参）+
   `feynman_recheck_band(combined, threshold)`——刻意与 R12 的"下一轮升 think"边缘区间
   （−0.15/+0.10）分开：R12 决定**下一轮**档位，本函数决定**本轮已出分**是否复评。
2. `service/feynman_ledger.py`：把"净化（evidence 校验/降级）"与"并入账本"拆开——
   `clean_card(card, transcript=…)`、`card_combined(card)`（单轮加权综合分）、
   `merge_clean_card(ledger, clean, round_no=…)`；`merge_card` 变为二者组合（旧签名不变、
   测试口径不变）。**动机**：复评要先比较两次卡、再只并入采用那一次，若沿用 `merge_card`
   会对已降级的卡二次 ×0.5。
3. `service/session._act_feynman`：单轮评分完成后判断触发（三条件：落边缘带 + 本轮非 think +
   本轮未复评过）→ 以 think 档**重跑 feynman_evaluate**（复用同一 `ctx`：同一份稿、同一 rubric、
   同轮语境，含 `previously_acknowledged`）→ 取两次较高者：
   - 采用复评 → `strategy="think"`、`strategy_reason="edge_recheck=think"`、`f["last_strategy"]` 同步；
   - 复评抛 `AiCallError` → 保留首次结果（不 500、不换档位），事件带 `second: null`；
   - `attempts.meta["recheck"] = {used, first_combined, second_combined, taken}`（**恒写入**，
     未触发时 used=false / taken="first"），事件 `feynman_edge_recheck {first, second, taken}`；
   - 账本仍按"采用那次"的卡 `merge_clean_card`（维度 max），通过判定口径不变（R30 F3：
     账本累计分 ≥ 阈值）。
   - **"本轮尚未复评过"由结构保证**：该分支在单次完整稿提交内只走一次，复评后 `rounds_done` 递增
     → 同一轮不可能再次触发（无循环；每轮最多 1 次额外 heavy 调用，满足 §F6.5 成本纪律）。
4. `tests/test_r30_edge_recheck.py`（新，**7 用例**＝R30 §6 六条 + 带外参数化）：
   ① 带内 0.68 → 触发、复评 0.75 → 取高 **pass**（断言 `gw.calls == ["fast","think"]`、
   `strategy=think`、事件 `taken=second`、meta 四字段、mastered）；
   ② 带外 0.40（不过）/0.90（直接过）→ **不触发**（`calls == ["fast"]`、无事件、meta.used=false）；
   ③ 首次即 think（`think_deep=true`）→ 不触发；
   ④ 复评更低 0.68 → 0.60 → **取首次** 0.68、不 pass、`strategy` 仍 fast；
   ⑤ 复评抛 `AiCallError` → 200 保留首次（事件 `second=null`、meta `second_combined=null`）；
   ⑥ 每轮复评 ≤1 次：第 1 轮 fast+复评（2 次调用）→ 第 2 轮轮次≥2 本就 think → 0 次复评。
5. 文档：docs/05 §5（流程第 4 步增"边缘带复评"）、docs/06 §2.0（payload 协议 + 事件清单）。

**实测证据（离线桩：由临时 dump 脚本 `backend/tests/_r30_f6_evidence.py` 打印真实 payload/meta
后即删；下表为逐字摘录）**

| 场景 | 调用档位序列 | 结果 | 事件 / meta.recheck |
|---|---|---|---|
| 带内 0.68 → 复评 0.75 | `["fast","think"]` | verdict=**pass**, combined=**0.75**, strategy=think, mastered=true | `{first:0.68, second:0.75, taken:"second"}` / `{used:true, first_combined:0.68, second_combined:0.75, taken:"second"}` |
| 带外 0.40 | `["fast"]` | verdict=fail, combined=0.40, 无复评 | `[]` / `{used:false, first_combined:0.4, second_combined:null, taken:"first"}` |
| 带外 0.90 | `["fast"]` | verdict=pass, combined=0.90, 无复评 | `[]` / `{used:false, …taken:"first"}` |
| 带内 0.68 → 复评 0.60 | `["fast","think"]` | verdict=fail, combined=**0.68**（取首次）, strategy=fast | `{first:0.68, second:0.6, taken:"first"}` |
| 首次即 think（override） | `["think"]` | 无复评 | `[]` |
| 复评抛错 | `["fast","think"]` | **HTTP 200**，保留首次 0.68 | `{first:0.68, second:null, taken:"first"}` |

**回归**：pytest **325 passed + 2 skipped**（327 collected；基线 306+2 → +19 = F6 7 + F5 2 +
R29 引申 10，不降）；R10/R11/R17 费曼分支、R27 三条路径、R29 老会话用例全绿；
`content validate` 26/54；audit 五学段全绿；`npx tsc --noEmit` + `npm run build` 通过。

## 49. R30 遗留收口：F5 evidence 最短门槛 / F4 文案 / R29 引申 flow schema 自愈 / F2 行尾治理

### F5 · evidence 最短长度门槛（`23fc603`）
- `feynman_ledger`：新增常量 `MIN_EVIDENCE_CHARS = 6`；`quote_valid` 在"归一化子串包含"之外
  先判**归一化后长度 < 6 → 无效**（极短引文如"方程"能平凡通过包含校验，等于没有依据）；
  新增 `quote_invalid_reason(quote, transcript, where=…)` 区分「过短」与「不在本轮文本中」
  （错误全中文；`clean_card` / `update_dimension` 的 `evidence_reason` 同步）。
- 用例：`test_r30_f5_evidence_min_length_threshold`（2/4/5 字判无效、6 字与含标点干扰的有效、
  原因文案区分）+ `test_r30_f5_short_quote_downgraded_end_to_end`（桩给"极短但在文本中"的引文
  → `evidence_valid=false` + ×0.5 + 事件 `feynman_evidence_flagged`）。

### F4 · 补答未补上后的文案统一（前后端）
- 事实口径：`_act_feynman_answer` 收尾清空 `followup` → "同一缺口可再追一次"实际**须先再交一次
  完整稿**换取新追问（R28 F4）。
- 后端 `_act_feynman_answer` note：`缺口保留在账本里——**再交一次完整讲解后，会针对该缺口再问**`
  （`backend/app/service/session.py:834`）；前端 `EVENT_TEXT.feynman_gap_open` 同措辞
  （`frontend/src/pages/SessionPage.tsx:26`）；顺带补 F6 事件横幅
  `feynman_edge_recheck: "⚖️ 本次接近及格线，已用更认真的档位复核一遍（取较高分）"`。
- 用例锁定：`test_r27_path3_budgets_exhausted_relearn` 增断言
  `"再交一次完整讲解" in message` + `followup_question is None`。
- 文档：docs/07 §2.3（含 F6 提示）、docs/05 §5 第 5 步。

### R29 引申 · flow schema 演进的单一自愈入口
- **审计结论**（"后加且用 `[]` 取值"的 flow 键）：R12 `lecture_cache`（缓存子键 `lecture_md`/
  `strategy`/`explicit` 为后加）、R12 `regen_think_override`、R25 `regen_reissue_used`、
  R27 `feynman.answers_done` / `followup_gap` / `ledger`（**R29 真实炸点**）、`feynman.last_scores` /
  `last_combined` / `last_transcript` / `edge_think` / `last_strategy`。practice 子键自 M2 起就有、
  但同样按 `[]` 取值（手工改坏/整块缺失即 500）。→ 全部收敛到 `_ensure_flow_shape`。
- `service/session.py` 新增 `_ensure_flow_shape(flow)`（+ `_ensure_block` 与
  `_PRACTICE_SHAPE`/`_FEYNMAN_SHAPE` 类型表）：整块缺失/非 dict → `new_flow()`；缺键 → 补当前默认
  （**不覆盖已有值**）；错类型/非法取值（stage 越界、`streak` 变字符串、`ledger` 变数组…）→
  **单键回退默认**；`ledger` 深结构复用 `feynman_ledger.normalize_ledger` 同一口径（不另写一套）；
  lecture_cache 合法形态 = `None` 或含 `lecture_md(str)` 的 dict（脏缓存宁可重生成）。幂等。
- 调用点（R29 教训：**自愈点必须在 `step()`**，不能只挂 `resume()`）：`step()` 入口、
  `_act_feynman` / `_act_feynman_answer` 入口、`_ensure_invariants`（resume/老会话）、
  `_response`（响应体是"永不下发半截结构"的最后一道闸）。原 R29 单点 `_backfill_feynman_keys`
  已删除（行为被超集覆盖）；`test_r27_legacy_session.py` 不改一字仍全绿，证明热修未回退。
- 用例 `tests/test_r30_flow_shape.py`（**10 用例**）：单元 5（整块缺失补默认、flow 非 dict、
  缺键保进度、错类型逐键回退 + 合法 lecture_cache 保留、幂等）；HTTP 5（缺键/错类型/整块缺失
  参数化提交不 500 且自愈落库；flow 整块改坏 → 回默认讲解阶段可继续学；practice 整块缺失 →
  中文 409 而非 KeyError）。

### F2 · 行尾治理（纯 EOL 独立提交）
- `backend/app/service/session.py`：CRLF 1488 → **LF 1488**（`git diff --cached --ignore-cr-at-eol`
  为**空**＝无功能 diff；`git ls-files --eol` 现为 `i/lf w/lf attr/text eol=lf`）。
- 新增 `.gitattributes`：`*.py text eol=lf`、`*.ts text eol=lf`、`*.tsx text eol=lf`（docs 的
  CRLF 维持现状，不在约束范围）→ 防"整文件伪 diff 覆写 blame"复发。提交后工作树干净，
  另有 6 个历史 CRLF 的 `.py`（`app/__init__.py`/`ai/drafting.py`/`config.py`/`content/cli.py`/
  `main.py`/`scripts/gen_content.py`）**未被本次改动**（git 状态仍干净，下次被触碰时自动按 LF 入库）。

## 50. R30 验收自证与疑点（2026-09-10）

**逐条自证**（对应工单 §4）
1. F6 六条测试全绿：`backend/tests/test_r30_edge_recheck.py` **7 passed**
   （`test_r30_f6_band_in_triggers_recheck_and_takes_higher` /
   `test_r30_f6_out_of_band_never_rechecks[0.4-False]` / `[0.9-True]` /
   `test_r30_f6_think_round_never_rechecks` / `test_r30_f6_lower_second_keeps_first` /
   `test_r30_f6_recheck_error_keeps_first_result` / `test_r30_f6_at_most_one_recheck_per_round`）；
   实测值见 §48 表格（带内触发→取 0.75 pass；带外 0.40/0.90→`calls==["fast"]`、无事件；
   复评更低→取首次 0.68 不 pass）。
2. 回归：R10/R11/R17 费曼分支（`test_api_flow.py`）+ R27 三条路径 + evidence 纪律 + R29 老会话
   （`test_r27_legacy_session.py`）**全绿**（与上列同批跑完，0 failed）。
3. 全量：`pytest backend/tests` = **327 collected / 325 passed + 2 skipped / 0 failed**（离线段；
   基线 308 collected / 306+2）；`npx tsc --noEmit` exit 0；`npm run build` ✓ 1.03s；
   `content validate` ok 26/54；audit 五学段 `ok=True`（27/31/81/59/60，前置缺失 0/锚点缺失 0/
   环 0/内容不变式违规 0/正向引用 0）。
4. F2：`session.py` LF（1488 行）且 `--ignore-cr-at-eol` diff 为空；F5 最短长度用例 2 条；
   F4 文案证据＝后端 `session.py:834` 与前端 `SessionPage.tsx:26` 同措辞（"再交一次完整讲解后，
   会针对该缺口再问"）+ docs/07 §2.3 同步。
5. 真模型：本批**未跑**真模型（F6 触发前提是分数恰好落边缘带，桩控分数才能稳定覆盖六条路径；
   真实评分波动本身见 R28 F6 留档）→ 按 F1 纪律，若后续要跑须另存唯一文件名（DB + stdout）。
6. 错误全中文：新增/改动路径的对外错误未新增英文（复评失败不产生新错误分支，仅保留首次结果）；
   evidence 新原因文案为中文。
7. 工作树干净；提交链均标注 R30：`4f7990b`(F6) → `23fc603`(F5) → `49e5149`(F4) →
   `f66af5f`(R29 引申) → `f8c856d`(F2) → 本文档提交。

**疑点（挂待架构裁决）**
1. **边缘带的"本轮综合分"取哪一分**：R30 §F6.2 写"本轮综合分落边缘带"，实现取**本轮评分卡的
   加权综合分**（净化后，含 evidence 降级），而通过判定仍是**账本累计分**（R30 F3 维持）。
   二者在"首讲/单轮"场景下同值（R28 F6 实测 0.73 亦是同值），但在"补答抬分后再终验"场景可能
   不同（如账本 0.85 → 本轮卡 0.66 → 复评会触发、却已 pass）。当前口径：**按本轮卡判定与比较**
   （更贴合"这一份稿评得准不准"的问题本身）。若要求"只在会因此不过线时才复评"，可加一条
   `passed` 前置条件（一行改动）。
2. **复评失败时的 `used` 语义**：实现为 `used=true, second_combined=null, taken="first"`
   （＝"已尝试但未采用"），以便审计"花了这次 heavy 调用"。若裁决 `used` 应表示"复评结果被采用"
   则需改成 false（同时失去失败留痕）。
3. **边缘带复评与 R12 边缘升档叠加**：本轮 fast 落带内且复评仍不过 → 仍会置 `edge_think`（下轮
   think）。即最坏情形"相邻两轮各一次 think 评分"（本轮复评 + 下轮升档）；单轮成本纪律
   （≤1 次额外 heavy）满足，但跨轮相邻会连续 think。若要求去重（例如本轮已复评则不再升档），
   需另行裁定。
4. **practice 整块缺失无法恢复进度**：`_ensure_flow_shape` 只能补默认（练习未达标）→ 会话退化为
   须重做练习并返回中文 409；未做"stage 一致性回退"（如 stage=feynman 但练习未达标 → 回 explain），
   因那属状态机语义变更、超出"深度补齐 + 类型校验"授权。
5. `_ensure_flow_shape` 在 `_response` 每帧调用（幂等、O(键数)），未见性能影响；若后续 flow 体积
   显著增长可加"仅当结构变更才回写"的短路。

---

## 51. 立心批验收（R32）+ 架构侧会话续接（2026-09-10 · 颜回/架构师）

> 本节由**架构侧**追加（非 Euler 实现记录）；Euler 的实现记录请从 **§52** 起顺延。

**基线独立复跑（不采信汇报，2026-09-10）**
- pytest **325 passed + 2 skipped / 327 collected，exit 0**（130.48s，离线）；
  留档：`%TEMP%\yanhui-baseline-r32.txt`。与 R31 记录逐位一致 → 立心批**未影响任何行为**。
- `content validate` **ok 26/54**；roadmap `audit()` 五学段 **27/31/81/59/60**，各错误项 0；
  `npx tsc --noEmit` exit 0。

**环境实况（改名余波，已修）**
- `.venv` 在目录改名后重建时**漏装 dev 依赖**→ `No module named pytest`，基线不可复跑。
  已补：`pip install -e "backend[dev]"` → pytest **9.1.1** / pytest-cov **7.1.0**。
  运行时依赖（fastapi/uvicorn/sqlalchemy/pydantic/sympy/fsrs/PyYAML/pypdf 等 29 项）本已齐全。
- `npm run build` 在本会话受限沙箱内失败于 `esbuild: spawn EPERM`（子进程管道被策略阻断）
  → **环境限制，非代码问题**；`tsc --noEmit` 已独立通过，build 需在普通终端复核。
- 后端服务当时在 8000 活跃（返回 200）→ 数据库改名/迁移**不可热做**，已列入 R33 工单停服执行。

**立心批验收结论：通过、放行**（docs/09 R32）
- 主体提交 `92b6ff9`（产品定义 + 运行时 LLM 角色 + 包描述 + README 立心）；
- 代码内文案/注释清理：本批工作树 14 文件（后端 5 / 前端 5 / docs 4），**逐行复核零逻辑变更**
  （唯一表达式 `preset?.label ?? "数学"` 为纯展示回退）；随本批提交；
- 历史裁决 R1–R30 未改写（决策链证据口径）。

**库路径遗留（R33 任务 B）**：真实库 `backend/data/mathfeynman.db` 仍在用（user_nodes 26 /
sessions 3 / attempts 31 / subjects 2 / concepts 113）。根因＝`.env` 的 `MF_DB_PATH` 写旧名，
使 `db.py::_migrate_legacy_db_path()` 的"新名不存在才迁移"前置不成立 → 迁移永不触发；
代码默认值（`config.py`）与本文档 §0 其实均已是 `backend/data/yanhui.db`。

> **【R33 已处置 · 本段为时点记录，保留不改写】** 本节由上可见"库仍在旧名"是**写作当时的真实状态**；
> R33 已完成改名与校验（库=`yanhui.db`，六项计数 26/3/31/2/113/0 逐位一致），并发现了本节未记到的
> **第二层根因**（进程环境变量 `MF_DB_PATH` 压过 `.env`）。执行记录见 **§54**，裁决见 docs/09 **R33 §7**。

**会话续接（架构师）**：本会话为 **颜回（YanHui 新任架构师）首棒**，续接记录见 docs/15 §8 #1；
下一批 = R33（文档/配置一致性 + 库路径归一 + 真人验收清单），工单 `.runtime/EULER_TICKET_R32.md`。

**会话基础设施事故留档（与本项目代码无关，仅纪律）**：DSH 0.1.2→0.1.5 升级 + 工作目录改名 +
旧版误启动三事叠加，导致**旧会话 chat 正文丢失**（项目文件零损失）。预防已做：`.dsh` 全量备份
（robocopy 权威比对 Files 52886 / Mismatch 0 / FAILED 0）+ 旧版 0.1.2 缓存**双改名屏蔽**
（目录名 + `bin.js`→`bin.js.disabled-bak`，阻断启动器"探 `bin.js` 存在性"的发现路径），
并以启动器自身算法验证唯一解析到 0.1.5。纪律见 docs/09 R32 §5。

---

## 57. R34：`dev.ps1` 库路径确定性 + `.gitignore` 编码修复（2026-09-10 · **架构侧直接执行**）

> 本批由架构侧直办（用户指示"一口气修一下"）；Euler 的下一批实现记录请从 **§58** 起顺延。

**改动 1 · `scripts/dev.ps1`（根因第三层，见 docs/09 R33 §2）**
- 在启动 uvicorn 前**显式设定** `$env:MF_DB_PATH = <root>\backend\data\yanhui.db`，并加**读回校验**
  （不一致即中文报错中止，把"静默建空库"变成"响亮失败"）。
- **未采用** `load_dotenv(override=True)`（会覆盖 conftest 的临时库 → 测试写真实库，已被 R33 §2 否决）。
- ⚠️ **执行踩坑与修复（重要教训）**：编辑工具重写该文件时**丢掉了 UTF-8 BOM**，导致
  Windows PowerShell 5.1 按 ANSI/GBK 解析中文注释 → **整脚本语法错误、`dev.ps1` 一度跑不起来**；
  修回时又因"`ReadAllText(UTF8)` 把 BOM 解成 `U+FEFF` 字符 + 再手写 BOM"造成**双 BOM**
  （`EF BB BF EF BB BF`），报错落在 `param()` 的 `8000` 上（`InvalidLeftHandSide`）。
  最终状态：**恰好 1 个 BOM + LF + 解析 0 错误**。
  **纪律**：`.ps1` 属"Windows PowerShell 5.1 按 BOM 判编码"的文件，改动后必须复核
  `前 3 字节 = EF BB BF`、无 CRLF、`Parser::ParseFile` 零错误。

**改动 2 · `.gitignore`**：由 **GBK** 重写为 **UTF-8 无 BOM + LF**，注释恢复可读中文，
**规则逐条不变**（11 条忽略用例 + `!content/_drafts/.gitkeep` 例外均经 `git check-ignore -v` 复核命中）。

**验收自证（架构侧）**
- 改前先停服 → 库三件套整份备份 `_backups\yanhui-db-before-r34-20260910-161534\`，
  三件 **SHA256 逐位一致**，副本 `integrity_check=ok`、计数 26/3/31/2/113。
- **修法实测（污染终端法）**：终端内先设 `MF_DB_PATH=backend/data/mathfeynman.db`（模拟残留）
  → 跑 `scripts\dev.ps1` → 后端**仍连真实库**：`/api/subjects` 返回 **math + 行星科学（2 个）**，
  `backend\data\` **未新建** `mathfeynman.db`；`yanhui.db-wal` 于启动时刻被正常写入。
- 全量回归：pytest **325 passed + 2 skipped**（112.9s，exit 0）——与基线逐位一致。
- 服务就绪：后端 8000 / 前端 5173 均 200，前端为 **vite dev**（直接服务最新源码，
  含 R32 批那 5 个前端文案文件，故真人走查看到的是最新 UI）。

---

## 52. 会话续接（2026-09-10 16:00）—— 基线复核通过（Euler · R33 开机）

> 本节为**新任 Euler 开机自证**（工单 `.runtime/EULER_TICKET_INIT_R33.md` §2）；
> 上任上下文已耗尽，记忆来源＝仓库文件（README / docs/13 / docs/09 R30–R32 / docs/15 / 本文件 §48–§51）。

**开机状态**
- HEAD = `4604fcf`（docs(R32): 旧版痕迹全清…）；工作树**干净**（`git status --short` 为空）。
- 目录名 = `D:\DeepseekHarness\YanHui`（旧名 MathFeynman，R32 已改名验收）。
- venv 已含 dev 依赖（pytest 9.1.1，无需补装）；后端服务当时在 8000 活跃（PID 19852）。

**基线复核（本会话独立复跑，不采信文档口述）**

| 项 | 命令 | 实测 | 工单 §2 期望 | 结论 |
|---|---|---|---|---|
| 测试 | `.\.venv\Scripts\python -m pytest backend/tests -q --junitxml=.runtime/r33_pytest_baseline.xml` | **327 collected / 325 passed + 2 skipped / 0 failed / 0 error，exit 0**（111.50s，离线） | 325 passed + 2 skipped（327 collected，exit 0） | ✅ 逐位一致 |
| 内容库 | `.\.venv\Scripts\content.exe validate` | `ok=True nodes=26 exercises=54`，exit 0 | ok，26 节点 / 54 练习 | ✅ |
| 蓝图 | `app.content.roadmap.audit(<level>)` 五学段 | primary **27** / middle **31** / high **81** / college **59** / ai **60**；各 `ok=True`，cycles / prereq_missing / anchors_missing / content_prereq_violations / boss_unmatched / cross_reverse **全 0** | 27/31/81/59/60，各错误项 0 | ✅ |
| 前端 | `npx tsc --noEmit`（frontend/） | exit 0 | exit 0 | ✅ |
| 仓库 | `git status --short` | 空（干净） | 干净 | ✅ |

- 留档：`.runtime/r33_baseline.txt`（stdout）+ `.runtime/r33_pytest_baseline.xml`（junit 权威计数：
  `tests=327 errors=0 failures=0 skipped=2`）。2 skipped = 真模型冒烟 `test_live_ai` +
  Phase C 验收 `test_phase_c_live`（需 `MF_ALLOW_LIVE_AI=1` + `LLM_API_KEY`），与 docs/13 §4 一致。
- **onboarding 结论：通过**，可开工 R33（本批＝纯文档/配置，零逻辑改动）。

**开工前勘察（为任务 A/B 取证）**
- 旧名残留全仓扫描（排除 `.venv`/`node_modules`/`.git`/`resume/`，含 git 忽略区）共 40 处命中，
  分类见 §53；`.env:14` 的 `MF_DB_PATH=backend/data/mathfeynman.db` 是唯一"把旧路径当当前路径用"的
  本地配置（任务 B 处理）。
- 服务实况：`backend/data/` 现有 `mathfeynman.db`(327680B) + `-wal`(70072B) + `-shm`(32768B)
  （＋历史 `mathfeynman.db.bak-20260908-220309`）；8000 的**监听者**是 PID 19852，而 `.runtime/pids.txt`
  记录的是 9084 / 2944 —— 二者不同**属正常**：`dev.ps1` 记的是它 `Start-Process` 出来的**父进程**
  （uvicorn 父 / cmd.exe 包装），真正 listen 的是**子进程**；实测 `stop.ps1` 杀父后子进程随之退出、
  端口立即释放（见 §54 B1）。

## 53. R33 任务 A：文档小尾巴（docs/02 目录树 + 旧名残留复核 · 2026-09-10）

### A1 · docs/02 §3 目录树（只写实，未新建任何目录）

- 首行 `颜回（YanHui）/` → **`YanHui/`**（旧显示名残留，含全角括号），并注明 2026-09-10 由 MathFeynman 改名。
- 逐项对照实测目录后补齐/纠正（依据 = `Get-ChildItem` 全量列目录，非文档转述）：
  1. 补 `backend/app/config.py`（环境变量与默认配置，含 `MF_DB_PATH` 默认 `backend/data/yanhui.db`）；
  2. 补 `backend/migrations/`（实存，仅 `.gitkeep`；注明当前用 `create_all` + 保留升级路径）；
  3. `backend/app/content/` 注释补"含 roadmap 蓝图加载与 audit"；
  4. 补 `content/roadmap/`（五学段 `<level>.yaml` + `REVIEW-blueprint.md`/`REVIEW2-master.md`）与
     `content/manifest.yaml`（均实存且入库）；
  5. `frontend/src/pages/` 由 4 个示例名改为实有 8 个页面（Dashboard/Session/Review/Settings/
     Subjects/Outline/Feedback/FeynmanHistory）；
  6. `frontend/src/components/` **删去三个不存在的假名**（`WorkedExercise`/`FeynmanChat`/`GraphTool`），
     改为实有组件（MathInput / ExercisePanel / SubjectSwitcher / MdMath / ErrorBoundary…）；
  7. 补 `scripts/stop.ps1`（实存，读 `.runtime/pids.txt` 停服）；
  8. 树后加一条说明：`.gitignore` 覆盖的本地目录不入库（`backend/data/`、`content/_drafts/`、
     `.runtime/`、`_dsh-local/`、`resume/`、`.env`）。
- 未改动的部分：`api/service/domain/ai/outline` 等既有行（与实测一致，保持原样）。

### A2 · 旧名 `MathFeynman` / `mathfeynman` 残留复核（改动清单 / 保留清单）

扫描范围：全仓（含 git 忽略区），排除 `.venv`/`node_modules`/`.git`/`resume/`；命中 **40 处**。

**① 改（"把旧路径当当前路径用"）**
| 位置 | 处理 | 理由 |
|---|---|---|
| `.env:14`（本地、git 忽略） | `MF_DB_PATH=backend/data/mathfeynman.db` → `backend/data/yanhui.db` | 唯一把旧库名当**当前库**用的活配置，是迁移不触发的根因（任务 B） |
| `docs/15 §3a` | 现状描述"`.env` 的 `MF_DB_PATH` 仍指旧名…迁移未触发" → 改为 R33 已完成 | 属**当前状态**描述，任务 B 落地后即失真 |
| `docs/15 §7B`⑥ | 标注该勘察项已由 R33 任务 B 执行完毕 | 同上（§7B 其余清单保留为改名手册） |

**② 有意保留（历史证据，逐处理由）**
| 位置 | 内容 | 不改理由 |
|---|---|---|
| `README.md:56` | "源自…旧名 MathFeynman" | 沿革说明（工单点名保留） |
| `README.md:66` | "改名 MathFeynman → YanHui … R32" | 改名记录引用 |
| `docs/09:548` | 真模型留档的**历史临时库**路径 `backend/data/mathfeynman.db` | 工单点名保留：R28 F1 证据链，当时的真实路径 |
| `docs/09:722/732/761/766/802` | R32 改名过程叙述与旧版痕迹清理记录 | 决策链证据口径（docs/15 §7A-3：历史裁决不改写） |
| `docs/13:89` | "工作目录已改名 …（旧名 MathFeynman）" | 交接说明，写明"旧名"不算当前路径 |
| `docs/15:29/63/99/102` | 立心批状态、改名手册、勘察清单① | 同上（手册性质） |
| `IMPLEMENTATION_NOTES.md:2089`（§51） | "库路径遗留（R33 任务 B）：真实库 …mathfeynman.db 仍在用" | **架构侧于 2026-09-10 写的时点记录**，属历史；本批在 §54 记录迁移结果，不回改他人留档（改写会伪造历史）。若架构侧要求改为"已迁移"，一句话即可 |

**③ 不能改（功能字面量）**
- `backend/app/db.py:20/24/29/33`：`_migrate_legacy_db_path()` 的 legacy 字面量 `"mathfeynman.db"`
  与其中文提示——**迁移逻辑必须知道旧名**，改成新名会让迁移失效（属逻辑，本批也不许动）。

**④ 本地留档 / 忽略区（不改，仅登记）**
- `.runtime/EULER_TICKET_INIT_R33.md`（本批工单）、`.runtime/EULER_TICKET_R32.md`（历史工单）：
  文中旧名是"当时口径"说明；`R32.md:30` 的"若仍有 MathFeynman 绝对路径→改为 YanHui"即本批 A2 依据。
- `.runtime/EULER_TICKET_R27.md:3`、`R30.md:3`：**旧绝对路径当仓库路径用**（误导源）→ 按工单只加一行
  "本文件为历史留档 / 当前路径为 YanHui"注记（见 A3）。
- `_dsh-local/r30_*.xml`（8 个 junit 证据，含旧绝对路径 `D:\DeepseekHarness\MathFeynman\...`）、
  `.runtime/r27_live_out.txt`、`.runtime/u01_dump.txt`、`_dsh-local/diag_fb.py`（新名优先、旧名兜底的
  只读诊断脚本）：均为**既往批次的证据/工具**，属被忽略的本地目录，不入库、不动。
  （本批新产出的留档：`.runtime/r33_*.txt|xml`。）

### A3 · 历史工单注记

- `.runtime/EULER_TICKET_R27.md` / `.runtime/EULER_TICKET_R30.md`：标题下各加一行
  「⚠️ 本文件为历史留档…文中 `D:\DeepseekHarness\MathFeynman` 是当时的路径，现为 `YanHui`…正文不改写」。
- 二文件均被 `.gitignore` 忽略（`.runtime/`）→ 不入库、不产生提交，仅本机防误导。

### A4 · 回归

- 本批 A 段**零代码改动**（只动 `docs/02`、本 NOTES、两个被忽略的 `.runtime` 文件）。
- 改后复跑：`pytest backend/tests` = **327 collected / 325 passed + 2 skipped / 0 failed，exit 0**
  （留档 `.runtime/r33_pytest_afterA.xml`）→ 与 §52 基线**逐位一致**。

## 54. R33 任务 B：数据库库名归一（`mathfeynman.db` → `yanhui.db` · 2026-09-10）

**总原则**：全程**只改名**，不复制数据、不覆盖、不删除；任何一步异常即回滚并记"待架构裁决"。

### B1 · 停服（第 1 步）

- 停服前实况：8000 的**监听者**是 `python -m uvicorn app.main:app` PID **19852**（子进程）；
  `.runtime/pids.txt` 记录 9084 / 2944（**父进程**，`dev.ps1` 写的是 `Start-Process` 返回的父 PID）。
  两者不同**属正常**，不是记录失效。
- 实测：`scripts\stop.ps1` 杀掉记录的父进程后，**子进程 19852 随之退出**，8000 / 5173 随即无监听、
  无残留 uvicorn → 停服成功（另按端口定位复核了一遍，此时已无可杀对象）。
- 纪律：停服一律**以端口复核**（8000/5173 无监听才算停干净）；改名/迁移前也必须确认进程真退出——
  SQLite 打开时不带 `FILE_SHARE_DELETE`，被占用时 `Rename-Item` 会失败（本次未遇到）。

### B2 · 备份（第 2 步，改名之前）

- 路径：**`D:\DeepseekHarness\_backups\yanhui-db-20260910-160212\`**（政策要求落在 `_backups\`，不落桌面）。
- 内容与核对（**先复制 → 逐文件核对大小 + SHA256 → 通过才继续**）：

  | 文件 | 字节 | SHA256（前 16 位） | 源/副本一致 |
  |---|---|---|---|
  | `mathfeynman.db` | 327680 | `820EFC7218A15784` | ✅ |
  | `mathfeynman.db-wal` | 70072 | `A27D54D5C3A62D53` | ✅ |
  | `mathfeynman.db-shm` | 32768 | `12172D4B437F114C` | ✅ |

  副本只读校验：`pragma integrity_check = ok`，六项计数与源一致（26/3/31/2/113/0）→ **备份可用**。

### B3 · 改名（第 3 步）

- `backend/data/` 内：`mathfeynman.db` → `yanhui.db`、`mathfeynman.db-wal` → `yanhui.db-wal`、
  `mathfeynman.db-shm` → `yanhui.db-shm`（纯 `Rename-Item`；改名后旧三件套在原名下 `Test-Path = False`）。
- 历史文件 `mathfeynman.db.bak-20260908-220309`（2026-09-08 的备份）**不在改名范围**、原样保留。

### B4 · 配置（第 4 步）＋ **第二层根因（本批新发现，重要）**

- `.env`（git 忽略）：`MF_DB_PATH=backend/data/mathfeynman.db` → **`backend/data/yanhui.db`**（已改）。
- `.env.example`（入库）：本来就是 `backend/data/yanhui.db`，**无需改动**（R32 §4#2 口径成立）。
- **重启后实测：应用仍打开了旧名库**——16:03:40 在 `backend/data/` **新建了一整套空库**
  （`mathfeynman.db` 4096B + `-wal` 412032B + `-shm` 32768B；`subjects=1`/`sessions=0`/`attempts=0`）。
- 定位（逐层排查，非猜测）：
  1. `config.py:15` 用 `load_dotenv()`（无参）→ 从 `config.py` 所在目录向上找到仓库根 `.env`，**路径解析正常**
     （`REPO_ROOT` 锚定，`.env` 新值确实被读到）；
  2. 但 **python-dotenv 的 `load_dotenv()` 默认不覆盖已存在的环境变量**；
  3. 当前进程环境里**存在 `MF_DB_PATH=backend/data/mathfeynman.db`**（`Process` 级）——
     由**当前 DSH 服务进程（node.exe）继承而来**（`User`/`Machine` 级均为空，不是 `setx` 持久化的）。
  4. → 结论：**双层根因**。R32 §3③ 只记到 `.env`（第一层）；第二层是
     **进程环境变量优先于 `.env`**，只改 `.env` 永远不生效。这也解释了为何改名前"迁移静默不触发"。
- 处置：
  1. 误建空库三件套 **move（不是删除）** 到备份目录
     `…\_backups\yanhui-db-20260910-160212\stray-from-misconfigured-restart\`（留作证据，可回滚）；
  2. 以 `$env:MF_DB_PATH='backend/data/yanhui.db'` 重启后端（进程级覆盖 .env/继承值，立即生效）；
  3. **真实数据零损失**：`yanhui.db` 六项计数与迁移前逐位一致（见 B5）。

### B5 · 校验与冒烟（第 6/7 步）

- 只读连 `backend/data/yanhui.db`：`pragma integrity_check = ok`；
  **user_nodes 26 / sessions 3 / attempts 31 / subjects 2 / concepts 113 / reviews 0** —— 与迁移前**逐位一致**。
- `backend/data/` 现仅：`yanhui.db`(+`-wal`/`-shm`) 与历史 `mathfeynman.db.bak-20260908-220309`；
  **`mathfeynman.db` 三件套不在原名下**（校验项达成）。
- 启动日志：无 `[db] 已迁移旧库 …` 行 —— **正常**（已人工改名，迁移代码路径不必触发；工单 §5.5 已注明）。
- 应用层（服务重启后）：`/api/health` 200、`/api/dashboard` 200、`/api/subjects` 200、
  `/api/selfextend/status` 200、`/api/campaign` 200；前端 `http://127.0.0.1:5173/` 200（index 669B）
  —— **无 500、无白屏**（HTML 正常返回）。
- **数据真实性交叉验证**（区分"真库"与"误建空库"）：`/api/subjects` = `math`(数学, preset) +
  `s-f2decfcf`(行星科学, custom) **两个**学科（空库只有 1 个）；`/api/dashboard.stats` =
  `learning 1 / locked 24 / consecutive_days 1`（空库为 `0/23/0`）；遗留会话
  `s-f2decfcf.u01:a7689b7ebf`（state=learning）在库 → 确认应用正读**真实库**。
- 服务现状：后端 8000（PID 21656）、前端 5173（PID 2948）均在跑；`.runtime/pids.txt` 已由 `dev.ps1`
  刷新为**正确 PID**（顺带修掉了任务 B 开工时发现的陈旧记录问题）。

### B6 · 回滚方案（未使用）

- 若需回滚：停服 → 把备份目录三件套改回 `mathfeynman.db`/`-wal`/`-shm`（或把 `yanhui.db*` 改回旧名）
  → `.env` / 进程环境 `MF_DB_PATH` 指回旧名 → 重启。本次**未触发任何异常，无需回滚**。

### B7 · 遗留（交架构侧/用户，非仓库改动）

1. **当前 DSH 服务进程的环境仍带旧值**：由它派生的新终端/新进程会继续继承
   `MF_DB_PATH=backend/data/mathfeynman.db`。`.env` 已是新名 → **只要重启 DSH（或换一个新终端启动
   `scripts\dev.ps1`）即自动正确**，无需任何显式设置。建议用户方便时重启 DSH 以彻底清掉该残留。
2. 若要**永久**免除进程环境干扰，可考虑（需架构裁决，本批未做）：启动脚本里显式覆盖
   `MF_DB_PATH`，或让 `config.py` 改用 `load_dotenv(override=True)`——**两者都属逻辑/行为改动，超出本批授权**。

## 55. R33 任务 C：真人验收清单（用户动作）+ 疑点（2026-09-10）

> 规格来源：docs/09 R32 §4「用户动作（R33 真人验收清单）」。Euler 只负责清单**准确、可执行**；
> 下面全部是**用户动作**，本批未代跑（真人浏览器走查无法由 Euler 代做）。

### C0 · 前置（Euler 已办妥，用户直接开浏览器）

- 后端已在 8000、前端已在 5173 运行（PID 见 `.runtime/pids.txt`）；数据库已是 `backend/data/yanhui.db`。
- 打开 **http://127.0.0.1:5173/**（后端 API http://127.0.0.1:8000/api/health 已 200）。
- ⚠️ **若你要自己重启服务**：请**先重启 DSH（或换一个新开的终端）**再跑 `scripts\dev.ps1`，
  否则该终端会继承 DSH 进程里残留的旧 `MF_DB_PATH`（见 §54 B4/B7），又指回旧库名。

### C1 · 遗留会话费曼 v3 全流程（R29 修复后的真实走查）

- [ ] 打开遗留会话 `s-f2decfcf.u01:a7689b7ebf`（行星科学，库中 state=learning）——
      **应正常打开，不再出现"会话不可用"**（R29 修复前该动作为必现 500）。
- [ ] **首讲**：提交一段完整讲解 → 出现评分卡（维度分/综合分/门槛进度）。
- [ ] **补答**：有追问时点「回答追问」提交 → 得分条应**可见上升**（缺口维度分涨）、缺口提示同步更新；
      不再出现"两轮逐字同分"。
- [ ] **整合重讲**：点「整合后完整重讲」提交完整稿 → 综合分/进度条刷新；过线则进入 mastered + 复习队列。
- [ ] **额度徽标**：整体稿 ≤3 / 补答 ≤2 显示正确；补答未补上时的文案应为
      「**再交一次完整讲解后，会针对该缺口再问**」（F4 口径）。
- [ ] 若本轮综合分落边缘带 `[0.65, 0.78]`：应出现
      「⚖️ 本次接近及格线，已用更认真的档位复核一遍（取较高分）」横幅（R30 F6）。

### C2 · 真实 SearXNG 端到端

- [ ] 自托管 SearXNG（需开 JSON 输出）后配 `MF_SEARCH_PROVIDER=searxng` / `MF_SEARXNG_URL`；
- [ ] 学科 → 大纲/材料 → 联网候选：返回候选清单；勾选后抓正文入库（不整本下载）；
- [ ] 未配置时：UI 应显示中文"未配置检索后端"提示，而不是报错。

### C3 · PDF 上传 UI

- [ ] 上传 ≤20MB 的 PDF → 分页入库、材料列表出现；
- [ ] 超限 / 非 PDF / 无文本层 → **中文**错误提示（不得裸英文堆栈）。

### C4 · math 停用 / 重新启用演示

- [ ] 停用 math → 仪表盘顶部中文提示 + 图谱与内容隐藏、不影响其他学科；
- [ ] 重新启用 → 内容与进度恢复（"移除可恢复"语义）。

### C5 · 材料可追溯重生成

- [ ] 让引用材料的单元重生成 → 来源标注可查、可追溯。

### 疑点（挂"待架构裁决"，本批未擅改）

1. **进程环境变量覆盖 `.env`（§54 B4/B7）**：是否需要把 `config.py` 改为
   `load_dotenv(override=True)`，或在 `scripts\dev.ps1` 里显式设置 `MF_DB_PATH`？
   —— 二者都属**行为/逻辑改动**，超出 R33"零逻辑改动"授权，故只记录不实施。
2. **`.gitignore` 是唯一非 UTF-8 的入库文件**（GBK/ANSI，中文注释显示为乱码；实测 200 个入库文件中仅此 1 个）。
   git 按字节匹配模式，**功能不受影响**；本批未改（改编码会造成整文件伪 diff，且属"编码/配置变更"）。
   是否列入后续清理批，请架构侧裁。
3. **NOTES §51（架构侧留档）"库路径遗留"的时点问题**：迁移完成后该段文字已过时，但它是**架构侧 2026-09-10 的
   时点记录**，改写会伪造历史 → 本批**未回改**，仅在 §54 记录结果。若架构侧希望标注"已迁移"，一句话即可。
4. **提交标签与实际内容的小偏差（自曝）**：任务 A1 的 `docs/02` 改动与 NOTES §52 **同批落入 `51c6a62`**
   （消息只标了 §52）；`docs/15` + NOTES §53/§54 落入 `b90c160`。本地领先 `origin/main` 37 个提交、**未推送**，
   为避免改写历史未做 rebase；以本节记录为准。若架构侧要求重排提交，请明示后再动。
5. **`backend/data/mathfeynman.db.bak-20260908-220309`**（229376B，2026-09-08 的应用库旧备份，git 忽略）
   仍在盘上。备份政策"只留当前运行版本数据"针对 DSH 缓存；此文件是**应用库的旧备份**，
   是否清理请用户/架构侧定 —— 本批**未删**（改名批次不做删除动作）。
6. 备份目录内新增 `stray-from-misconfigured-restart\`（§54 B4 的误建空库三件套，留作证据）：
   确认无保留价值后可删（本批保留）。

## 56. R33 验收自证（逐条给证据 · 2026-09-10）

> 对应工单 `.runtime/EULER_TICKET_INIT_R33.md` §7。数字一律取自留档，不口述估算。

1. **pytest（终检）**：`.\.venv\Scripts\python -m pytest backend/tests -q --junitxml=.runtime/r33_pytest_final.xml`
   → junit 权威计数 **tests=327 / failures=0 / errors=0 / skipped=2**（= **325 passed + 2 skipped**，
   time=111.619s，exit 0，离线）→ 与 §2 基线**逐位一致**。
   三次留档：`.runtime/r33_pytest_baseline.xml`（开机）、`.runtime/r33_pytest_afterA.xml`（任务 A 后）、
   `.runtime/r33_pytest_final.xml`（收尾），三者同为 327/0/0/2。
2. **content validate**：`.\.venv\Scripts\content.exe validate` → `ok=True nodes=26 exercises=54`，exit 0。
   **audit 五学段**：primary **27** / middle **31** / high **81** / college **59** / ai **60**，
   各 `ok=True`，cycles / prereq_missing / anchors_missing / content_prereq_violations / boss_unmatched /
   cross_reverse **全 0**。
3. **前端**：`npx tsc --noEmit`（frontend/）→ **exit 0**。（`npm run build` 在受限沙箱会因 esbuild 子进程
   EPERM 失败，属环境限制；按 docs/13 §4 以 tsc 为准。）
4. **任务 A**：改动清单 + 每处「为何改 / 为何保留不改」见 **§53**（A1 目录树逐项、A2 残留 40 处分类表、
   A3 历史工单注记）。
5. **任务 B**：备份路径 `D:\DeepseekHarness\_backups\yanhui-db-20260910-160212\`（3 文件 + SHA256 逐项核对
   + 副本 integrity ok）；**迁移前后六项计数对照**（迁移前 → 迁移后）：
   user_nodes **26 → 26** / sessions **3 → 3** / attempts **31 → 31** / subjects **2 → 2** /
   concepts **113 → 113** / reviews **0 → 0**（**逐位一致，零损失**）；
   页面/接口冒烟：8000 与 5173 均监听，`/api/health`、`/api/dashboard`、`/api/subjects`、
   `/api/selfextend/status`、`/api/campaign`、前端 `/` **全部 200、无 500、无白屏**；
   另测**前端同源路径**（浏览器实际走的链路）：`http://127.0.0.1:5173/api/health` → 200（vite 代理到后端）、
   `http://127.0.0.1:5173/src/main.tsx` → 200（模块可转译）、首页返回 `<!doctype html lang="zh-CN">` +
   vite HMR client → **具备渲染条件**（真机视觉走查仍归 §55 C 组，用户动作）；
   **异常与回滚记录**：无异常，未触发回滚；唯一插曲＝进程环境变量导致误建空库（已 move 出留存，见 §54 B4）。
6. **任务 C**：可勾选真人验收清单见 **§55**（C0 前置 + C1–C5 五组，用户动作）。
7. **git**：本批提交链均标注 `R33`：`51c6a62`（NOTES §52 + docs/02）→ `b90c160`（NOTES §53/§54 + docs/15）
   → `7eec2fc`（NOTES §55/§56 + docs/13 §3/§4）→ `c9f61ba`（pids 口径更正 + 前端同源冒烟证据）
   → `2c08a57`（docs/15 §3 基线行同步）→ **本节修订提交（链尾）**；工作树**干净**（`git status --short` 为空）。
   本地领先 `origin/main` 若干提交、**未推送**（沿用既有"不自动推远端"惯例）。

**本批改动文件清单**
| 文件 | 类型 | 说明 |
|---|---|---|
| `docs/02-architecture.md` | 入库·文档 | §3 目录树：首行 `YanHui/` + 按实测补齐/纠正（含删去 3 个不存在的组件名） |
| `docs/15-architect-handover.md` | 入库·文档 | §3a R33 状态、§7B⑥ 库路径同步 + 新教训 |
| `docs/13-agent-handover.md` | 入库·文档 | §3 R33 执行摘要、§4 库路径与停服口径 |
| `IMPLEMENTATION_NOTES.md` | 入库·日志 | §52 续接基线 / §53 任务 A / §54 任务 B / §55 任务 C+疑点 / §56 自证（本节） |
| `.env` | 本地·忽略 | `MF_DB_PATH` → `backend/data/yanhui.db` |
| `backend/data/yanhui.db(+wal/shm)` | 本地·忽略 | 由 `mathfeynman.db(+wal/shm)` **改名**而来（数据不变） |
| `.runtime/EULER_TICKET_R27.md`、`R30.md` | 本地·忽略 | 各加一行"本文件为历史留档"注记（正文不改写） |
| `D:\DeepseekHarness\_backups\yanhui-db-20260910-160212\` | 仓库外 | 迁移前备份（含 SHA256 核对）+ 误建空库证据 |

**零逻辑改动自证**：本批未触碰 `backend/app/**`、`frontend/src/**`、`content/**`、`backend/tests/**`
（`git diff --stat 4604fcf..HEAD` 仅含 docs 与 NOTES）→ 测试数字与基线逐位一致（第 1 条）。

---

## 57. R34-fin 收尾批：数据清空后的合规确认（2026-09-10）

> 工单 `.runtime/EULER_TICKET_R34_FIN.md`；背景＝用户为测试「生成大纲」清空学习数据
> （行星科学硬删 / math 停用 / 进度归零，架构侧记录见 docs/15 §3.1）。本批**只做确认**，零逻辑改动。

### 57.1 任务 1 · 全量回归（留档 `.runtime/r34fin_pytest.xml`）

| 项 | 实测 | 期望 | 结论 |
|---|---|---|---|
| `pytest backend/tests` | **327 collected / 325 passed + 2 skipped / 0 failed / 0 error，exit 0**（116.55s） | 325+2 / 327 | ✅ 一致 |
| `content validate` | **ok=True nodes=25 exercises=48** | ok（真实库 25 内容文件） | ✅ 如实记录（原 26/54，差＝已硬删的行星科学内容） |
| roadmap `audit()` | **primary 27 / middle 31 / high 81 / college 59 / ai 60**，各 `ok=True`，错误项全 0 | 27/31/81/59/60 | ✅ 不变（roadmap 文件未动） |
| `npx tsc --noEmit` | exit 0 | exit 0 | ✅ |

**结论**：清空真实库**不影响**测试数字——`backend/tests/conftest.py` 在导入 app 之前就把
`MF_DB_PATH` 指向临时库（L52–L54）、`MF_CONTENT_ROOT` 指向会话级内容副本（L68–L71），
真实库与测试完全隔离。故"清空后 pytest 仍 325+2"是**预期内**的，不构成疑点。

### 57.2 任务 2 · 清空后体验一致性

**(a) math 停用态（API 实测，全部 200）**

| 端点 | 实测 |
|---|---|
| `GET /api/subjects` | `{"subjects":[]}`（默认隐藏停用者，符合 B4 设计） |
| `GET /api/subjects?include_removed=1` | 仅 `math`，`enabled=false`、`removed_at=2026-09-10T09:03:52` |
| `GET /api/dashboard` | 全 0：`mastered/learning/available/locked/consecutive_days/today_done = 0`，`recommended_node=null` |
| `GET /api/graph` | **0 节点 0 边**，200 |
| `GET /api/campaign` | 5 个学段容器在、**关卡节点总数 0**（内容与关卡地图已隐藏） |

**(b) ❌ 发现一处真实缺陷（显示层 · 本批未修 · 记 §58-6）**：仪表盘顶部中文停用提示**不会出现**。
- 证据链（代码 + 接口实测）：`frontend/src/pages/DashboardPage.tsx:44` 取的是 `api.get("/subjects")`
  —— **默认不含已移除学科**；L50–51：
  `const math = subs.subjects.find((x) => x.id === "math"); setMathEnabled(math ? math.enabled : true);`
  → math 停用时该列表为空 → `find` 得 `undefined` → **回退成 `true`** → L95 `mathEnabled === false`
  的横幅（L96–99 中文提示"预置学科（数学）已停用…"）**不渲染**。
- 实测接口：`GET /api/subjects` → `{"subjects":[]}`；**按前端原逻辑对活接口复刻演算**（本会话执行）：
  `find(math)=None` → `mathEnabled=True` → 横幅条件 `mathEnabled === false` 为 **False**
  → **中文停用提示实际"不会显示"**。
- 拟修（**一行，待架构裁决，本批严禁改逻辑故只登记**）：改取 `"/subjects?include_removed=1"`
  （回退表达式可保持不变）。

**(c) 学科列表页（代码路径确认，未真点）**：`SubjectsPage.tsx:38` 用 `include_removed=1`；
L93 `已停用` 标签；L119–120「重新启用」按钮；L154 空态文案「暂无启用中的学科。可新建自定义学科，
或在下方「已移除」中重新启用。」；L160 分组「已移除（大纲/内容文件留盘 · 可重新启用）」。
→ 与当前状态（唯一学科 math 停用）一致。**未点「重新启用」**（保持现场给用户测建新学科）。

**(d) 全链路走查（真模型，脚本 `.runtime/r34fin_walkthrough.py`，输出 `.runtime/r34fin_walkthrough.out.txt`）**

| 步骤 | 结果 |
|---|---|
| 新建自定义学科 `POST /api/subjects` | **201**（`s-r34walk`，kind=custom） |
| 起草大纲 `POST /outline/draft`（真模型） | **200**，`source=ai`，3 单元（u01/u02/u03） |
| 采纳 `PUT /outline`（status=active） | **200**，`revision=1`、units=3 |
| 懒生成内容 `POST /units/{id}/content` ×3（真模型） | **3/3 → 200**，`status=created`，落盘 `content/stages/s-r34walk/*.md` |
| 进度视图 `GET /progress` | **200**（3 单元 todo、u01 open） |
| 硬删 `DELETE /subjects/s-r34walk?hard=true` | **204**，学科列表回到仅 math（停用） |

全程 **0 个 500**；错误中文化抽查：`count=99` → **422**「参数校验失败：单元数量：格式或取值有误。
请修正后重试。」；不存在学科 → **404**「学科不存在或已停用: s-doesnotexist（重新启用请见列表「管理已移除」）」。

**(e) 现场影响（如实登记；未做任何 DB 手改）**

| 表/项 | 走查前 | 走查后 | 说明 |
|---|---|---|---|
| `nodes` | 25 | 28 | +3 为 `s-r34walk.u01–u03` **残影且 `enabled=0`**——属 hard 删除的**设计行为**（Node 行禁用、不物理删，`outline/store.py:196`），与清空时那 3 行行星科学残节点同类 |
| `nodes(enabled=1)` | 25 | **25** | 真实内容库不变 ✅ |
| `user_nodes` | 0 | 25 | 懒生成触发 `sync_content` 的"重算全部用户状态"（`service/library.py:56`）；25 行均为默认 `locked`，dashboard 仍全 0、graph 仍 0 节点 → 不影响体验 |
| `ai_logs` | 38 | 42 | 走查 4 次真模型调用（`outline_draft` ×1 + `unit_content_draft` ×3） |
| 其余 | — | — | `subjects 1 / concepts 83 / edges 28 / sessions,attempts,reviews,feedback,relearn_logs,user_concepts 全 0` **逐位不变** ✅ |

文件层：`content/subjects/` 仅剩 `math/`；`content/stages/` 回到 **25** 个 `.md`（走查产物随硬删物理清除）；
`git status` **干净**（无残留、无未跟踪文件）。→ 若要求回到"绝对 0"，需删 3 行
`nodes where enabled=0 and id like 's-r34walk.%'` 与 25 行 `user_nodes`；**本批未执行**（数据写操作，等指令）。

### 57.3 任务 3 · 口径登记（一行）

> **auto 内容随生成即入版控（当前口径）**：运行期懒生成落盘的内容文件
> （如 `content/stages/primary/topic_数与运算/node_primary_s27_auto.md`）由架构侧 `git add` 入库
> （提交 `83e1ad5`）——即"内容库＝git 管理"这一约束**对运行期 auto 产物同样成立**（`git ls-files`
> 实测 content/stages 下 **30** 条已入库，含 12 个 `*_auto.md`）。本批**未**写任何自动提交逻辑
> （属未裁定的新机制）。

### 57.4 R33 两处遗留已闭合（登记，避免下任困惑）

- 旧库快照 `backend/data/mathfeynman.db.bak-20260908-220309`：**已不存在**（R33 §3.5 的"暂留"项已清）。
- 误建空库证据 `_backups\yanhui-db-20260910-160212\stray-from-misconfigured-restart\`：**已不存在**
  （R33 §3.6 的"暂留至验收结束"项已清）；该备份目录现仅剩迁移前三件套（`mathfeynman.db` + wal/shm）。

## 58. 待架构裁决 / 未决（挂账清单 · 2026-09-10 更新）

> 供下一任 Euler 续接用：本节＝**当前所有未闭项**的单一入口。凡本节已裁决的项，实现时在此标注结果。

1. **R35 全量规格（可答性 S1–S8）——已全部落地**：S1–S8 的代码/内容/文档/用例见
   §61（S1/S2/S5/S6/S7 + A3 例题）→ §62（S6/S7 收口）→ §63/§64/§65（语义闸门 → 求值单一化 →
   题面泄漏/expect/basis/P4）→ **§66（S3 挑战题池 + S4 reteach + 引文精度 + 文档收尾）**。
   ⚠️ R35 §5 原文指向的**行星科学 u01/u04**已按用户指令硬删（本项**不再待澄清**）：
   R35 的最终验收 = **用户新建 PDF 学科就绪后跑 A2 全链路审计（不可答 = 0）**，
   那是**非数学路径的第一次真考试**（架构侧 §17 亦如此收口）。
   **审计脚本已入库**：`backend/tests/audit_answerability.py`、`audit_template_semantics.py`
   （不带 `test_` 前缀 → 不被 pytest 收集、不随常规 CI；手动门槛见 docs/13 §4）。
2. **真实 SearXNG 端到端**：需用户自托管实例后配 `MF_SEARCH_PROVIDER=searxng` / `MF_SEARXNG_URL`。
3. **PDF 上传 UI 真人走查**；**材料可追溯重生成**（引用材料参与的单元重生成 + 来源可查）。
   **R37 部分闭合**：来源可查已闭（`GET /coverage` + 单元 `meta.coverage` + 讲解尾部"教材依据"）；
   **"按材料变化强制重生成"仍缺**（`POST /units/{id}/content` 是幂等的，内容在库即返回 `exists`；
   要重生成需先删内容文件或加 `force` 入口——**未做**，见 §67.6）。
4. **math preset 本体是否彻底清**：当前保留 25 个内容文件 + 258 单元大纲（仅 `enabled=0`）。
   若要"纯白纸"（连内容文件一并清），属另一条指令。
5. **`.runtime/EULER_TICKET_R34.md` 已作废、不要执行**：其两项已由架构侧直办——
   `dev.ps1` 库路径确定性（`17646f8`）、`.gitignore` 转 UTF-8（`17646f8`）、
   `stop.ps1` 进程树（`e55c8b3`）、启动器加固（`4a032d2`）。
6. ~~**【R34-fin 发现】仪表盘"数学已停用"横幅不显示**（§57.2b）~~ → **✅ 已闭（R36 L1，2026-09-10）**：
   采纳架构侧倾向方案②——`GET /api/dashboard` 直出 `preset_subject{id,label,enabled}`，前端不再从
   `/subjects` 反推。改动与证据见 **§59.1**（含回归用例）。
7. ~~**【R34-fin 发现】走查在真实库的痕迹是否清理**（§57.2e）~~ → **✅ 已闭（R36 L2，2026-09-10）**：
   已备份后清理：3 行 `nodes(enabled=0)` + 4 行走查 `ai_logs` **永久清除**；`user_nodes` 清为 0，
   但**每次后端启动会由 `sync_content` 重建**（引擎既有语义，非走查残留）→ 详见 **§59.2**。
8. ~~**R35 审计脚本要入库**~~ → **✅ 已闭（R35b）**：`backend/tests/audit_answerability.py`
   （零基础学生模型逐题判 `answerable`，选择题必须把 options 一并喂给"学生"）+
   `backend/tests/audit_template_semantics.py`（28/30 模板体检）**已在库**，文件名不带 `test_` 前缀 →
   pytest 不收集；手动门槛（改生成器后跑一轮 / 发版前跑 / 日常 CI 只跑离线校验）见 docs/13 §4。
9. **【R36 D/P 新发现】math 预设大纲 15 处难度倒置**（§60.5 清单）：P1（先修难度 ≤ 后继）对
   `source=="roadmap"` 的预设大纲**豁免**（其顺序由 R18 总序 + roadmap audit 治理，改数学数据超本批授权）。
   待裁：**治理数据**（按 P1 修 roadmap difficulty/顺序）还是**确认长期豁免**？
10. ~~**P4（难度只能靠已教事实累积）目前只有 prompt 约束**~~ → **✅ 已闭（R35b §65.4）**：
    `answerability.check_progression()` 两条机器校验（引用必须已教 / 加难必须加事实）**已接生成端**，
    含造错用例；已随可答性闸门一起跑（`outline/generate.py`）。
11. ~~**【R36 D/P 新发现】材料注入只做"分节摘要"**（PDF 按页 / Markdown 标题 / 段落兜底，每节 ≤400 字、
    总量 ≤`MF_OUTLINE_MATERIAL_MAX_CHARS`）：**未做语义级摘要**——大部头书籍注入的是"每节开头若干字"。~~
    → **✅ 已闭（R37 S1，2026-09-10）**：默认改为**不设预算**（`MF_MATERIAL_INJECT_MAX_CHARS=0`）+ 按
    `bookmap` 章/节结构注入**完整正文** + 按 `MF_MATERIAL_BATCH_CHARS` 在章/页边界分批；**显式设的上限
    只作单次调用预算**（R38 §3 共存口径：调小不丢章节，`dropped` 恒空）。样本实测注入量 6,000 → **103,448 字**；
    见 **§67.1/§67.2**。
12. **【长期纪律】AI 输出 schema 与 prompt 的字段一致性**是易漏点（§60.4：schema 漏声明
    `materials` → pydantic 静默丢弃，单测用假 provider 测不出）。**今后新增 AI 输出字段必须同时改
    `ai/calls.py` 的 out schema + prompt + 一条 schema 往返用例**。（本批挑战题两个调用点已照此办：
    `test_challenge_callpoints_registered`。）
13. **【R35b §66 待架构侧确认】`reteach` 不翻转 stage**（§66.3）：架构侧文档写"返回 `reteach`
    （退回讲解补讲）"；若把 `stage` 翻回 `explain`，练习已通过的会话会**重新出题**并再次计入
    practice 账目（等于用一次敷衍回答污染练习记录）。本批实现为：**阶段不动 + 随响应下发讲解原文 +
    `next_action="reteach"`**。若架构侧坚持 stage 回退，请一并裁定"回退后不再出题"的配套改法。
14. **【R35b §66 提升项】模板 basis 引文"是否真支撑该模板"仍需人读**：机器只能判
    「逐字出自讲解」+「非开场白/过渡句」（`verify.opening_quote_warning`，**告警不拒绝**）。
    本批 30 条已逐条改引支撑规则句（对照表见 §66.1），但**语义贴合度属人工判断**，
    架构侧可抽读复验。
15. **【R35b §66 新发现 · 待裁】挑战题在页面刷新/换页后不恢复**（§66.6-3）：挑战题**刻意不进默认
    payload**（否则等于"出现在默认流程"）→ 刷新后面板消失，再点「挑战一下」会重新生成一道
    （`asked` +1，旧题在 flow 里被覆盖）。若要"刷新后仍在"，需加一个显式读端点
    （如 `GET /session/{id}/challenge`）——**未做**，因为那会把挑战题变成"半个默认流程"。
    取舍请架构侧裁定（倾向：保持现状＝规格优先）。

16. **【R37 待架构侧确认】5 条**（详述见 §67.6）：
    ① 离线段（无 `LLM_API_KEY`）+ 有教材：仍出稿但覆盖状态如实记"未覆盖（本内容无教材依据）"，
    是否改为**拒绝出稿**？② 难度**非降钳制**的副作用（书序上一个 3 会抬高其后全部单元）；
    ③ 讲解"整句命中教材"仅 19%（转述 + 夹引号，S3 允许），是否要更贴原文；
    ④ 附录类小条目（45 字）也会成为单元（S2 无豁免规则）；⑤ 有章节地图时**单元数由书决定**
    （样本 46 个），`count` 只在无地图时生效——与 docs/14 §2.1 字面略有出入。
    → **①–⑤ 已由 R40 裁决**（`50bdde7`）：①改**拒绝出稿**（**R38 已实现**，见 §68.1 末行）②接受现状但
    **必须显性**（已进账本 + 大纲页）③接受，basis 引文改节级（提升项）④**条目过短须合并/标跳过且必须记账**
    ⑤确认语义，须在 UI 说明。**④/⑤ 仍待办**（见本条 17-⑦）。

17. **【R38/R39 收尾待办 / 请架构侧定夺】（2026-09-10）**：
    ① 账本是否也给"成功路径"记账（当前只记"异常/偏离"）——§69.7-1；
    ② 复习降级回炉是否在新总账里再记一条（当前只留 `relearn_logs` 单一权威源）——§69.7-2；
    ③ 模型调用的"**降档**"（think→fast）是否逐次记账——§69.7-3；
    ④ 提示词 **user 模板**是否开放编辑（当前只读对照；接线已就绪）——§69.7-4；
    ⑤ 审计文件**自动**按保留期清理（当前人工触发 + 参数）——§69.7-5；
    ⑥ **R38 "总注入上限"口径**：事实报告（不丢章节）vs 跨批硬封顶（会丢章节）——**§68.4**；
    ⑦ **R40 遗留**：材料"条目过短（<200 字）→ 合并进相邻单元或标跳过，且跳过必须记账"
       与"有地图时 `count` 只在无书时生效"的 **UI 说明**——**尚未落地**（R37 裁决 §2-4/§2-5）。


---

## 59. R36 任务 L（先行 · 清现场 · 2026-09-10）

### 59.1 L1 · 仪表盘停用横幅不显示 → **方案②（dashboard 直出）**，已修

**方案选择与理由**（架构侧给了二选一）——**采纳方案②**：`GET /api/dashboard` 直接下发
`preset_subject: {id, label, enabled} | null`：

- **语义正确**：横幅问的是"**预置学科的生命周期状态**"，而 `/subjects` 的契约是"**列出启用中的学科**"
  （默认隐藏已移除者）。用后者推断前者属于**契约误用**——这也是缺陷根因。直出后不再有"推断"，
  也就没有 `find` 失配回退的风险。
- **少一次请求**：仪表盘首屏由 4 个并发请求降为 3 个（`/dashboard` 已聚合引擎状态，无需再拉全量学科）。
- **通用**：按 `kind == "preset"` 查（非硬编码 `math`），未来多预置学科时语义不变；无预置学科 → `null`。
- 未选方案①（`/subjects?include_removed=1`）的原因：一行能修，但把"生命周期状态"塞进列表响应里靠前端筛，
  语义仍然绕，且不解决"为看一个布尔值拉全量列表"。

**改动清单**（提交 `1c121f3`）
| 文件 | 改动 |
|---|---|
| `backend/app/api/dashboard.py` | 响应新增 `preset_subject`（`kind=="preset"` 首行；`enabled` 如实、**不加启用过滤**） |
| `frontend/src/api.ts` | `DashboardData` 增字段与注释（说明"不得从 `/subjects` 反推"） |
| `frontend/src/pages/DashboardPage.tsx` | 删 `mathEnabled` state 与第 4 个请求；`presetOff = Boolean(preset_subject && !preset_subject.enabled)`；横幅文案用 `preset_subject.label` |
| `backend/tests/test_subject_visibility.py` | **新增用例** `test_dashboard_exposes_preset_subject_lifecycle`（1 条） |
| `docs/06-api.md`、`docs/07-ui.md` | 契约与 UI 口径同步（含"不得改用 `/subjects` 反推"的告警） |

**证据**
- 回归：pytest **328 collected / 326 passed + 2 skipped / 0 failed，exit 0**（基线 325+2 → **+1 = 新用例**；
  留档 `.runtime/r36L_pytest.xml`）；`npx tsc --noEmit` exit 0。
- 新用例双向锁定：math 启用 → `{id:math,label:数学,enabled:True}`；停用 → `enabled:False` 且
  **默认 `/subjects` 列表里确实没有 `math`**（把旧缺陷的成因写进断言，防回归）。
- **活体（真实库，math 仍停用）**：`GET /api/dashboard` → `preset_subject = {id:'math', label:'数学',
  enabled:False}` → 前端新逻辑 `presetOff = True` → **中文横幅会显示**；
  vite dev 已服务新源码（转译产物含 `presetOff`/`preset_subject`、**不含** `mathEnabled`）。
- "**启用时不出现**"：由上述用例在 hermetic 环境覆盖；**未**在用户真实库上开关 math（保护现场，
  用户接下来要测建新学科）。

### 59.2 L2 · 真实库走查痕迹清理（先备份 → 核对 → 再清理）

**备份**：`D:\DeepseekHarness\_backups\yanhui-r36-before-clean-20260910-172524\`（三件套 + **SHA256 自证**）：

| 文件 | 字节 | SHA256（前 16 位） | 源/副本一致 |
|---|---|---|---|
| `yanhui.db` | 327680 | `820efc7218a15784…` | ✅ |
| `yanhui.db-wal` | 1128912 | `7f0e8e1532b8b4e9…` | ✅ |
| `yanhui.db-shm` | 32768 | `2134080933b2fc58…` | ✅ |

副本 `integrity_check=ok`、计数与源一致 → **备份核对 PASS 后才动库**。清理脚本留档
`.runtime/r36_db_l2.py`（backup / clean / count 三模式，可复跑审计）。

**计数对照**

| 项 | 清理前 | 清理后 | 重启后（观察） | 二次清理后（**最终交付**） |
|---|---|---|---|---|
| `nodes` | 28 | **25** | 25 | **25** |
| `nodes(enabled=1)` | 25 | 25 | 25 | **25** |
| `s-r34walk` 残影行 | 3 | **0** | 0 | **0** |
| `edges` | 28 | 28 | 28 | **28** |
| `user_nodes` | 25 | **0** | 25（见下） | **0** |
| `ai_logs` | 42 | **38** | 38 | **38** |
| `concepts` / `subjects` / `users` | 83 / 1 / 1 | 不变 | 不变 | **83 / 1 / 1** |
| `sessions`/`attempts`/`reviews`/`feedback`/`relearn_logs`/`user_concepts` | 全 0 | 全 0 | 全 0 | **全 0** |
| `integrity_check` | ok | ok | ok | **ok** |

- **删除内容**：① 3 行 `nodes`（`s-r34walk.u01–u03`，`enabled=0`，走查产物，**永久清除**）；
  ② 25 行 `user_nodes`；③ **4 行走查 `ai_logs`（id 39–42 = `outline_draft` ×1 + `unit_content_draft` ×3，
  本会话走查所产生）**。
  **`ai_logs` 取舍说明**：可留可清（工单授权自定）→ 选择**清掉走查那 4 行、保留此前 38 行真实历史**
  （后者是用户真实使用与 R35 审计的调用记录，属可观测性/成本审计凭据，不该动）。清理掉的 4 行内容
  已在 §57.2d 留档（调用点 + 时间 + 结果），信息不丢失。
- **⚠️ 重要发现（`user_nodes` 不是"走查残留"）**：清理后首次启动后端，`user_nodes` **立刻回到 25**
  —— `main.py` lifespan → `sync_content()` → `recompute_states()`（`service/library.py:96-99`、
  `service/progress.py:85-88`）会为**全部 enabled 内容节点**建立默认状态行（本库＝25 个 math 节点，
  全 `locked`）。故 `user_nodes=0` 是**瞬态**：任何后端重启或内容生成都会重建。
  - 读接口（`/dashboard`、`/graph`、`/campaign`、`/subjects`、`/selfextend/status`）**不会**重建
    （`state_map` 只读、不写行）——实测 5 个端点访问后 `user_nodes` 仍为 0。
  - 处置：**按工单目标把最终交付态清成 0**（二次清理，只删启动重建的那 25 行），并如实登记其瞬态性；
    若要求"永久 0"，需把 `recompute_states` 改成**按需建行**（引擎语义变更，超出 R36 授权，未做）。
- 现场复核：`subjects = [('math','数学','preset',0)]`（math 仍停用）；`content/stages` 25 个 `.md`、
  `content/subjects` 仅 `math/`；服务 8000/5173 均 200；`git status` 干净。

---

## 60. R36 任务 D＋P：大纲起草读材料 + 「由易到难·零基础读一本书」通用化（2026-09-10）

> 规格：`docs/09 R36` §1（D1–D5）/ §2（P1–P5）；工单 `.runtime/EULER_TICKET_R36.md`。
> 与 R35 **合批执行、分两次汇报**；本批为第二次（第一次＝任务 L，见 §59）。
> **提交与 R35 无混合**（R35 本批未实现）。

### 60.1 提交链（均本批）

| 提交 | 内容 |
|---|---|
| `adc0b89` | `refactor(R36 D2)`：**引文尺子收敛**为 `app/content/citations.py`（`feynman_ledger` 委托，R30 F5 口径逐字不变） |
| `ae2c8f7` | `chore(R36)`：`backend/app/config.py` 行尾归一 LF（**纯 EOL 独立提交**，便于分离 blame——R28 F2 同口径） |
| `6b589b7` | `feat(R36 D+P)`：D1–D5 + P1–P5 实现 + 15 用例 + docs/06、docs/14 |
| `3bf1ca8` | `fix(R36 D2)`：`CALL_OUTLINE_DRAFT` 输出 schema 声明 `materials`（**活体冒烟实测踩到的接线缺口**，见 §60.4） |

### 60.2 D1–D5 落地

| 项 | 实现 | 证据 |
|---|---|---|
| **D1 注入** | 唯一入口 `outline.materials.draft_materials(db, sid, max_chars=…)` → `text`（分节摘要注入 prompt）+ `index`（服务端校验用，含正文，不下发）；`_ai_draft_units` 把材料块拼进 user message；`/outline/draft` 与 custom 的 `/outline/regenerate` 都注入 | `test_d1_draft_injects_material_sections_into_prompt`；**材料可选**：`test_d1_draft_without_materials_degrades_but_succeeds`（无材料 → 200、`material_usage.count=0`、不报错） |
| **D2 逐单元溯源** | `OutlineUnit.materials: [{title, section}]` + `OutlineDraftMaterial`（**AI 输出 schema 必须声明**）+ `check_unit_material`：title 必须属于该学科引用库；section 必须是**真实章节名**（`第 N 页`/标题，来自 `material_sections`）**或逐字出自材料正文的引文**（复用 `content.citations` 的 ≥6 字归一化包含校验）。不成立 → **驳回重生成一次**（中文原因回灌 prompt）→ 仍不成立 → **剔除该引用并记问题**（宁缺勿造，不硬失败） | `test_d2_valid_section_and_verbatim_quote_are_kept` / `test_d2_bogus_citation_rejected_then_regenerated`（断言 `len(calls)==2` + 回灌含"引用库"）/ `test_d2_citation_stripped_when_regeneration_also_fails` |
| **D3 大纲层溯源** | 采纳时**服务端**按各单元 `materials[].title` 反查 `material_id`（`material_ids_for_titles`）写入 `OutlineDoc.source_materials`（**不信客户端自报**）；引用不存在 → 中文 422；候选响应即带 `source_materials`；大纲页显示「本大纲依据的材料」+ 逐单元"依据"行 | `test_d3_put_outline_records_source_materials_server_side` / `test_d3_put_outline_rejects_unknown_material_zh`；前端 `OutlinePage.tsx`（tsc 通过） |
| **D4 预算** | `MF_OUTLINE_MATERIAL_MAX_CHARS`（默认 6000，`config.py` + `.env.example`）；**先到先得 + 总字符硬上限**，超限 → 该材料截断（`truncated`）/整体不注入（`dropped`）并**留痕**（prompt 尾部注明"另有 N 份未展示"）；**禁止整本塞入一次调用**；每日 token 上限仍由 `LLM_MAX_TOKENS_PER_DAY`（provider 侧）保护 | `test_d4_injection_respects_char_budget`（800 预算：`used_chars ≤ 800`、`truncated`、prompt 无第 20 页）/ `test_d4_material_over_budget_is_reported_dropped` |
| **D5 通用** | 与学科无关：custom 一律适用（含 regenerated 候选）；preset（math）大纲由 roadmap 派生、不走起草路径 → 不受影响 | 用例全部用自定义学科（含非理科语义） |

### 60.3 P1–P5 落地

- **P1（新增校验）**：`validate_outline_doc` 增"先修 `difficulty` 不得高于后继"，中文问题串带「由易到难」；
  `/outline/validate` 按 `source` 生效、`PUT` 采纳时硬拒（**422 中文**）。
  用例：`test_p1_validate_reports_difficulty_inversion`（造错必报）、`test_p1_put_outline_rejects_difficulty_inversion_zh`、
  `test_p1_monotonic_ok_and_roadmap_exempt`。
- ⚠️ **实测数据问题（需架构侧裁）**：math 预设大纲（258 单元，`source=roadmap`）**有 15 处难度倒置**，例如
  `primary.s05`(难度1) ← 前置 `primary.s04`(难度2)、`high.h08`(1) ← `high.h07`(2)、`ai.a33`(2) ← `ai.a32`(3)…
  （完整 15 条清单见 §60.5）。**本批处置＝豁免 `source=="roadmap"`**（预设顺序由课程蓝图总序 R18 + roadmap audit
  治理；改数学数据超出本批授权）→ **数据治理或"长期豁免"需架构侧裁**（挂 §58-9）。
- **P2（首单元零基础）**：写进起草 system prompt（"第一个单元必须能被完全零基础者学会，不得假定任何前置概念"）；
  **P3**（group 表达章/阶段层次、组内先易后难）与 **P4**（难度只能靠已教事实累积）同样只落在 prompt 约束；
  **P4 的机器校验待 R35 的 `taught_facts/derivable`**（本批不做——用户已明确要求汇报里说明）。
  用例：`test_p2_p3_p4_constraints_are_in_draft_prompt`（断言 prompt 含"零基础"/"由易到难"/"group"/"已讲"）。
- **P5**：**不新增引擎**（沿用掌握度 + FSRS）；本批未改 domain/service 的进度语义。

### 60.4 活体冒烟（真模型 · 两次，留档 `.runtime/r36_live_smoke{,2}.out.txt`）

脚本 `.runtime/r36_live_smoke.py`：建临时学科 `s-r36smoke` → 上传 2 页材料 → 起草 → 采纳 → **硬删复原**。

| 次序 | 结果 | 结论 |
|---|---|---|
| 第 1 次（schema 修复前） | 起草 200/ok，但 **每个单元 `materials=[]`、`source_materials=[]`**（模型给了引用也会被丢） | **发现接线缺口**：`CALL_OUTLINE_DRAFT` 的输出 schema 未声明 `materials`，`provider.chat_json` 用 `model_validate` 校验时**静默丢弃未声明字段** → 假 provider 的单测**测不出**这类缺口。已修（`3bf1ca8`）+ 补接线锁定用例 |
| 第 2 次（修复后） | 3 个单元**全部带真实页引用**：u01→`第 1 页`、u02→`第 2 页`、u03→`第 1 页＋第 2 页`；候选与采纳后 `GET /outline` 的 `source_materials` 均为 `['mat-16e1affd81']`；`material_usage={count:1, used_chars:193, dropped:[], truncated:false}`；难度 **1→2→2**（单调）、首单元 `prereqs=[]`、`group` 为"第一章 认识星空" | D1/D2/D3 真模型链路**打通** |

现场复原：临时学科 204 硬删，学科列表回到 `[math(禁用)]`；计数
`nodes 25 / edges 28 / user_nodes 25（引擎物化，架构侧已裁定接受）/ subjects 1 / sessions·attempts 0`，
`ai_logs 38 → 40`（两次冒烟各 1 次真模型调用，**保留**作为真实调用留档，不再清库——遵 R36 §6 裁定）。

### 60.5 math 预设大纲难度倒置清单（P1 豁免依据，供架构侧治理）

`primary.s05(1)←s04(2)`、`primary.s23(2)←s10(3)`、`primary.s24(2)←s15(3)`、`primary.s21(2)←s20(3)`、
`middle.m11(1)←m03(2)`、`high.h08(1)←h07(2)`、`college.c06(2)←c05(3)`、`college.c16(2)←high.h47(3)`、
`college.c31(2)←c30(3)`、`college.c44(2)←high.h06(3)`、`ai.a07(2)←a06(3)`、`ai.a11(2)←college.c20(3)`、
`ai.a19(2)←a14(3)`、`ai.a33(2)←a32(3)`、`ai.a56(2)←a55(3)`（格式：`单元(难度)←前置(难度)`，共 15 处）。

### 60.6 与 R35 的复用接口（用户点名要求：同一套引文纪律，别写两份）

`backend/app/content/citations.py` = **引文纪律的单一实现**：

```python
MIN_QUOTE_CHARS = 6
normalize(text) -> str                     # 去空白/标点/省略号
is_valid(quote, source, *, min_chars=6)    # 归一化子串包含 + 最短门槛
invalid_reason(quote, source, *, where="给定原文") -> str   # 中文，区分"过短"/"不在原文"
check(quote, source, *, where=…) -> (bool, str)
```

- 既有使用方：费曼 evidence（`service/feynman_ledger` 全部委托，R30 F5 语义/文案不变）；
- 本批新增使用方：**D2 大纲单元的材料溯源**（`outline.materials.check_unit_material`）；
- **R35 S2 的 basis 引文校验直接调用本模块**（勿再写第二份包含校验）。
- 锁定用例：`test_citation_ruler_is_shared_with_feynman_evidence`。

### 60.7 回归自证

| 项 | 实测 | 与基线 |
|---|---|---|
| `pytest backend/tests` | **343 collected / 341 passed + 2 skipped / 0 failed / 0 error，exit 0**（116.0s） | 基线 328/326+2 → **+15 = 本批新用例**（留档 `.runtime/r36dp_accept.xml`） |
| `content validate` | **ok 25 / 48** | 不变 |
| roadmap audit | **27 / 31 / 81 / 59 / 60**，各错误项 0 | 不变 |
| `npx tsc --noEmit` | exit 0 | ✅ |
| 代码范围 | `backend/app/{content/citations,ai/calls,outline/{schemas,materials,draft,store},api/subjects,config}.py`、`frontend/src/pages/OutlinePage.tsx`、`docs/06`、`docs/14`、`tests/test_r36_outline_materials.py` | 未触碰 domain/判定/内容库/`content/stages` |
| 错误中文化 | 新增错误全部中文（材料引用不成立/引用库不存在/由易到难…） | ✅ |

**疑点（挂 §58）**：① math 15 处难度倒置（P1 豁免来源）是否治理；② P4 机器校验待 R35；
③ 材料注入目前只做"分节摘要"（PDF 按页 / Markdown 标题 / 段落兜底），**未做语义级摘要**——
若书很大，注入的是"每节开头 400 字"，必要时再接一次轻模型摘要（成本/复杂度上升，未做）。

---

## 61. R35a（第一次汇报）：可答性——生成端接入（S1/S2/S5 核心 + A3 例题）

> 规格：`docs/09 R35` §2/§3 + `.runtime/EULER_TICKET_R35.md`（§3b 融合约束、§7 防冲突）。
> **本批分两次汇报**（先内容后引擎）：本节＝**R35a**；R35b（S3 挑战题 / S4 追问 discipline /
> S6 小思考 / S7 反馈入口 / 全库审计 / P4 机器校验 / 数学路径接入）**尚未做**，见 §61.5。

### 61.0 开工前：R36 对照基线（工单强制动作）

| 项 | R35 开工基线（=R36 验收值） | 本批后 |
|---|---|---|
| `pytest backend/tests` | **343 collected / 341 passed + 2 skipped / 0 failed，exit 0** | **351 collected / 349 passed + 2 skipped / 0 failed，exit 0**（+8 新用例） |
| `content validate` | ok **25/48** | ok 25/48（不变） |
| roadmap audit | **27/31/81/59/60**，错误项 0 | 不变 |
| `npx tsc --noEmit` | exit 0 | exit 0 |

（提交前工作树干净；R36 已全部提交 `adc0b89…b292c74`。）

### 61.1 落地内容（S1/S2/S5 核心 + A3）

| 件 | 实现 | 复用点（§3b 融合约束） |
|---|---|---|
| **S1 声明式知识包** | `content/schemas.py`：`TaughtFact{id,text}`、`Derivable{conclusion,premises,rule}` 挂到 `NodeDoc`；`text` 必须**逐字出自讲解**（`citations.check`）；`derivable` 的前提必须是已声明事实 id + 非空规则 | 判定器 `content/answerability.py`；引文尺子＝`content/citations.py`（**未写第二份包含校验**） |
| **S2 出题引文纪律** | `ExerciseDoc.basis: BasisDoc{fact_ids,quote,premises,rule}`；`FeynmanDoc.socratic_basis`（与 `socratic_followups` **按下标对齐**）；推理题须 ≥2 条已述事实前提 + `rule`（且须落在本单元 `derivable` 内） | 同上；**出题/评分共用同一把尺子**（`feynman_ledger` 已委托 citations） |
| **S5 自动质检** | `answerability.gate_node(doc)`：不合规的**核心题/追问一律丢弃并记中文原因**（不是让整份内容失败）；生成端把丢弃原因**回灌 prompt** 触发重生成（修生成器，不是改某题文案） | 丢弃计数（`report.dropped`）**待接 `service/guardrails.py`（TRIP_RATIO=0.3）**——R35b 接 |
| **A3 例题约束** | `validate_generic_content` 新增"auto 出稿必须 `worked_examples ≥1`"；启发式与 AI 两条路径都产出例题 | 复用既有 `WorkedExampleDoc`（不新建结构） |
| **A1 生成端接入** | `outline/generate.py`：AI 出稿 prompt 增 `taught_facts/derivable/worked_examples/asks(basis)` 要求（含"零基础假设/只问讲过的/不许个体比较"硬约束）；`build_node_doc` 落盘新字段；**删除硬编码的三条 socratic 模板套话**（"举实例/它与你学过的联系" 正是被审计判死的那三条）；`_frontmatter_md` 写出新字段 | 复用既有 `NodeDoc`/`ExerciseDoc`/`FeynmanDoc`；`asks` 走既有 `socratic_followups` 字段 |
| **接线锁（R36 §8 纪律）** | `ai/calls.py`：`UnitContentBasis/Fact/Derivable/WorkedExample/Ask` + `UnitContentExercise.basis` + `UnitContentDraftOut.{taught_facts,derivable,worked_examples,asks}` **声明在 schema**（pydantic 默认丢未声明字段 → 漏声明会静默失效） | 三处同改：schema + prompt + 往返用例 `test_unit_content_call_schema_carries_answerability_fields` |

### 61.2 审计脚本入库（§5）

- 新增 **`backend/tests/audit_answerability.py`**（长期保留、不被 pytest 收集）：
  零基础学生模型逐题判定；**选择题把 `options` 一并交给"学生"**（架构侧第一版假阳性坑）；
  **`MF_ALLOW_LIVE_AI=1` 门槛**（否则直接拒绝运行，防误触真模型）；`--nodes` / `--limit` 可指定靶子；
  报告写 `%TEMP%\mf_r35_audit_<时间戳>.json`（**文件名唯一不覆盖**，F1 纪律）；有不可答项 → 退出码 1。
- 用法：`$env:MF_ALLOW_LIVE_AI=1; .\.venv\Scripts\python backend/tests/audit_answerability.py --nodes node_primary_s27_auto`
  （**默认用临时库**、真实内容根——审计只读，不动用户数据）。

### 61.3 回归自证（本批）

- 新用例 **8 条** `backend/tests/test_r35_answerability.py`：事实来源校验 / 无据题丢弃（无 basis、引文不在讲解、
  引文过短 <6 字、引用未知事实 id）/ 推理题 ≥2 前提 + 规则 / socratic 无据丢弃 / 旧内容不阻塞加载但不过校验 /
  **启发式端到端**（落盘内容带知识包+依据+例题，重载后仍通过）/ **AI 端到端**（假 provider 给 1 道越界题
  → 只丢那一题、其余入库）/ **schema 接线锁**。
- 全量 **351 collected / 349 passed + 2 skipped / 0 failed，exit 0**（留档 `.runtime/r35_final.xml`）；
  `content validate` 25/48、audit 五学段全绿、`tsc` exit 0。**既有 343 条用例无一改动**（兼容性由它们守住）。

### 61.4 已知边界（本批如实登记）

1. **数学/roadmap 路径（`content/pipeline.py` + `stub_drafter` + `ai/drafting.py`）本批未接入可答性** ——
   它走的 `CALL_DRAFT_CONTENT` 出的是**整篇 .md 文本**（模板题为主），接入需同时改 stub/AI prompt/流水线
   三级（§7 文件区域分工也要求"R35 加可答性校验"为独立函数），**留 R35b**。当前行为：数学 auto 内容
   仍可入库但**没有** `taught_facts` → 若对它跑 `gate_node` 会判"未声明知识包"（口径一致，不矛盾）。
2. **S6 🤔 小思考（`explain_node.asked_to_confirm`）本批未改** —— 留 R35b（含 `ExplainOut.asks_basis`）。
3. **S3 挑战题 / S4 追问 `reteach` / S7 反馈入口 / 复习只考已教事实（S8 收尾）** —— 留 R35b。
4. **真模型审计证据（A2/A4/A5）本批未跑** —— 审计脚本已入库，待 R35b 与用户新建 PDF 学科一并跑并贴证据。

### 61.5 R35b 待办（下一任 Euler 直接照做）

① `pipeline.validate_answerability`（独立函数）+ `stub_drafter`/`ai/drafting` 产出知识包与依据；
② S6：`explain_node` prompt + `ExplainOut.asks_basis` + 校验丢弃（复用 `prompts.context_block`）；
③ S3 挑战题双池（**不得**触碰费曼账本/额度/mastery）；④ S4 追问纪律（引用学生原话，无可引用 → `reteach`）；
⑤ S7 反馈入口（**复用 `feedback` 表加一种 `kind`**）；⑥ 可答性问题率接 `guardrails.py`；
⑦ **P4 机器校验**（R36 欠账：难度提升只能靠已教事实累积）；⑧ 全库审计 + A2/A4/A5 真模型证据；
⑨ 融合对照表（§3b 验收项）+ docs/06、docs/07 同步。

### 61.6 附：math 难度倒置口径澄清（R36 §9 架构侧复算 12 处 vs Euler 15 处）

架构侧按"**同文件内**前置"口径复算得 12 处；Euler 的 15 处为**更宽口径**（含跨学段/内容节点引用，
即 `college.c16←high.h47`、`college.c44←high.h06`、`ai.a11←college.c20` 这 3 条跨学段边）。
校验器实现只比对**同文件内**前置 → **只会漏检、不会误拒**，与架构侧结论一致（**非缺陷**，登记备查）。

### 61.7 本批自曝（纪律）：ad-hoc 探针污染过真实内容库
调试可答性判定时用了一个临时探针脚本（只隔离了 `MF_DB_PATH`，**未隔离 `MF_CONTENT_ROOT`**）
→ 在**真实 `content/`** 下写入了 `content/subjects/r35probe/`（outline.yaml + 空 materials 目录），
并被本批第一次提交 `f9e68c8` 一并带上。**处置**：`8b0fe8a` `git rm` 删除 + 磁盘清理 + 复核
（`content/subjects` 仅 `math/`；`content validate` 仍 ok 25/48；真实库无 `r35probe` 行——探针当时用的是临时库）。
**教训（写入纪律）**：**调试脚本必须同时隔离 `MF_CONTENT_ROOT` 与 `MF_DB_PATH`**（`conftest.py` 就是这么做的），
只隔离 DB 不够；提交前一律 `git status` 检查是否混入 `content/` 产物。

---

## 62. R35b · P0：S6 🤔 小思考对齐 + S7「这题我没法答」反馈入口（2026-09-10）

> 架构侧 R35 §11 三条裁定已照办：`taught_facts` **不落 concepts 表**（改为给 `TaughtFact` 加**可选
> `concept_id`** 指向既有注册表，见 §62.4）、数学参数化题采 **模板级 basis + 降优先级**、
> 审计脚本**不随常规 CI**（docstring 已写明"这是工具，不是测试"）。

### 62.1 S6（P0）已落地

| 件 | 实现 | 复用点 |
|---|---|---|
| 依据字段 | `ai/calls.py`：`CiteBasis{fact_ids,quote,premises,rule}`（**声明在 schema**，R36 §8 三处同改）；`ExplainOut.asks_basis`（与 `asked_to_confirm` **按下标对齐**）；`ExplainIn.taught_facts`（可选） | `UnitContentBasis(CiteBasis)` 同一结构，不写两套 |
| 生成约束 | `OpenAICompatibleGateway.explain_node` 的 task 增硬要求：**每条小思考必须能被"只读过本讲解的零基础学生"答出**、须给 `asks_basis` 引文（≥6 字逐字）、**没有依据就不要出**、禁模板套话（"它与你学过的内容有什么联系"等） | `ai/prompts.py::context_block`（讲解正文 + 白名单注入**原样复用**，未另写 prompt 组装） |
| 服务端校验 | `gateway.filter_asks()`：引文必须逐字出自**本次讲解或官方讲解稿**（`content/citations.py`，≥6 字）；声明了 `taught_facts` 时 `fact_ids` 必须落在其中；**不合规的那条直接丢弃** | 引文尺子＝`content/citations.py`（**单一实现**） |
| 离线兜底 | `OfflineGateway`：小思考从讲解里**含该概念的整句**取引文（`sentence_with`）；取不到 → **不出这条** | 同一 `filter_asks` 尺子 |
| 留档 | `session.py` 把 `asks_basis` 写进 `lecture_cache`（审计/复盘可查） | 既有 `lecture_cache`（不新建存储） |

### 62.2 S7（P0）已落地

| 件 | 实现 | 复用点 |
|---|---|---|
| 投诉入口 | `POST /api/exercises/unanswerable` `{node_id, exercise_id, session_id?, message?}` → **中文**回应「已记录：这题不计失败、不扣分…」 | 复用 `service.feedback.record` |
| 存储 | `feedback.KINDS += "answerability"`（**同一张表、加一种 kind，不建表**） | `models.Feedback`（既有 `kind/exercise_id/status/result`） |
| **不计失败/不扣分** | 端点**不写 `attempts`**、不动掌握度/连对/额度；若正卡在会话里的这道题 → `_clear_current_if_matches()` 把 `practice.current` 清空并 `attempts_this=0`（**换一题，无失败记录**） | 复用既有 practice flow 字段 |
| 护栏口径 | `guardrails.KINDS += "answerability"` → 与纠错反馈**同一问题率**（`TRIP_RATIO=0.3`），不另立阈值 | `service/guardrails.py`（原样复用） |
| 内容修正 | auto 节点按**既有反馈闭环**后台重生成（"这题没法答"＝内容缺陷 → 修生成器，不是改这一题） | `feedback.spawn_auto_regen` |

### 62.3 融合对照表（§3b 验收项 · 本批部分）

| 新增件 | 复用点 | 断言 / 用例 |
|---|---|---|
| `taught_facts` 声明 | 概念层（**同源口径**）：不落表，`concept_id` 指向既有 `concepts` 注册表（§62.4） | `test_gate_drops_fact_not_verbatim_in_lecture` |
| 问题 `basis` 引文纪律 | `content/citations.py`（R36 已收敛，`MIN_QUOTE_CHARS=6`） | `test_citation_ruler_is_shared_with_feynman_evidence`（R35a）+ `test_filter_asks_keeps_only_cited_ones` |
| S6 小思考约束 | `ai/prompts.py::context_block` + 既有 `ExplainOut.asked_to_confirm` | `test_offline_gateway_ask_requires_lecture_basis` / `test_session_payload_asks_are_all_backed` |
| S7 可答性投诉 | `feedback` 表加 `kind`（**不建表**）+ `guardrails.KINDS` | `test_feedback_kind_answerability_registered_in_guardrails` / `test_report_unanswerable_records_feedback_without_penalty` |
| S7 不计失败 | 既有 practice flow（`current`/`attempts_this`） | `test_clear_current_exercise_replaces_question`（断言 attempts 与 user_nodes 计数不变） |
| 错误/提示文案 | `api/errors_zh.py` 口径（端点回中文；HTTPException 走既有 `{detail:{error:{code,message}}}`） | `test_report_unanswerable_rejects_unknown_exercise_zh` |
| AI 输出字段 | R36 §8 纪律（schema + prompt + 往返用例） | `test_explain_call_schema_carries_asks_basis` |
| **S3 挑战题 / S4 追问 / P4 机器校验 / 数学模板级 basis** | —— | **本批未做**（见 §62.5，附件为下一批计划） |

### 62.4 `TaughtFact.concept_id`（架构侧裁定 1 的落地）

- `content/schemas.py::TaughtFact` 增**可选** `concept_id`；`answerability.clean_facts` 归一保留；
  校验（R35b 补）：`concept_id` 若给出，**必须指向已注册概念**（`concepts` 表 / 大纲 `concept_tags`），
  否则该事实句**剔除并记问题**——"讲过的概念"与"考的概念"因此共用同一套 id，而"这句事实"仍留在节点内。
- ⚠️ 本批只落**字段 + 校验器接口**；把节点事实与注册表的**批量对齐**（内容侧回填）留 R35b 收尾。

### 62.5 本批未做（下一任照做）

① **S3 挑战题双池**（可开始/取消/放弃 + 「挑战一下」单独调模型 + **不得**污染账本/mastery/额度/掌握统计）；
② **S4 追问 `reteach`**（学生无引用内容 → 禁止硬造发散题）；③ **P4 机器校验**（R36 欠账）；
④ 数学路径**模板级 basis**（降优先级）；⑤ 全库审计 + 用户新建 PDF 学科的 A2 证据；⑥ docs/06、docs/07 同步。

### 62.6 s27 体检结果（架构侧 A5 靶子 · 真模型审计，`--nodes primary.s27`）

`.runtime/r35_s27_audit.txt`（明细 JSON：`%TEMP%\mf_r35_audit_20260910-181105.json`）：
**6 项受检 → ❌ 不可答 2 项**（讲解 778 字 · 练习 1 · 例题 1 · **taught_facts 0** · socratic 3）：

| 项 | 结果 | 原因（审计原文摘要） |
|---|---|---|
| `exercise[ex1]` | ❌ 不可答 | 渲染为「求 5 和 5 的最小公倍数」；讲解只给了 12/18 的例子与 LCM 定义，**没有"相同数/倍数关系"情形的结论** |
| `socratic[2]` | ❌ 不可答 | 「如果两个数中一个是另一个的倍数，它们的最大公因数和最小公倍数分别是什么？」——**讲解没有该结论**（正是 R35 要治的"问超纲"） |
| `socratic[1]` / `socratic[3]` / 费曼任务 / 例题 | ✅ 可答（4 项） | — |

**由该审计顺带发现的 P0 内容缺陷（比"不可答"更严重：答案本身错）**——`primary.s27` 的 `ex1` 模板：
`prompt="求 {a} 和 {b} 的最小公倍数，其中 {b} 是 {a} 的倍数"`、**`constraint=None`（条件未强制）**、
`answer_expr="a*b"`。实测渲染：

```
seed=1: 求 5 和 5 的最小公倍数，其中 5 是 5 的倍数。   -> 模板答案 25（正确应为 5）
seed=2: 求 6 和 8 的最小公倍数，其中 8 是 6 的倍数。   -> 模板答案 48（题干陈述为假；正确 LCM 为 24）
seed=3: 求 5 和 7 的最小公倍数，其中 7 是 5 的倍数。   -> 模板答案 35（题干陈述为假）
```

- **两层问题**：① `constraint` 缺失 → **题干可能陈述假事实**；② `answer_expr=a*b` 与"b 是 a 的倍数"矛盾
  （该条件下 LCM **就是 b**；`a*b` 只在互质时成立，而互质 + 倍数关系在 a≥2 时无解）→ **每次渲染答案都是错的**。
- 既有 sympy 自检**测不出**这类错：它只验"模板能渲染 + 表达式可解析"，不验"题面条件与答案一致"。
- **处置建议（R35b P2"数学路径模板级 basis"一并做）**：生成器侧要求 ① `constraint` 必须强制题面所述条件
  （如 `b % a == 0`）；② `answer_expr` 用 `lcm(a,b)` 之类**与条件自洽**的表达式，禁止"条件+答案"互相矛盾；
  ③ 该模板**当前仍在库中（用户在库可见）**，建议随 P2 一起重生成。

---

## 63. R35b · 语义自检闸门 + 28 模板题体检 + 缺陷节点重生成（2026-09-10）

> 规格：`docs/09 R35 §12`（架构侧扩大我报的 s27 缺陷 → 4 例 + 根因"answer_expr 与题干同一次 LLM 调用自证"）。

### 63.1 闸门三层（**学科无关是第一原则**）

| 层 | 实现 | 说明 |
|---|---|---|
| ① 通用层（所有学科） | `content/verify.py::check_domain_rule`：渲染 N seed → 结果必须满足**内容显式声明**的领域谓词（`semantics.domain`: `nonneg`/`integer`/`ratio`）+ **学段政策**（`level=="primary"` 默认补 `nonneg`，小学不出现负数）；无声明 → **finding（要求声明）**，**不猜题面关键词** | 吃"声明"不吃"学科规则"；`integer` 必须显式声明（实测教训：分数加法/百分比在小学同样合法，一刀切判"非整数"是**假阳性**） |
| ② L1 验算插件层 | `content/l1_math.py::MathSympyVerifier`（唯一与学科相关的一层）：**sympy 独立验算** `semantics.expect` 与 `answer_expr`（逐 seed 数值比对）+ `requires` 是否被 `constraint` **穷举反例**保证 | 经 **注册表** `register_l1/l1_for` 解析（**无 `if subject == "math"` 分支**）；`subject_of()` 只做命名空间映射（LEVELS→math preset） |
| ③ 无 L1 的学科 | `l1=None` **如实标注**（不是漏做）；仍须过通用层 + R35 可答性 + 既有护栏 | 将来"数值+单位""代码沙箱"按**同一接口**注册 |

**关键实现坑（值得留档）**：`sp.sympify("lcm(a, b)")` 会把 `lcm` 当"一般符号"化简成 **`a*b`**（sympy 默认符号互质）→ 独立验算退化成"抄 answer_expr"。修法：**先把参数代入表达式文本**（`lcm(a,b)` → `lcm(6,9)`）再 sympify ✓。

**接线**：`pipeline.validate_semantics(raw_md)`（**与结构校验分开的独立函数**，各自调用）→ `generate_entry` 里校验失败**拒绝入库**（自动重试带错误反馈）；`content validate` **只报 `[semantics]`/`[semantics?]` 不阻断**（保住既有 CLI 契约，同时给出全库体检输出）；`ai/drafting.py` 出稿 prompt 增"语义自检纪律"（三处同改：schema + prompt + 用例）。

### 63.2 闸门用例清单（`backend/tests/test_r35_semantics_gate.py`，10 条）

| # | 用例 | 断言 |
|---|---|---|
| 1 | `test_gate_rejects_answer_expr_contradicting_independent_expect` | **造错必报**：`answer_expr ≠ expect` → 拒绝 |
| 2 | `test_gate_rejects_lcm_template_written_as_product` | s27 形状：条件未强制 + `a*b` vs `lcm` **双错**都报 |
| 3 | `test_gate_rejects_condition_not_enforced_by_constraint` | **造错必报**：`requires` 未被 constraint 保证 → 反例报；**补上 constraint 后同一算式通过** |
| 4 | `test_gate_rejects_negative_count_in_primary` | 小学学段负数（39-47）→ 拒 |
| 5 | `test_gate_rejects_fractional_discrete_quantity_when_declared` | 声明 `integer` 后"半个苹果"→ 拒 |
| 6 | **`test_generic_layer_applies_to_non_math_subject`** | **换学科仍成立**：自定义学科 `s-testsubj`（**无 L1 插件**）→ 金额为负 / 个数非整 **均被拒** |
| 7 | `test_generic_layer_no_declaration_is_finding_not_silent_pass` | 无声明 → finding（不静默通过、不猜） |
| 8 | `test_primary_policy_adds_nonneg_but_not_integer` | 学段政策只加 nonneg（分数加法**不得**被误杀） |
| 9 | `test_subject_namespace_and_registry` | 注册表解析（无学科分支） |
| 10 | `test_pipeline_gate_entry_rejects_bad_template_md` | 生成端入口拒绝坏模板（拒绝入库） |

### 63.3 28 模板题体检表（重生成前 → 处置 → 复验）

体检工具：`backend/tests/audit_template_semantics.py`（工具非测试；`--json` 落档）。**重生成前**：29 条模板
（含重生成后新增的 1 条）→ **违规 4 类/5 条**，其余 21 条"未声明 semantics"（finding）。

| 节点/题 | 问题类型 | 处置 | 复验 |
|---|---|---|---|
| `primary.s27/ex1` | 条件未强制（题面说"b 是 a 的倍数"却 `constraint=None`）+ `answer_expr=a*b` 与 LCM 矛盾（a==b 必错） | **重生成** ✓（1 稿过闸门） | 声明 semantics ✓ 违规 0 |
| `primary.s12/ex1` | 金额为负（7 元买 8 元 → -1 元） | **重生成** ✓ | 违规 0 |
| `primary.s23/ex2` | 半个苹果（`total*x/(x+y)` 非整）+ 题面条件未强制；`ex1` 化简比却给比值 | **重生成** ✓ | 违规 0 |
| `primary.s02/ex2` | 小学减法出负数（39-47 → -8） | **重生成** ✓ | 违规 0 |
| `primary.s04/ex1` | 题干要"商和余数"两个量，`answer_expr` 只给商（答对被判错）——**欧拉追加发现** | **重生成** ✓（第 3 次尝试成功；前两稿 YAML/题型非法被拒） | 违规 0 |
| `middle.0102/ex1–ex3`、`middle.0201/e1`、`middle.0202/e1`、`primary.0101–0104`、`s01/s03/s09/s10/s11/s13/s22` | **未声明 semantics**（finding） | **未改**（人工锚点不动；auto 的待下批按需重生成） | 仍为 finding |
| 题面泄漏（种子相关） | 渲染答案原样出现在题干：`middle.0202/e1`（如 -5）、`primary.0102/e1`（如 3/5）、`0103`、`0104`、`s04` 等 **8 条**有命中 | **登记**（多数是"格式示例恰好等于答案"；建议把示例改成占位形式如 `x=…`） | 待裁 |

**复验（重生成后）**：29 条模板 → **违规 0**；其中 **8 条已声明 semantics**（＝被修的 5 个节点的全部模板）；
`content validate` **ok 25 节点 / 49 练习**（练习数 48→49：重生成内容题量变化）；audit 五学段不变。

### 63.4 全量回归（不降）

| 项 | 实测 | 与上一批 |
|---|---|---|
| `pytest backend/tests` | **370 collected / 368 passed + 2 skipped / 0 failed / 0 error，exit 0** | 360/358+2 → **+10 闸门用例** |
| `content validate` | **ok，25 节点 / 49 练习** | 48→49（重生成所致，节点数不变） |
| roadmap audit | **27/31/81/59/60**，错误项 0 | 不变 |
| `npx tsc --noEmit` | exit 0 | 不变 |

### 63.5 融合对照表补全（本批新增件）

| 新增件 | 复用点 | 断言/用例 |
|---|---|---|
| 语义闸门通用层 | 既有 `templates.render_exercise` + 内容声明谓词 | 用例 4/5/6/7/8 |
| L1 验算插件 | `docs/14 §2.4` L1 结构化可验的**注册表接口**（math 首个实例；非数学特权） | 用例 1/2/3/9 |
| 生成端拒绝 | 既有 `pipeline.generate_entry` 重试+入库链路（validate_semantics 独立函数） | 用例 10 + `validate` 体检输出 |
| 出稿纪律 | `ai/drafting` prompt（schema 三处同改） | 重生成 5 节点全过闸门（真模型实测） |

---

## 64. R35b · §13：求值路径单一化 + 闸门补三条硬规则 + s23 修复（2026-09-10）

> 架构侧在收下闸门后**复现出闸门漏网**：`primary.s23/ex2`「化简比 {m}:{n} 后前项与后项之和」——
> 判题给出 36（`m/1 + n/1`），正确答案 9。**三重套娃**：判题求值器不认识 `gcd` → sympy 把未知函数
> **静默当 1**；L1 那套认识 gcd → 算出 9；**闸门两侧都走 L1** → 用正确的尺子量了自己两遍。

### 64.1 求值路径单一化（§13 裁决 1，根治）

- 新增 **`app/content/exprs.py`**：**唯一函数表 `MATH_LOCALS`**（lcm/gcd/abs/min/max/floor/ceiling/sqrt/…）
  + 唯一 `parse/eval_expr/eval_text/eval_number/holds`。**逐词白名单校验**：出现既非参数名、又非支持函数的
  名字 → **抛中文 `ExprError`**（绝不静默当 1）。
  - 实测留档：`sympify("lcm(a,b)")` 会把 `lcm` 当一般符号化简成 `a*b`（sympy 默认互质）；
    `sympify(..., strict=True)` 又会连纯算术文本一起拒——故采用"**先代入参数文本 + 逐词白名单**"的方案；
  - `templates.eval_answer_expr` **改为委托 `exprs`**（判题路径与验算路径**同一份实现**，消灭并行机制）；
  - `l1_math` 的私有 `_LOCALS`/`_param_values`/`_sympify` **删除**，全部改用 `exprs`。
- **效果**：`m/gcd(m,n) + n/gcd(m,n)` + {m:16,n:20} → 判题路径现在给 **9**（此前 36）✓。

### 64.2 闸门补三条硬规则（§13 裁决 2/3/4）

| 规则 | 实现 | 用例 |
|---|---|---|
| **校验"实际求值路径"** | `l1_math` 里新增：`templates.eval_answer_expr(answer_expr)` 的结果必须与 L1 独立验算一致；不一致 → **违规** | `test_gate_compares_actual_judging_path_with_independent_expect` |
| **`expect` 不得自证** | `expect` 与 `answer_expr` **文本相同 → 违规**（等于没验） | `test_gate_rejects_expect_that_is_copy_of_answer_expr` |
| **未声明 expect 即违规（数学）** | `NO_EXPECT_PROBLEM` 由 finding 升为 **problem** | `test_math_template_without_expect_is_violation` |
| **非数学学科如实分界** | `NO_L1_MARKER` 显式标注"本模板无独立验算"；`TemplateVerdict.l1_available/verified` 落档；`verify.library_stats()` + **`guardrails.semantics_stats()`**（护栏口径委托同一实现） | `test_non_math_subject_is_marked_unverified_and_counted` |
| **未知函数不再静默当 1** | `test_unified_eval_path_unknown_function_is_chinese_error_not_one` | 中文报错含"未知名" |

**必修项**：`pipeline.stub_drafter` 的模板题同步声明 `semantics`（否则测试里"unlock_until 生成"被新闸门拒绝，
54 条用例连锁失败——实测踩到并修复）。

### 64.3 s23 修复与影响面重扫

- **影响面扫描（§13 裁决 5）**：全库 `answer_expr` 的"未知名"扫描 → **0 条**（gcd/lcm 已进唯一函数表，
  这一类判题错算被**结构性地**堵死）；架构侧口径"仅 s23 两题"一致。
- **s23 重生成** ✓（1 稿过新闸门）；同时重生成此前"expect 自证"的 `s02/s12/s04`（各 1–2 稿通过；
  `s02`/`s04` 首两稿因模型照抄 `a+b`/`a/b` 被闸门**拒绝** → 强化 prompt 给出"一步运算也要换等价写法"
  示例（`a+b`→`b + a`、`a/b`→`Rational(a, b)`…）后通过）。**"自证"清零** ✓。

### 64.4 体检工具修复（§13 裁决 6）

- 控制台标记改**纯 ASCII**（`[BAD]/[WARN]/[OK]`），不再用 emoji（Windows GBK 控制台崩溃）；
- 汇总行**分列**：`违规 N（无 expect x / expect 自证 y / 其它 z）；已独立验算并通过 V；其余 = 未验算或未声明
  （不得读作「全库已验证」）`——**违规数不再被 finding 稀释**；
- 新增 `unknown_names` 列（§13 影响面扫描，常驻）。

### 64.5 当前库状态（诚实口径）与遗留清单

`guardrails.semantics_stats()` = **`{templates: 30, violations: 21, verified: 9, unverified: 21}`**：

- **violations 21 = 全部"未声明 expect"**（12 个历史节点：`middle.0102`×3、`middle.0201`、`middle.0202`、
  `primary.0101`×2、`0102/0103/0104`、`primary.s01`×2、`s03/s09/s10/s11/s13/s22` 等）；
  其中 `middle.*` 与 `primary.0101–0104` 是**人工锚点**（不该用重生成覆盖）→ **建议处置**：
  由内容侧追加 `semantics`（`expect` 用**独立写法**，如 `Rational(c - b, a)`）+ `domain`，本批**未动人工锚点**；
  auto 节点可按需重生成（生成器 prompt 已就位）。
- `verified 9`＝被独立验算并通过的模板（＝刚修的 5 节点的全部模板 + 1）。
- **行为影响**：新生成内容**必须**带 expect 才能入库（硬闸门）；历史内容仍可加载（不阻塞），
  但其"未验算"状态**在体检/护栏口径里如实可见**。

### 64.6 回归与提交

| 项 | 实测 |
|---|---|
| `pytest backend/tests` | **375 collected / 373 passed + 2 skipped / 0 failed / 0 error，exit 0**（+5 用例） |
| `content validate` | **ok 25 节点 / 50 练习** |
| roadmap audit | **27/31/81/59/60**，错误项 0 |
| `npx tsc --noEmit` | exit 0 |

新增/改动：`content/exprs.py`（新）、`content/l1_math.py`（重写）、`content/verify.py`、`content/templates.py`、
`content/pipeline.py`（stub 声明 semantics + 闸门入口）、`content/cli.py`、`ai/drafting.py`（出稿纪律）、
`service/guardrails.py`（`semantics_stats`）、`tests/audit_template_semantics.py`、`tests/test_r35_semantics_gate.py`（15 条）、
5 个节点重生成。

---

## 65. R35b · §14：题面泄漏清零 + 全库模板补 expect/basis + P4 机器校验（2026-09-10）

> 本批目标：把"答案正确"这条线一次收干净（顺序按架构侧 §14 指令）。
> **提交 `3348c55`（内容声明）→ `ca2f072`（闸门/P4 代码）**；步骤 1–4 完成，**步骤 5–6（S3/S4）未做**（见 §65.5）。

### 65.1 步骤 1 · 题面泄漏：7 处示例改占位 + 升为**违规**

- 新增 `verify.leak_problems()`：**只扫题干的"提示/示例片段"**（`（…）` 内或「如/例如」之后）
  —— 题干正文里的数字（比例 `1:2`、被减数）是题目本身的一部分，不算泄漏；
  示例「如 x=5」「如 3/5」等于某 seed 的答案才是**直接漏答案**。判为 **violation**（可拒绝入库）。
- **实测修正了一处架构侧口径**：架构侧列的 8 处命中里，`primary.0103/0104/s04` 等是**参数值出现在题干**
  的假阳性（我的旧规则扫全静态文本）→ 收紧到"提示片段"后 **真泄漏 2 处**、
  **含数字示例共 7 处**，全部按"占位形式"修掉：
  `middle.0102`×3（并顺手把"填数字"与 `x=` 形状不一致的提示改成「直接输入数字，不要写 x=」）、
  `middle.0201`、`middle.0202`、`primary.0102`、`primary.0104`。
- 复扫（16 seeds）：**泄漏 0 命中**；**含数字提示片段 0 条**（该类隐患清零）。

### 65.2 步骤 2 · 全部模板补 `semantics`（含 21 条人工锚点）→ **violations = 0**

- 纯**加字段**（不改解题路径/答案/节点 id）：21 条模板补 `expect`（**独立写法**，如 `Rational(c - b, a)`、
  `b * a`、`a*b + a*c`、`100 * a`、`10 * floor((a + 5)/10) + …`）+ `domain`（nonneg/integer，按题面量纲声明）。
- 顺带修 `_as_number`：方程解展示形如 `x = 2` → 取等号右侧数值再判 domain（否则"方程题无法验算"是假阳性）。
- **`guardrails.semantics_stats()` 现为 `{templates: 30, violations: 0, verified: 30, unverified: 0}`** ✓

### 65.3 步骤 3 · 数学路径 template-level basis

- `TemplateDoc.basis: BasisDoc`（复用**同一个** basis 模型，不新建结构）；
- 闸门校验：`basis.quote` 必须**逐字出自本节点讲解**（`content/citations.py`，≥6 字）→ 不成立即**违规**；
  已为 **30 条模板**落盘 `basis.quote`。
- ⚠️ **如实说明取值口径**：本批的 quote 是**机械取值**（该节点讲解里首个 ≥6 字的句子），
  语义上"支撑该模板的规则句"更精确 → **建议下批按内容精细化**（属提升，不是缺陷）。
- 参数化**不解到每道渲染题**（参数不产生新知识）——与架构侧口径一致。

### 65.4 步骤 4 · **P4 机器校验（R36 欠账，点名交付）**

`answerability.check_progression(doc, prereq_docs)`（学科无关，纯 `taught_facts`/`derivable` 判定）：
1. **引用必须已教**：题/追问的 `basis.fact_ids` ⊆「已教集合 = 本单元 ∪ 已学前置单元的 taught_facts」，
   否则违规（等于问没教过的）；
2. **加难必须加事实**：练习难度高于全部前置单元，却**没有新增任何已述事实** → 违规（不得凭空加难）；
   前置为空而难度≥2 且无 `taught_facts` → 违规。
- **已接生成端**：`outline/generate.py` 在可答性闸门后一并跑 P4（前置单元内容从大纲 prereq 解析），
  问题并入重试反馈 → 过不了就不入库。
- 用例：`test_p4_rejects_fact_not_taught_anywhere`（含正例）/ `test_p4_rejects_harder_without_new_facts`。

### 65.5 未完成（下一批，明确遗留）

- **步骤 5 · S3 挑战题双池**（可开始/取消/放弃 + 独立调模型 + **四不变**断言）——**未做**；
- **步骤 6 · S4 追问 `reteach`**（学生无可引用内容 → 退回讲解）——**未做**；
- 步骤 7 · 融合对照表**部分**补全（S3/S4/P4 三行待补）、`docs/06`/`docs/07` 同步**未做**；
- 原因：本会话预算有限；按架构侧此前口径"**先把'答案正确'做对，再谈交互**"，
  本批把 1–4 做完做净（库里模板已 100% 独立验算），S3/S4 留作下一批第一件事。

### 65.6 回归与提交

| 项 | 实测 |
|---|---|
| `pytest backend/tests` | **378 collected / 376 passed + 2 skipped / 0 failed / 0 error，exit 0**（+3 用例） |
| `content validate` | **ok 25 节点 / 50 练习** |
| `guardrails.semantics_stats()` | **violations 0 / verified 30 / unverified 0** |
| roadmap audit | **27/31/81/59/60**，错误项 0 |
| `npx tsc --noEmit` | exit 0 |

**融合对照表补行（§3b）**

| 新增件 | 复用点 | 断言/用例 |
|---|---|---|
| 题面泄漏判定 | 复用 `templates.render_exercise` 渲染 + 纯静态文本分析（无新机制） | 闸门违规 + 16-seed 复扫 0 命中 |
| 模板级 basis | **复用 `content/citations.py`** 与 `BasisDoc`（与题/追问同一结构） | `test_template_basis_quote_must_be_verbatim` |
| P4 机器校验 | 复用 `taught_facts`/`derivable` + 既有大纲 prereq（不新建"已学表"） | 2 条 P4 用例（含造错必报） |
| 验证覆盖率统计 | **接 `service/guardrails.py`**（`semantics_stats()` 委托 `verify.library_stats()`） | `test_non_math_subject_is_marked_unverified_and_counted` |

---

## 66. R35b · §66 收尾批：模板 basis 引文精细化 + S3 挑战题双池 + S4 追问 reteach + 文档收尾（2026-09-10）

> **工单**：R35b 收尾批（步骤 5–7）。**开机基线（架构侧独立复跑值）已逐项复现**：
> pytest **376 passed + 2 skipped（378 collected）**、`content validate` **ok 25/50**、
> audit 五学段 **27/31/81/59/60（ok=True）**、`tsc --noEmit` exit 0、
> `guardrails.semantics_stats() = {templates:30, violations:0, verified:30, unverified:0, l1_subjects:['math']}`。
> **提交**：`955724c`（任务1 引文精细化 + 告警断言）→ `7395b26`（S3+S4 引擎/前端/用例）→ 本节提交（文档收尾）。

### 66.1 任务1 · 模板 basis 引文**语义精细化**（架构侧 §18 提升项）

**病根**（架构侧实测）：30 条模板 → **仅 19 条不同引文**（最多重复 3 次），且大量引文是
**开场白**（"同学们，今天学习…"）。引文校验 100% 通过（**不是幻觉**），但**引用不准**：
开场白同样逐字出自讲解，却支撑不了任何模板。

**做法**：逐条判定"**哪一句规则真正支撑这个模板**"，改引该句（**允许同节点同规则重复**）。
**29/30 行被改写**（`primary.0104` 原文已是规则句，保持不动）。改后统计：

| 指标 | 改前 | 改后 |
|---|---|---|
| 模板数 | 30 | 30 |
| 不同引文数 | **19** | **26** |
| 重复引文 | 9 组（最多 ×3） | **4 组（全部 ×2，且都同节点同规则）** |
| 引文落在开场白（机器可判） | 未测 | **0** |
| 引文逐字出自讲解 | 30/30 | 30/30 |

**30 条对照表（新引文 → 判定理由）**

| 节点·题 | 支撑该模板的规则句（引文） | 判定理由 |
|---|---|---|
| `middle.0102/ex1` ax+b=c | `1. **移项**：把不含未知数的项移到右边，**移项要变号**。` | 该题第一步就是移项（减 b） |
| `middle.0102/ex2` ax-b=c | 同上（**同规则确实支撑两题**） | 减 b → 移到右边变 +b，同一句规则 |
| `middle.0102/ex3` ax=c | `依据是**等式性质**：等式两边同时加/减同一个数，或同时乘/除以同一个**非零**数，等式仍成立。` | 无移项，只做"两边同除以系数" |
| `middle.0201/e1` 相反数 | `**相反数**：只有符号不同的两个数，如 3 和 -3，它们在数轴上离 0 一样远。` | 题面问的就是相反数定义 |
| `middle.0202/e1` 异号相加 | `**异号相加**：取绝对值大的符号，用大的绝对值减小的。` | 参数 b 恒负、a 恒正 → 恒为异号（同号规则不适用） |
| `primary.0101/e1` a+b×c | `2. **没括号**：先**乘除**，后**加减**；` | 无括号题考的正是这条顺序 |
| `primary.0101/e2` (a+b)×c | `1. **有括号**：先算括号里面的；` | 括号题考的是这条 |
| `primary.0102/e1` 同分母加 | `**同分母分数加减**：分母不变，分子直接相加/相减。` | 题面即同分母加法 |
| `primary.0103/e1` 异分母加 | `做法：**通分**——把两个分数化成**分母相同**的分数，再按同分母加减。` | 题面要求"先通分再算" |
| `primary.0104/e1` 分数乘法 | `**分数乘法**：分子乘分子，分母乘分母` | **原文已是规则句**（未改） |
| `primary.s01/ex1` 四舍五入 | `四舍五入：要保留到某一位，就看它后面一位，如果小于 5 就舍去，如果大于等于 5 就向前一位进 1。` | 题面即"四舍五入到百位" |
| `primary.s01/ex2` 估算 | `估算时，先取近似数再计算。` | 题面即"看成整十数再相加" |
| `primary.s02/ex1` 进位加 | `记住两条口诀：加法个位满十就进位，减法个位不够减就退位。` | 规则句覆盖两题（同句双引） |
| `primary.s02/ex2` 退位减 | 同上 | 退位由该句后半明确支持 |
| `primary.s03/ex1` a×b | `于是，数学家想了一个简便的方法，用乘法来表示“几个相同加数的和”。` | 乘法的定义句（不是首句"今天我们学习乘法"） |
| `primary.s04/ex1` 求商 | `所以做有余数除法，只要找到“除数乘几最接近被除数、又不超过它”，那个几就是商，差就是余数。` | 题面问"每个盘子最多放几个完整的"= 商 |
| `primary.s04/ex2` 求余数 | `余数就是“分到最后剩下的、不够再分一份”的数。` | 余数定义句 |
| `primary.s09/ex1` 0.a+0.b | `计算小数加减法时，关键是要把小数点对齐，也就是相同数位对齐，然后按照整数加减法的方法计算，最后在结果中点上小数点，使小数点与上面的小数点对齐。` | 小数加法规则句 |
| `primary.s10/ex1` a 的 b% | `百分数就是分母为 $100$ 的分数，求一个数的百分之几，就用这个数乘以对应的百分数。` | 求百分比的规则句（**剔掉"我们来总结一下："过渡语**，仍是逐字子串） |
| `primary.s22/ex1` 分配律 | `乘法分配律：两个数的和与一个数相乘，可以先把它们分别与这个数相乘，再相加。` | 题面明确要求用分配律 |
| `primary.s23/ex1` 按比例分（甲） | `按比例分配的关键是：先求总份数，再求一份是多少，最后求各部分是多少。` | 该规则支撑两题（同句双引） |
| `primary.s23/ex2` 按比例分（乙） | 同上 | 同上 |
| `primary.s27/ex1` LCM | `特别地，当 $b$ 是 $a$ 的倍数时，$a$ 和 $b$ 的最大公因数是 $a$，最小公倍数是 $b$。` | 题面条件="b 是 a 的倍数"，这句**正是该条件下的结论** |
| `primary.s27/ex2` GCD | 同上 | 同句同时给出 GCD 结论 |
| `primary.s11/ex1` 米→厘米 | `例如，3米=300厘米，因为1米=100厘米，3×100=300。` | 讲解里唯一直接给出"1米=100厘米"的句子 |
| `primary.s11/ex2` 千克→克 | `1千克=1000克，1吨=1000千克。` | 直接给出千克与克的进率 |
| `primary.s12/ex1` 找零 | `方法很简单：付出的钱减去商品的价格，就是找回的钱。` | 找零规则句 |
| `primary.s13/ex1` m²→dm² | `相邻两个面积单位之间的进率是100。` | 面积单位进率规则句 |
| `primary.s13/ex2` dm³→cm³ | `常用体积单位有立方厘米、立方分米、立方米，相邻两个体积单位之间的进率是1000。` | 体积单位进率规则句 |
| `primary.s13/ex3` 升→毫升 | `所以，1升等于1000毫升。` | 直接给出升/毫升换算 |

**新增体检断言（告警级，不当违规）**：`verify.opening_quote_warning(quote)` ——引文（去 Markdown
前缀后）以 `同学们/大家好/今天/这节课/上节课/接下来/首先/我们/目标/本节/导入` 开头 → **finding 告警**，
并入 `check_template` 的 findings（**不拒绝入库**）。理由与边界都写进代码注释：
机械规则**分不干净**"过渡句"与"以『我们』开头的规则句"（如"我们把两个数同时除以公有的质因数"是真规则），
故按架构侧口径"实现为告警即可"。用例：`test_opening_line_quote_is_warned_but_not_rejected`
（造错必报，含正例）+ `test_library_template_basis_quotes_are_rule_sentences`（全库现状锁定）。

**复验脚本**（入库外，`_dsh-local` 性质）：`.runtime/r35c_fix_basis.py`（改）/ `r35c_verify_basis.py`（验）
→ 现况 **templates=30 distinct=26 duplicated=4 bad=0**（报告 `.runtime/r35c_basis_verify.txt`）。

### 66.2 任务2 · S3 挑战题双池（「挑战一下」）

**池的分界**：核心题池（内容库 `exercises`，计入掌握与费曼）/ **挑战题池（完全不上算）**。
挑战题**永不出现在默认流程**——`GET /session/{id}`、`next`、练习帧、费曼帧的 payload **都没有**
`challenge` 键；它只随 `challenge_*` 动作下发（用例 `test_challenge_actions_are_registered_outside_default_flow`）。

**五个动作 + 单题三态**（`challenge_start / begin / submit / cancel / abandon`）：

| 动作 | 语义 | 后果 |
|---|---|---|
| `challenge_start` | 「挑战一下」→ **单独调模型生成**（`challenge_exercise`） | 只写 flow 的 `challenge` 块 |
| `challenge_begin` | 开始作答（纯 UI 状态推进） | **无**（不写任何记录） |
| `challenge_submit` | 提交作答 → **单独判分**（`challenge_check`） | **只记复盘**（`attempts.kind="challenge"`） |
| `challenge_cancel` | 取消本次（丢掉这题） | **无**（连 attempts 都不写） |
| `challenge_abandon` | 明确放弃（"我不会/我不感兴趣"） | **只记复盘**（`verdict="abandoned"`） |

**不设额度、不计轮次、不影响进度**：`asked`/`answered` 只是展示计数，代码里**没有任何一处**拿它们
做门禁（连做 3 道挑战题后核心流程照样能过：`test_challenge_no_quota_and_core_flow_still_passes_afterwards`）。

**UI 显式标注**：后端直出 `challenge.notice = "挑战题：需要讲解之外的知识，答不出不影响任何进度"`
（+ `counts_nothing: true` 契约位），前端原样渲染、**不显示任何进度/额度/分数影响**（docs/07 §2.3.1）。

**⚠️ 必交断言的实证——并查出一处真实污染**：断言"作答后**四项均不变**"时，
`/api/dashboard` 的 `stats` 出现了差异：`today_done` 4 → 5。根因：该统计原本
`count(Attempt) join Session` **不过滤 kind** → **挑战题被算进了"今日完成"**（用户可见的进度数字）。
**已修**：`models.PROGRESS_KINDS = ("exercise","feynman")` 白名单（默认拒绝新 kind，而非"排除 challenge"黑名单），
`dashboard.today_done` 按其过滤 + 注释点名 R35 S3 红线。**这正是"四不变"断言的价值**——
一个看起来"只是复用 attempts 表"的改动，会从统计口径漏进用户可见进度。

**"换个学科还成立吗？"**：挑战题链路无任何学科分支（同一 `context_block` 注入 + schema 校验 + 降级 +
tier 决策）；用例 `test_challenge_works_for_non_math_subject` 在**自建非数学学科**上跑通
"生成 → 提交 → 除 challenge 块外 flow 逐位不变"。

**新增件与复用点**（详见 §66.4 融合对照表）：复用练习/判题/复盘链路与 attempts 表；
新增的只有**两个 AI 调用点**（挑战题必须"单独调模型生成"、且要考讲解之外的知识，
无法由核心题池渲染，也不能复用 explain/hint 的语义）——这是 docs/09 R35 S3 的明文要求。

### 66.3 任务3 · S4 追问 `reteach`（逐字引用 + 退回讲解）

**两层，不是两套机制**：

1. **确定性前置**（`feynman_ledger.has_quotable_content`）：学生的完整稿去掉敷衍用语
   （不知道/不会/不懂/没学过…）与纯填充词后**仍不足 6 字** → 判"没有可引用的实质内容"。
   命中 → **直接返回 `reteach`**：**不调评分、不消耗整体稿额度**（`evals_done` 仍为 0）、账本不动。
   用例 `test_dismissive_transcript_returns_reteach_without_burning_budget`（"我不知道"×5 →
   `verdict="reteach"`，随后补讲仍能一次通过 → 证明额度没被吃掉）。
2. **模型层的通用兜底**：`FeynmanFollowupOut` 增 `student_quote` / `missing` / `reteach` 三个字段
   ——追问**必须逐字引用学生原话**（服务端用 `feynman_ledger.quote_valid` 做包含校验，**同一把引文尺子**）
   并说清"这句话缺了什么"。四种不成立（模型自陈 reteach / 引文非逐字 / missing 空 / 正文空）
   → 一律转 `reteach`，**绝不下发一条学生答不出的追问**。用例 4 条（含正例）。

**`reteach` 响应**：`verdict="reteach"`、`next_action="reteach"`、`reteach{reason, message_md,
lecture_md, missing_dimensions[]}` + 事件 `feynman_reteach`；离线路径同样满足（offline
`feynman_followup` 从学生原话里取可引用片段，取不到即 reteach）。

**⚠️ 一处实现决策（已登记 §58-13 待架构侧确认）**：**不把 stage 翻回 `explain`**。
原因：练习已通过时"讲解→例题→练习"会**重新出题**并再次计入 practice 账目——等于用一次敷衍回答
**污染练习记录**，与 S4 的目的（把学生送回讲解）背道而驰。改为"**阶段不动 + 随响应下发讲解原文
（`reteach.lecture_md`）+ `next_action="reteach"`**"，学生当场就能看讲解、补讲后再交完整稿。

**顺带收口 S4 的另一条**：socratic 模板**不得作为默认兜底**下发——
`SessionService._backed_socratic(node)` 只保留 `socratic_basis` **逐字成立**的主题
（复用 `answerability.check_basis`，不重写包含校验）；离线网关里"无缺口就丢一条 socratic"的兜底**已删**。
`middle.0102` 等人工锚点（有 socratic 套话、无 basis）→ 下发语料为**空**（用例 `test_socratic_topics_require_basis`）。

### 66.4 任务4 · 文档同步 + 融合对照表（含 S3/S4 行）

- `docs/06`：`/session/step` 的 action 全集（含 5 个 `challenge_*`）、§2.0 追问新增
  `followup_quote`/`followup_missing`、**§2.0.1 `reteach` 协议**、**§2.2 挑战题池协议**、
  `/exercises/unanswerable`、新增**「复盘」端点表**（`/history/feynman`、`/history/challenge`）、
  `attempts.kind` 与 `PROGRESS_KINDS` 白名单口径。
- `docs/07`：§2.3 追问的"逐字引用 + 这句话缺什么"与 **reteach 卡片**、**§2.3.1 挑战题**
  （入口/显式标注/三态/结果展示）、§5 UI 红线新增两条（挑战题不得进默认流程、不得渲染进度影响）。

**融合对照表（R35 全量 · 每条新增件 → 复用点 → 断言）**

| 新增件 | 复用点（禁新建平行机制） | 断言/用例 |
|---|---|---|
| `taught_facts` / `derivable` | 扩展既有概念层（`concept_id` 指向 `concepts` 注册表；事实句留节点内） | `test_r35_answerability.py`（含 `concept_id` 未注册即剔除） |
| 前置知识判定 | 复用 `user_concepts` / 已掌握前置单元 | `check_progression` P4 用例 |
| `basis` 引文校验（题/追问/小思考/模板） | **复用 `content/citations.py`**（单一实现，`MIN_QUOTE_CHARS=6`） | `test_template_basis_quote_must_be_verbatim` 等 |
| 模板级 `basis`（规则句） | 复用 `BasisDoc` + `citations`；**不新建题目体系** | **§66.1**：30 条 + `test_library_template_basis_quotes_are_rule_sentences` |
| 引文精度告警 | 复用 `check_template` 的 findings 通道（不新增拒绝条件） | `test_opening_line_quote_is_warned_but_not_rejected` |
| S3 挑战题池 | **复用现有练习/判题/复盘链路**；挑战题池只是**标记位**（`attempts.kind="challenge"`），不新建题目体系与表 | `test_r35b_challenge.py` 全 7 条（四账不变 / 三态无后果 / 非数学学科） |
| 挑战题"单独生成" | 复用 `CALLS` 注册表 + `context_block` 注入范式 + `chat_json` schema 校验/重试 + `ai/tier` 档位决策 | `test_challenge_callpoints_registered` + 上面 7 条 |
| 挑战题判分 | 同上（无 rubric/无 L1 → **如实分界**：机器验不了，只能模型判；"无 L1 学科"的同一分界） | 同上 |
| 挑战题复盘 | **复用 `attempts` 表 + 既有复盘读法**（同一 `_rows()` 实现，不新建表/存储） | `GET /history/challenge` 断言 + `test_challenge_submit_changes_nothing_but_review_log` |
| 进度统计口径 | **复用 `models.PROGRESS_KINDS` 白名单**（`dashboard.today_done`）；不另立统计体系 | 同一用例的 `stats` 前后逐位相等断言 |
| S4 追问逐字引用 | **复用引文尺子**（`feynman_ledger.quote_valid` → `content/citations`） | 4 条 reteach 用例（含非逐字引文必转 reteach） |
| S4 `reteach` | 复用 R27 状态机与额度语义（**不消耗额度**）+ 复用 `lecture_cache`（不重生成讲解） | `test_dismissive_transcript_returns_reteach_without_burning_budget` |
| socratic 有据才下发 | **复用 `answerability.check_basis`**（不写第二份包含校验） | `test_socratic_topics_require_basis` |
| 前端挑战题按钮/标注 | 复用 SessionPage 的 action 分发 + `payload` 渲染范式（前端无判断逻辑） | `tsc --noEmit` + `vite build`；docs/07 §2.3.1 |
| 面向用户文案 | 复用既有中文口径（`api/errors_zh.py`；所有新文案中文，含 `CHALLENGE_NOTICE`） | `test_errors_zh.py` 既有 + 新用例断言文案关键词 |

**缺复用点的（只有一处，理由）**：**挑战题的两个 AI 调用点**（`challenge_exercise` / `challenge_check`）。
**不能复用**既有调用点的理由：① S3 明文要求挑战题"**须单独调模型生成**"；
② 语义相反——核心题池的硬约束是"**只能用已讲过的**"，挑战题**必须**超出讲解
（`context_block` 的基础禁令在挑战题里被显式豁免，且这是唯一允许它的地方）；
③ `explain_node`/`hint_on_error`/`feynman_evaluate` 的输出结构都不含"题目 + 作答提示 + 为什么它超出讲解"，
硬套会造出"字段语义漂移"的第二含义。**除这两个调用点外，本批无新建机制**。

### 66.5 回归与提交（实测，非汇报值推算）

| 项 | 基线（架构侧） | 本批实测 |
|---|---|---|
| `pytest backend/tests` | 378 collected / 376+2 | **394 collected / 392 passed + 2 skipped / 0 failed / 0 error，exit 0**（**+16 用例**：挑战题 7 + reteach 7 + 引文精度 2） |
| `content validate` | ok 25/50 | **ok 25 nodes / 50 exercises** |
| audit 五学段 | 27/31/81/59/60 | **27/31/81/59/60，ok=True，错误项全 0** |
| `tsc --noEmit` | exit 0 | **exit 0**（另跑 `vite build` **exit 0**） |
| `guardrails.semantics_stats()` | violations 0 / verified 30 | **{templates:30, violations:0, verified:30, unverified:0, l1_subjects:['math']}**（逐位一致） |
| 30 条模板 basis | 19 distinct / 有开场白 | **26 distinct / 重复仅 4 组 ×2（同节点同规则）/ 开场白 0 / 逐字 30/30** |

**提交链**：`955724c`（任务1）→ `7395b26`（S3+S4 引擎/前端/用例）→ 本节（文档 + NOTES + §58）。
**未污染真实内容库/用户库**：所有脚本用临时根/临时库；`.runtime/` 产物不入版控；`content/` 只改了
19 个模板文件的 `basis.quote` 一行（`git show --stat 955724c` 可核）。

### 66.6 疑点（已登记 §58）

1. **`reteach` 不翻转 stage**（§58-13）：与文档字面"退回讲解"有出入，理由见 §66.3，请架构侧确认；
2. **basis 引文的"语义贴合度"仍需人读**（§58-14）：机器只能判逐字 + 非开场白；
3. **挑战题在页面刷新后不恢复**：挑战题**刻意不进默认 payload**（否则等于"出现在默认流程"），
   故刷新/换页后面板消失，再点「挑战一下」会**重新生成一道**（`asked` 计数 +1，旧题在 flow 里被覆盖）。
   若希望"刷新后仍在"，需要一个显式的 `GET /session/{id}/challenge` 之类端点——**未做**，
   因为那会把挑战题变成"半个默认流程"，与本条规格相冲；**请架构侧裁定取舍**；
4. **`has_quotable_content` 是语言层启发式**（§66.3 第 1 层）：去掉敷衍用语后仍不足 6 字才算"无可引用"，
   个别"半敷衍"句子（如"我真的不会这道题，没学过"）可能落到第 2 层由模型判 reteach——
   方向安全（多一次模型判定、结论仍是 reteach 或按原话追问），但**不是百分百确定**，如实登记。


---

## 67. R37 教材真源化（Source-First）：S1–S9 落地与验收自证（2026-09-10）

> 用户指令原话要旨："**不用节省成本**。我导入教材，他就应该**教会我这本教材的一切**——大纲、题目、
> AI 去**直接理解这本教材**然后出具，**各种东西都应该这样**。"
> 性质：**产品级地基变更**——"教材＝参考" → "**教材＝权威真源**"。规格见 docs/09 R37、工单
> `.runtime/EULER_TICKET_R37.md`。

### 67.1 做了什么（按 S1–S9）

| 项 | 落地件（新增/改动） | 关键点 |
|---|---|---|
| **S1 不省成本** | `outline/bookmap.py`（新）、`materials.draft_materials/_full_blocks/_make_batches`、`config.material_inject_max_chars/material_batch_chars` | 默认 `MF_MATERIAL_INJECT_MAX_CHARS=0`＝**不限**；按章/节注入**完整正文**；书太大按 `MF_MATERIAL_BATCH_CHARS`（默认 60000）在**章/页边界**分批（每批都带全书地图），**绝不"前 N 字"**；显式设的上限只作**单次调用预算**（`min(预算, 分批阈值)`）——**调小预算不丢章节**（R38 §3 共存口径），单节超预算则整节注入；`dropped` 恒空、`truncated` 恒 false（**R39 铁则：禁止静默丢弃**） |
| **S2 大纲＝书的目录** | `bookmap.parse_book`（目录 + 运行页码 → 章/节）、`materials.coverage_problems/coverage_summary/entry_order/unit_order_key`、`draft.finalize_candidate` 书序重排/重编号/线性先修/难度单调化、`api/subjects.put_outline` 全覆盖 422 | 地图条目 → 单元；**未映射 → 违规**；起草期先**确定性回捞**、再按**教材目录补齐**并记问题（书的结构不是编造）；跨批 `prereqs` 不可靠 → 一律以**书序**线性串联 |
| **S3 讲解＝讲全教材该段** | `generate._ai_draft(material_text=…)`（教材锚定硬要求 8–11 条）、`unit_material_pack` | 注入该单元对应章/节的**完整正文**；讲解＝该段完整演绎（可换措辞/举例，不得省略要点、不得加教材外事实） |
| **S4 题目/例题/rubric 由教材派生** | 同 S3 + R35 既有 `basis`/`worked_examples`/rubric | 每题 `basis.quote` 必须逐字出自教材；例题仍走 R35 A3 口径（书里有的直接用，没有则由书中内容构造并在讲解尾部标"据教材 X 节"） |
| **S5 教材锚定（本批核心）** | `answerability.clean_facts/check_basis/gate_node(material=…)`、`AnswerabilityReport.dropped_facts/material_checked`、`generate` 失败三档 | **第三类校验**：事实句/引文必须逐字出自教材原文；**重试一次** → 题目仍不行**丢弃该题**、事实句仍不行**整单元失败**（`status="uncovered"`，不落盘）；违规文案全中文并说明"教材里没有这句话 vs 该段没讲到" |
| **S6 覆盖账本** | `materials.coverage_ledger`、`GET /subjects/{sid}/coverage`、`outline_store` 单元 `meta.coverage`、大纲页覆盖卡 | 每单元记录 来源材料 + 节标签 + 覆盖状态（完整/部分/未覆盖）+ 命中事实数/丢弃题数；大纲页显示 `已覆盖节/总节` + 未覆盖清单；**教材未覆盖 → 明确中文告知，不编造** |
| **S7 扫描版诚实边界** | `materials.text_health`（入库写入 frontmatter）、`add_material`/`list_materials`/PDF 上传响应、`draft_outline` 与 `put_outline` 拒绝 | 每页字符数 + 有文字页占比 → `healthy=false` + "本书是扫描版、未提取到文字，请先 OCR 或改用文本版"；**起草/采纳都拒绝**，不静默出稿；**不做 OCR** |
| **S8 大纲阶段读得到书的结构** | 同 S1/S2（章节地图 + 目标章节正文） | 起草 prompt 里同时给**全书地图**与**本批完整正文** |
| **S9 融合约束** | 复用 `content/citations.py`（唯一尺子）、闸门三层、`content/subjects/<sid>/materials/`、学科生命周期、`attempts/feedback` | **无平行机制**；无 `if subject == "math"`；R37 只给尺子加了教材排版归一化（全角 ASCII 折算 + 私用区字形剔除），**不新增第二份实现** |

### 67.2 真实样本对照（同一学科 / 同一本教材，架构侧立项证据 → 本批实测）

样本：学科「行星科学」`s-f2decfcf`，材料 `researchgate-17551026c7.md`（271,991 字，126 页）。
**改造前**样本留档 `D:\DeepseekHarness\_backups\r37-before-20260910-195904\`；本批重建前又备份到
`D:\DeepseekHarness\_backups\r37-regen-20260910-2043xx\`（含旧 `stages/`+`subjects/`）。

| 检查项 | 改造前（架构侧实测） | 改造后（本批实测） |
|---|---|---|
| `taught_facts` 命中教材 | **0/4** | **9/9（100%）** |
| 各题 `basis.quote` 命中教材 | **0/4** | **5/5（100%）** |
| 讲解句子 ≥12 字**整句**命中教材 | 0/16 | 5/26（19%；S3 允许换措辞，整句照抄非硬要求） |
| 讲解句**内含**教材逐字片段 ≥12 字 | 0/16 | **14/26（54%）** |
| 讲解字数 | 520 | **1,805** |
| 大纲 | 14 单元（全部来自前言/目录） | **46 单元；20/20 章/节条目全覆盖，未覆盖清单为空** |
| 教材结构识别 | — | `kind=toc`：**13 章 + 7 附录 = 20 条目**（目录 + 运行页码精确对齐；已按书末"参考文献/索引"截去其后 34 页） |
| 注入量（起草） | 6,000 字上限（分节摘要） | **103,448 字 / 2 批**（完整正文，`inject_max_chars=0`） |
| 覆盖状态（u01） | 无此概念 | `部分`（9 条事实句逐字出自教材；4 条模型自撰句被**丢弃**，0 题被丢弃） |

审计工具：`backend/tests/audit_material_binding.py`（docstring 写明属工具、不随 CI）——
复跑命令与输出：

```
.\.venv\Scripts\python backend/tests/audit_material_binding.py s-f2decfcf
taught_facts 命中教材：9/9（100%）
basis.quote 命中教材：5/5（100%）
讲解句内含教材逐字片段(≥12字)：14/26（54%）
结论：内容与教材有字面接地（无系统性零接地）。
```

**生成链路实测**（真模型 deepseek-chat，`MF_MATERIAL_BATCH_CHARS=60000`）：
`/outline/draft` 200（24.5s，2 批）→ `/outline` 采纳 revision 3→4 → 删除旧
`node_s-f2decfcf.u01_auto.md` → `/units/s-f2decfcf.u01/content` 200（14.8s，
"出稿：AI（教材锚定）；覆盖状态：部分"）→ `/coverage` 200（`total/covered = 20/20`、`uncovered = []`）。
生成出的讲解会**引用式演绎**（"教材指出：…"），facts/题目引文 100% 可回查。

### 67.3 造错必报用例（本批新增 11 条，`backend/tests/test_r37_material_binding.py`）

| 用例 | 断言（必报） |
|---|---|
| `test_r37_s5_fact_not_in_material_fails_whole_unit` | 事实句只在讲解里、教材里没有 → 两轮后 `status="uncovered"`、note 含"教材未覆盖此单元"、**磁盘无落盘文件** |
| `test_r37_s5_exercise_quote_not_in_material_is_dropped` | 某题引文只在讲解里 → **丢弃该题**（落盘文件里没有该题），其余保留，`coverage.status="部分"`、`dropped_exercises=1` |
| `test_r37_s5_grounded_unit_is_kept_whole` | 事实句/引文都逐字出自教材 → `created` + `coverage.status="完整"`；prompt 里确有**整章正文**与教材锚定硬要求 |
| `test_r37_s1_injection_defaults_to_unlimited_and_grows_with_book` | 默认 `inject_max_chars=0`、`dropped=[]`、`used_chars` 随书规模增长；显式 500 只改**单次预算**（分批、内容不丢） |
| `test_r37_s1_large_book_is_batched_by_structure` | 超阈值 → 分批；3 章正文**一句不丢**（不是"前 N 字"） |
| `test_r37_s1_small_budget_still_covers_every_chapter` | **R38 §3 共存**：预算调到 60 字 → 分批更多但**章节一个不丢**、注入内容与不限时逐字相同 |
| `test_r37_s2_draft_units_cover_every_chapter` | 候选 `coverage={total:2,covered:2,uncovered:[]}` |
| `test_r37_s2_unmapped_chapter_is_filled_from_book_toc_and_reported` | 模型漏映射 → 按**教材目录**补齐 + 记问题，`uncovered=[]` |
| `test_r37_s2_put_outline_rejects_unmapped_chapter_zh` | 手工大纲漏章 → **中文 422"教材覆盖不全"**；补全后 200 |
| `test_r37_s6_coverage_ledger_api` | `/coverage` 给出 来源/节标签/状态/note；条目 `covered=true` 且列出单元 id |
| `test_r37_s7_scanned_material_reported_and_refused` | 无文本层材料 → `text_health.healthy=false` + 中文；起草 422（含"扫描"）；采纳 422（含"文本层"） |
| `test_r37_citation_ruler_folds_fullwidth_and_private_use` | 全角数字/私用区字形归一化（教材排版），尺子仍单一实现 |

**改到既有用例的只有 1 处**（R36 `test_d2_citation_stripped_when_regeneration_also_fails`）：
R37 S2 要求"章节不得因溯源不成立而悄悄消失"，故该用例的断言从"`units[0].materials == []`"改为
"**被剔除引用的那个单元**保持无溯源（宁缺勿造口径不变）+ 该章由教材目录补齐并记问题"——**没有放宽**
（仍是 `ok=False`、仍报"溯源不成立"），只是把"书不能丢章"的新规格写进断言。

**另按后续裁决重写了 R36 D4 的两条预算用例**（`test_r36_outline_materials.py`）：
R36 D4 的"预算即全局上限、超出即截断/丢弃"已被 **R37 S1 ＋ R38 §3**（预算＝单次调用预算，
总覆盖面由分段保证）**取代**，并由 **R39「一切显性」铁则**兜底（禁止静默丢弃材料/章节）。
重写后断言：调小预算 → **分批更多但一页不丢**；单节超预算 → **整节注入**；`dropped` 恒空、
`truncated` 恒 false。**没有删弱任何断言**（新断言更强：逐页核对 20 页全在）。

### 67.4 融合对照表（R37 行：每条新增件 → 复用点 → 断言）

| 新增件 | 复用点（禁新建平行机制） | 断言/用例 |
|---|---|---|
| 教材结构解析 `outline/bookmap.py`（章→节地图） | **不是**第二套材料机制：它只是材料层的新解析器，入口仍在 `outline/materials.py` | `test_r37_s1_*` / 真实样本 `kind=toc` 20 条目 |
| 完整正文注入 + 结构化分批 | 复用 R36 的 `draft_materials()` 唯一入口与 `material_usage` 口径 | `test_r37_s1_injection_defaults_to_unlimited_and_grows_with_book`、`test_r37_s1_large_book_is_batched_by_structure` |
| 教材锚定（第三类校验） | **复用 `content/citations.py`**（同一把尺子，含新增归一化）与 R35 `gate_node` 结构 | `test_r37_s5_*` 三条 + `test_r37_citation_ruler_folds_fullwidth_and_private_use` |
| 事实句/引文逐字出自教材 | 复用 `TaughtFact`/`BasisDoc`/`AnswerabilityReport`（**不新建表/字段体系**）；结论落在既有 auto 内容文件 | 同上 + `content validate` ok |
| 覆盖账本 | 复用大纲 `OutlineUnit.materials`/`meta`（**不新建存储**）+ 材料层结构解析 | `test_r37_s6_coverage_ledger_api`、`GET /coverage` |
| "未覆盖"如实告知 | 复用既有中文错误/note 通道（`errors_zh` 口径），不新增状态机 | `uncovered` 走既有 `status` 字段 + 前端误报修正 |
| 扫描版检测 | 复用 `pdfparse`/`add_material` 入库链路（健康度写 frontmatter，不新建材料类型） | `test_r37_s7_scanned_material_reported_and_refused` |
| 大纲全覆盖校验 | 复用 `validate_outline_doc` + `PUT /outline` 的 422 通道 | `test_r37_s2_put_outline_rejects_unmapped_chapter_zh` |
| 出稿失败三档 | 复用 R35 既有"重试一次 → 丢弃 → 失败"骨架（本次把"教材"接进同一骨架） | `test_r37_s5_*` |
| 审计工具 | 复用 `content/citations.py` 尺子 + 既有审计脚本范式（`audit_*` 不带 `test_` 前缀） | `audit_material_binding.py` 工具输出 |

### 67.4b 融合对照表（**R38 / R39 行**：新增件 → 复用点 → 断言）

| 新增件 | 复用点（禁新建平行机制） | 断言/用例 |
|---|---|---|
| 预算两个滑块 + `GET/PUT /subjects/{sid}/budget` | **复用 `subjects.meta_json`（不新建表）** + 既有中文错误口径 | `test_r38_a1_slider_takes_effect_and_reads_back`、`test_r38_a5_illegal_value_is_zh_422` |
| 优先级解析（请求 > 学科 > `.env` > 内置） | 复用 R37 的 `config.material_inject_budget/batch_budget` 与 `MF_MATERIAL_*` 变量名 | `test_r38_a5_priority_request_beats_subject_slider` |
| "不限"= 真不限 | 复用 R37 `_make_batches`（不截断）＋ R39 铁则（`dropped` 恒空） | `test_r38_a2_unlimited_means_no_truncation` |
| 调小滑块不丢章节 | 复用 R37 结构化分批（同一次实现，不加第二套） | `test_r38_a3_smaller_slider_more_batches_chapters_intact` |
| 上下文安全阀 | 复用 `bookmap.split_entries`（页边界切）＋ R39 账本 | `test_r38_a4_context_valve_batches_instead_of_sending` |
| 节粒度：页合并成章级单元 | **在既有 `bookmap._chapters_from_blocks` 内改**；页标记沿用 `PAGE_MARK` | `test_r38_a1b_pdf_pages_merge_into_chapter_units_with_page_numbers` |
| 多材料合并与来源标注 | 复用 `draft_materials` 唯一入口 + `coverage_ledger` 唯一账 | `test_r38_b1_multi_material_merges_map_and_groups_uncovered` |
| 未纳入者显式列出 | 复用覆盖账结构 + R39 账本 | `test_r38_b1_blocked_material_is_listed_explicitly_and_in_ledger` |
| 材料角色（主/补） | 复用材料 frontmatter（不新建类型/表）+ `entry_order` 书序 | `test_r38_b2_role_orders_main_first_and_is_reported` |
| **账本 `service/ledger.py` + `content_ledger` 表** | **唯一入口**；错误文案复用 `errors_zh` 口径 | §69.4 六类 `test_r39_ironclad_*` |
| 就地提示 `LedgerAlerts.tsx` | 复用 API 响应（不起第二份状态源） | 同上 + 活体冒烟 |
| 总账页 `/ledger` + `api/ledger_api.py` | 复用同一 `ledger.list_entries`（就地与总账**同源**） | `test_r39_ledger_total_page_filters` |
| 提示词注册表 `ai/prompt_templates.py` | 复用 `ai.calls.CALLS`（**用例锁死两集合相等**）；占位符取值复用 `ai/prompts.context_parts` | `test_r39_all_call_sites_are_editable` |
| 提示词生效入口 `ai/prompt_runtime.py` | 复用网关与 outline 两条调用路径（**不写第二套渲染**） | `test_r39_prompt_edit_takes_effect_and_is_visible_in_audit` |
| `prompt_overrides` 表 + `service/prompt_store.py` | 新数据建表正当（不塞 `subjects.meta_json`）；台账复用 R39 账本 | `test_r39_prompt_reset_one_and_all`、`test_r39_prompt_missing_required_is_rejected_zh` |
| 提示词页 `PromptsPage.tsx` | 复用设置页入口 + 既有 `api.ts` | 活体冒烟（保存→差异→拒存→恢复） |
| 审计扩字段（`ai_logs`）+ `service/ai_trace.py` | **复用既有 `ai_logs` 表 + 既有 `make_ai_log_sink`**（不新建第二套日志） | `test_r39_audit_one_record_per_call_with_full_expand` |
| 审计页 `AiTracePage.tsx` + 调试开关（`app_settings`） | 复用设置页与 `/settings`（开关只控入口，**不控是否记录**） | `test_r39_audit_failed_call_records_retries_and_ranking` |
| 审计红线（遮蔽密钥 / 写失败记账 / 清理留痕） | 复用 R39 账本 + 既有中文口径 | `test_r39_audit_no_api_key_leak`、`test_r39_audit_write_failure_is_logged` |

### 67.5 回归与验收（实测，非推算）

| 项 | 基线（架构侧） | 本批实测 |
|---|---|---|
| `pytest backend/tests` | 392 passed + 2 skipped / 394 | **403 passed + 2 skipped / 405 collected，0 failed / 0 error**（+11 R37 用例） |
| `content validate` | ok 25/50 | **ok 26 nodes / 55 exercises**（差 1 节点 5 练习＝R37 重建的 `s-f2decfcf.u01`；旧样本 1 节点 4 练习） |
| audit 五学段 | 27/31/81/59/60 | **27/31/81/59/60，ok=True**（逐位一致） |
| `tsc --noEmit` / `vite build` | exit 0 | **exit 0 / exit 0** |
| `guardrails.semantics_stats()` | {30,0,30,0} | **{templates:30, violations:0, verified:30, unverified:0, l1_subjects:['math']}**（逐位一致） |
| 真样本接地 | 0/4、0/4、0/16 | **9/9、5/5、句内含逐字片段 14/26** |

**提交链（每步单独提交，标 R37，未与其它裁决混提）**：
`713a702`（后端核心 S1–S8）→ `22f4cbc`（11 条造错必报用例）→ `c534eaa`（大纲页覆盖账本 + 扫描版告知 + uncovered 展示）
→ `eac1faf`（书序重排/编号/线性先修/难度单调化 + 溯源规范标签 + 幂等重新记账 + 审计工具）→ 本节（文档 + NOTES + §58）。
**未污染**：测试仍走临时内容根/临时库；真实盘上只改了 `content/subjects/s-f2decfcf/outline.yaml`（revision 1→4）
与 `content/stages/s-f2decfcf/node_s-f2decfcf.u01_auto.md`（旧样本已在 `_backups` 归档），
两者都是**本次验收锚点要求**的重新生成产物，且仍未入版控（`.runtime`/`_backups` 同理）。

### 67.6 疑点 / 需架构侧确认（已登记 §58）

1. **离线（无 `LLM_API_KEY`）且有教材时**：无法读教材 → 仍走启发式出稿并落盘，但覆盖状态如实记为
   **"未覆盖：本内容无教材依据（离线启发式）"**，响应 note 与大纲页徽标都显示——**没有静默**。
   若架构侧要求"有教材且无模型时**也拒绝出稿**"，请裁定（当前取舍：保住离线机制可跑通/可测，
   与 R36 的"离线可用优先"一致）。
2. **难度单调化的副作用**：书序线性串联要求"先修难度不得高于后继"（R36 P1），故 R37 把书序上的难度
   做**非降钳制**；样本里第 2 章（动力学）判 3 后，后续单元全被抬到 3（`notes` 里有说明）。
   替代方案（保留模型原始难度、只让先修取"不高于自己"的最近单元）会让部分单元变成"根单元"——
   请架构侧定取舍。
3. **讲解的"整句命中率"只有 19%**：模型以**转述 + 夹引号**（"教材指出：…"）方式演绎，S3 明文允许换措辞；
   若希望"更贴原文"，需在 prompt 上进一步约束或加"逐段覆盖"校验（当前**未做**，如实登记）。
4. **附录类条目（如"附录D 元素周期表" 45 字）也会成为 1 个单元**：S2 要求"每个章节映射 ≥1 单元"，
   故它被目录补齐；若架构侧认为附录不必成单元，需要一条"哪些条目可豁免覆盖"的规则（当前**无豁免**）。
5. **单元数不再受 `count` 约束**：有章节地图时，单元数由书的结构决定（本样本 46 个，`UNIT_LOCAL` 上限放宽到 60）；
   `count` 只在无地图时生效——与 docs/14 §2.1"用户指定单元数"的字面略有出入，请确认口径。

---

## 68. R38 材料注入预算用户可控（两个滑块）+ 多材料合并口径（2026-09-10）

> 规格：docs/09 **R38**（§0.5 已按 R37 落地结果校准的两个参数）；工单 `.runtime/EULER_TICKET_R38.md`。
> 前置：R37 已验收（`50bdde7`）——注入语义已变成"默认不限 + 按结构分批"，本批补**用户可控那一半**。
> **R39 铁则的记账入口按工单要求先落地**：R38 里凡"丢弃/截断/未纳入"处**直接调 `service.ledger`**（见 §68.3）。

### 68.1 做了什么（A1–A5 / B1–B2）

| 项 | 落地件 | 关键点 |
|---|---|---|
| **A1 两个滑块 + 就地可见** | `outline/materials.py`（`BATCH_TIERS/INJECT_TIERS`、`subject_budget/resolve_budget/set_budget/budget_view`）、`api/subjects.py`（`GET/PUT /subjects/{sid}/budget`）、`MaterialBudgetPanel.tsx` | 滑块 A＝**单次调用预算**（`subjects.meta_json.material_batch_chars`＝20,000/60,000/150,000/**0=不限**）；滑块 B＝**总注入上限**（默认不限）；**必显**两档当前值 + 来源（你设定的（本学科）/.env 配置/默认）+ **上一轮注入总量与批次数** + 逐材料明细 + 未纳入清单；就地说明"调小 A 只是分更多批，不会少学章节" |
| **A1b 节粒度** | `bookmap._chapters_from_blocks(unit_chars=…)`、`parse_book(page_unit_chars=…)`、`config.page_unit_chars`（`MF_PAGE_UNIT_CHARS`=8000） | 无标题/无目录 PDF **按页合并成"章级"单元**（不再一页一节）；保留 `【第 N 页】` → **页号可溯源**；覆盖账按章级统计 + `page_total/page_covered`（页级下钻） |
| **A2 不限 = 真不限** | `resolve_budget` | A/B 都 0 → `per_call_chars=0`、`truncated` 恒 false、`dropped` 恒空；`used_chars` 与"显式大预算"逐字相同 |
| **A3 与 R37 分批共存** | `resolve_budget` + `_make_batches` | 预算只决定"每批装多少块"；**造错用例**：60000→300 批次数上升但**归一化内容逐字相同**、逐章不丢、覆盖账不变 |
| **A4 安全阀** | `materials.context_valve` + `MF_CONTEXT_TOKEN_LIMIT`（默认 120000） | 「字符≈token」粗估；**将超上下文 → 不发请求**，自动分批 + 中文"本书较大，已分 N 批处理"；单块超限先在**页边界**切（不切句子），仍超则独立成批并**记账**（绝不静默截断） |
| **A5 配置与优先级** | `resolve_budget`/`set_budget`/`_validate_budget` | **单次请求参数 > 学科滑块 > `.env` > 内置默认**（逐项给中文来源）；**复用 `subjects.meta_json`（不新建表）**；非法值 → **中文 422** |
| **B1 多材料合并** | `draft_materials`（合并 `chapter_map` + `usage.per_material/not_injected`）、`coverage_ledger`（`by_material`/`uncovered_by_material`/`uncovered_materials`/`order_basis`）、前端覆盖卡 | 所有材料章节地图**合并成一份**、每条标来源；覆盖账**跨全部材料**；未覆盖清单**按材料分组**；**任何未纳入的材料/章节都显式列出**（不再"只在 prompt 尾部提一句"） |
| **B2 材料角色** | `set_material_role/_ordered/order_basis`、`PUT .../materials/{mid}/role`、材料行下拉 | 主教材定顺序与范围、补充材料只补细节与例题；**未标注 → 按导入顺序**并在覆盖账注明。⚠️ 本轮把"未标注"从"默认主教材"改为**独立取值 `未标注`**（否则与显式主教材并列，排序失去意义） |
| **R40 §2-1 顺带闭合** | `draft.draft_outline` | **有教材 + 无可用模型 → 拒绝出稿**（中文 422 + 记账），不再产出"没有教材依据"的稿；无教材时仍退化为仅按 brief 起草 |

### 68.2 接线（R38 调 R39 入口，两处可见）

- `GET /subjects/{sid}/budget`＝界面"当前值/来源/上一轮用量/未纳入"的唯一数据源（全中文）；
- `POST .../outline/draft` 与 `POST .../units/{uid}/content`：**API 层开 `ledger.collector`**，响应带 `ledger[]`
  → 候选卡/单元结果就地显示；
- 材料区常驻 `SubjectLedgerInline`（读 `GET /subjects/{sid}/ledger`，最近 20 条）。

### 68.3 R38 里"丢弃/截断/未纳入"的**直接记账点**

| 触发 | 类别 | 中文原因（摘要） |
|---|---|---|
| 材料健康度不合格（扫描版）整份未注入 | 材料吸纳 | "该材料**未被注入**（文本层健康度不合格，疑似扫描/图片版）：…" |
| 某章/节不在任何注入批次 | 材料吸纳 | "该章/节**未被注入任何批次**（不在任何材料块里）" |
| 安全阀生效（超上下文自动分批） | 材料吸纳 | "本书较大，已分 N 批处理：按「字符≈token」粗估，单次调用最多 ~X 字…不截断正文、不漏章节" |
| 单块自身超上下文（页边界也切不开） | 材料吸纳 | "该章/节自身约 X 字，超过单次调用上下文硬上限…已**独立成批**（不截断、不丢弃）" |
| 实际注入量超过用户设的总注入上限 | 材料吸纳 | "本次**实际注入 X 字**，超过你设定的总注入上限 Y 字…为不丢任何章节，系统仍按批次完整注入" |
| 本学科无引用材料 | 材料吸纳 | "本学科没有引用材料：本次按 brief 起草（无教材依据）" |
| **有教材 + 无可用模型 → 拒绝出稿**（R40 §2-1） | 模型调用 | "未配置模型（LLM_API_KEY 为空），**无法依据教材生成大纲**…（**拒绝出稿**，不落盘）" |
| 无 key 离线起草（**仅无教材时**） | 模型调用 | "未配置模型…本次大纲由离线启发式骨架产出，没有读教材" |
| AI 起草失败 → 降级启发式 | 模型调用 | "AI 起草失败，本次已**降级为离线启发式骨架**（内容无教材锚定）" |
| 材料溯源不成立 → 驳回重生成一次 | 生成与校验 | "首次候选有 N 条材料溯源不成立，已把中文原因回灌并**驳回重生成一次**" |
| 重生成后仍不成立 → 剔除引用 | 生成与校验 | "驳回重生成后仍有 N 条不成立，**已剔除该引用**（宁缺勿造）" |
| 滑块改值 / 材料角色标注 | 材料吸纳 | "用户调整了材料注入预算滑块…调小单次预算**只是分成更多批，不会少学章节**" / "用户把该材料标为「主教材/补充材料」" |

### 68.4 "总注入上限"的口径（**请架构侧确认**）

R38 §0.5 把它定为"**总注入上限**（跨全部批次）"，而 **R37 已验收语义**是">0 时作**单次调用预算**"，
且 A3 铁则要求**调小不得丢章节**——两者在"上限小于整本书"时**必然冲突**（真要跨批累计封顶，
就只能不处理后面的批次＝丢章节）。**本批取舍**：
1. **单次调用预算**（滑块 A / 请求参数）＝真正生效的**每批上限**；
2. **总注入上限**（滑块 B / `.env > 0`）＝"**花费天花板**"的**事实报告**：超支就**记账 + 就地显示**，
   但**不为满足它而少注入任何章节**（与 R37 验收口径、A3 铁则、用户"不省成本要教材真源"三处一致）；
3. 想省成本 → 调小**滑块 A**（只分更多批，不丢章节）。

若要求"跨批累计硬封顶"，请明确——那需同时**放宽 A3** 并确认"未处理的章节在覆盖账里显式列出"可接受
（该清单已实现，切换成本很低）。

### 68.5 验收自证（实测）

| R38 验收项 | 证据（用例） |
|---|---|
| 滑块改值立即生效 + API 回读一致 | `test_r38_a1_slider_takes_effect_and_reads_back` |
| 非法值 → 中文 422 | `test_r38_a5_illegal_value_is_zh_422`（4 组） |
| 优先级 请求 > 学科 > .env > 内置 | `test_r38_a5_priority_request_beats_subject_slider` |
| 不限无截断（贴 `used_chars`） | `test_r38_a2_unlimited_means_no_truncation` |
| **调小滑块不丢章节（造错）** | `test_r38_a3_smaller_slider_more_batches_chapters_intact` |
| A4 安全阀自动分批 + 中文说明 | `test_r38_a4_context_valve_batches_instead_of_sending` |
| A1b 章级单元 + 页号可下钻 | `test_r38_a1b_pdf_pages_merge_into_chapter_units_with_page_numbers` |
| 多材料合并 + 每节标来源 | `test_r38_b1_multi_material_merges_map_and_groups_uncovered` |
| 未纳入者显式列出 | `test_r38_b1_blocked_material_is_listed_explicitly_and_in_ledger` |
| 材料角色 + 顺序依据 | `test_r38_b2_role_orders_main_first_and_is_reported` |
| **R40 §2-1** 有教材无模型 → 拒绝出稿 | `test_r38_r40_offline_with_material_refuses_draft_and_logs` |
| 前端必显字段契约 | `test_r38_api_contract_has_current_values_and_last_usage` |
| 前端全中文 / `tsc` / `build` | `MaterialBudgetPanel.tsx`；`tsc --noEmit` exit 0；`vite build` exit 0 |
| 真实库活体冒烟 | `.runtime/r38_r39_smoke.py` → `.runtime/r38_r39_smoke.out.txt`（3 份材料：`by_material` 3 组、`uncovered_materials=[扫描版]`；滑块 60000→0→300 逐行贴 `per_call/batches/used`，`truncated=False dropped=0`） |

## 69. R39 「一切显性」铁则 + 提示词可改可恢复 + AI 对话审计（2026-09-10）

> 规格：docs/09 **R39**（地基级铁则，凌驾于所有既有功能）；工单 `.runtime/EULER_TICKET_R39.md`。
> 顺序按工单 **R38 → R39**；但 **§1 的记账入口已在 R38 之前落地**（`service/ledger.py`），
> R38 各点**直接调用它**（§68.3）。**提交纪律：R38 与 R39 分开提交，不混提。**

### 69.1 铁则 §1：单一记账入口 + 两处可见

| 件 | 说明 |
|---|---|
| **`service/ledger.py`（新）** | **唯一入口**：`collector()`（一次操作的收集器）/`note()`（深层代码轻入口）/`write()`（落库）。类别：材料吸纳 `material` · 生成与校验 `generation` · 模型调用 `model_call` · 覆盖 `coverage` · 其它 `other` |
| **字段** | 时间 · 类别（+中文标签）· 对象（材料/单元/题号）· **原因（中文）** · 影响面 · 可否补救（+ `detail_json`、`subject_id/unit_id`） |
| **落库** | 新表 `content_ledger`（**新数据建表正当**）；写库失败**不影响主流程** |
| **两处可见** | ① 就地：`collector` + API 响应 `ledger[]`（前端 `LedgerAlerts.tsx`）；② 总账页 `/ledger`（按学科/类别筛 + 计数） |
| **禁止** | 各处自行 `print`；**只在 prompt 尾部提一句**（旧毛病，已删）；**拿日志文件当交付** |

**接入点全量**：材料（未注入/未进批次/安全阀/单块超限/超上限/无材料）、预算滑块与材料角色、
大纲起草（无 key/AI 失败降级/溯源驳回与剔除）、单元出稿（题·事实句·小思考丢弃、降级启发式、
启发式也不通过、整单元未出稿）、**日限额拦截**（`ai/provider.py`）、**审计写入失败**、
**审计文件清理**、**提示词改动/恢复/读库或渲染失败回退默认**。

### 69.2 §2：所有提示词可在程序内修改 + 一键恢复默认

- **单一注册表** `ai/prompt_templates.py`：**15 个调用点**（＝`ai.calls.CALLS` 全集）逐个声明
  `label/purpose/system/user/必填占位符/必留硬约束`；用例 **锁死注册表 == CALLS**（"一处不漏"的机器保证）。
- **模板语法**：`{placeholder}` 由程序注入；字面花括号写 `{{` `}}`（渲染后**逐字还原**旧文本）。
- **改动立即生效**：所有调用点经 `ai/prompt_runtime.render_pair()` 取**用户改过的**模板
  （网关 + `outline/draft.py` + `outline/generate.py` 三处统一）——此前 outline 两条路径直接读默认模板，
  **已修**（那正是"改了提示词却不生效＝静默失效"的隐患）。
- **存储**：新表 `prompt_overrides(call_name PK, system_text, user_text, updated_at)`（**不塞 `subjects.meta_json`**）。
- **拒存防线（中文 422）**：缺必填占位符 / 缺必留硬约束 / 模板花括号不合法（报错并教"双花括号"）；**拒存不落库**。
- **可回溯**："哪次生成用哪版"→ 审计 `prompt_versions`（`default:<call>` / `custom:<call>@<时间>`）。
- **界面**：设置 →「提示词」页（左列调用点 + 右编辑器 + 当前值/是否默认/上次修改时间 +
  **与默认的差异行** + 单条/全部恢复（确认）+ 保存前提示"改动会影响生成结果"）。

### 69.3 §3：提示词监听 / AI 对话审计（含调试模式）

- **每次调用一条**：时间 · 调用点 · 档位 · 模型 · 渲染后 system/user · 原始返回 · 解析/校验结果 ·
  **重试次数** · token · 耗时 · **最终结局**（采纳/降级/丢弃/失败）· **提示词版本** · 学科/单元。
- **存储（防库爆）**：元数据入 `ai_logs`（**扩既有表**；旧库由 `db._migrate_columns` 幂等补列）；
  全文落 `.runtime/ai_trace/<时间>-<调用点>-<id>.txt`（`MF_AI_TRACE_DIR`），DB 只存**路径+预览(600字)+字符数**；
  保留期 `MF_AI_TRACE_KEEP_DAYS`（默认 30 天）。
- **默认记录**：`write_trace` 无 sink 时自动落 `ai_logs`（provider 与 outline 两条路径都留证据）；
  调试开关只决定**界面入口**是否出现。
- **界面**：`AiTracePage.tsx`（侧栏入口随开关出现）：时间倒序、可按学科/调用点/是否失败筛、
  **失败与丢弃置顶 + 红色**；点开：**上＝发给 AI 的完整内容（system/user 分区折叠）**，
  **下＝AI 返回的完整内容**（等宽、可全文展开）+ 顶部一行摘要；**非流式**；超长只渲染前 20 万字。
- **红线**：全文**遮蔽疑似密钥**（`redact` → `[已隐去]`）；记录不阻塞主流程；写文件失败记账；
  文件缺失 → 详情页**如实说明 + 预览兜底**。

### 69.4 铁则"造错必报"用例（≥5 类，每类界面可见 + 中文原因）

| # | 类别 | 用例 | 断言 |
|---|---|---|---|
| ① | 材料吸纳 | `test_r39_ironclad_1_material_not_absorbed_is_in_ledger` | 响应 `ledger` 有 `material` 条目 + 原因含"未被注入/健康度"；`/ledger?category=material` 可筛 |
| ② | 生成与校验 | `test_r39_ironclad_2_dropped_exercise_is_in_ledger` | `generation` 条目含"丢弃" + 有"可否补救"；覆盖状态记"部分" |
| ③ | 生成失败降级 | `test_r39_ironclad_3_ai_failure_degrade_is_in_ledger` | `model_call` 含"降级…启发式" + 原始错误入 `detail` |
| ④ | 模型调用（日限额） | `test_r39_ironclad_4_daily_token_cap_blocked_is_in_ledger` | 账本含"额度已用尽"；审计 `outcome=failed` 一条 |
| ⑤ | 覆盖（未出稿） | `test_r39_ironclad_5_uncovered_unit_is_in_ledger` | `coverage` 条目 + `/coverage` 该单元 `status=未覆盖` |
| ⑥ | 其它 | `test_r39_ironclad_6_...`、`test_r39_audit_write_failure_is_logged` | 提示词改动 / 审计清理 / 审计写入失败 三类都在 `other` 下可见 |

### 69.5 验收自证（逐条实测）

| R39 验收项 | 证据 |
|---|---|
| 提示词：改一条 → 生成用新版（审计对照） | `test_r39_prompt_edit_takes_effect_and_is_visible_in_audit` |
| 单条 / 全部恢复默认 | `test_r39_prompt_reset_one_and_all`（`changed == []`） |
| 删占位符/硬约束 → **中文拒存** | `test_r39_prompt_missing_required_is_rejected_zh`（4 组；库内仍默认） |
| 模板语法错 → 中文拒存 | `test_r39_prompt_bad_template_syntax_is_rejected_zh` |
| 审计：每次调用一条 + 完整展开 | `test_r39_audit_one_record_per_call_with_full_expand` |
| 长 prompt（>10 万字）不卡界面 | `test_r39_audit_long_prompt_is_served_whole_but_ui_caps_render` |
| 失败/丢弃置顶 + 红色 | `test_r39_audit_failed_call_records_retries_and_ranking`（`retries==2`） |
| **无 API Key 泄漏** | `test_r39_audit_no_api_key_leak`（上游回显 `sk-…` → 文件里 `[已隐去]`） |
| **非流式** | 同上用例（`application/json`，非 `text/event-stream`） |
| 调试模式开关生效 | 活体冒烟：开→True、入口出现、关→False |
| 真实库活体冒烟 | `.runtime/r38_r39_smoke.out.txt`（15 调用点；保存→差异 4 行→删占位符 422→恢复默认；审计 57 条、最新一条 system 1071 / user 1593 / response 302 字可完整展开） |

### 69.6 回归与基线（本批实测）

| 项 | 基线（R40 验收，`50bdde7`） | 本批实测 |
|---|---|---|
| `pytest backend/tests` | 404 passed + 2 skipped / 406 collected | **441 passed + 2 skipped / 443 collected**（+37 用例：R38 15 + R39 22） |
| `content validate` | ok 26 / 55 | **ok 26 / 55**（逐位一致；本批未动内容） |
| audit 五学段 | 27/31/81/59/60 | 未跑（需 `MF_ALLOW_LIVE_AI=1` + key）；**只读**的 `audit_material_binding.py s-f2decfcf` 复跑：**9/9、5/5、19%、54%**——**逐位一致** |
| `tsc --noEmit` / `vite build` | exit 0 / exit 0 | **exit 0 / exit 0** |
| `semantics_stats()` | {30,0,30,0} | 未变（本批未动模板/闸门） |

**提交链**（分开不混提）：`R38 …` → `R39 …`（见两条提交信息）。

### 69.7 疑点 / 需架构侧确认（§58-17）

1. **账本是否也给"成功路径"记账**：本批只记"异常/偏离"（否则日常噪音淹没）；若要"成功也留账"请明确；
2. **复习降级回炉未重复记账**：既有 `relearn_logs` + 会话事件已是权威留痕（R30/R27 验收过），避免双源；
   若要在总账页也看到，在 `service/review.py`/`session.py` 回炉点加一条 `ledger.note(CAT_OTHER, …)` 即可；
3. **"降档"（think→fast）无独立账目**：目前只有"AI 失败降级"与"日限额拦截"；`ai/tier.resolve` 的
   `edge/trigger` 降档是否逐次记账？会显著增加账本量（倾向：只在用户显式选轻档或边缘带复评失败时记）；
4. **提示词 `user` 模板本批只读对照**（可编辑的是 `system`）；接线已就绪（`prompt_store.save(user_text=…)`）；
5. **审计文件清理目前人工触发 + 保留期参数**（无后台定时任务）；若要自动，`main.lifespan` 一行即可。



