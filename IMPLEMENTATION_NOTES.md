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
- **DB 路径**：默认 `backend/data/mathfeynman.db`（可 `MF_DB_PATH` 覆盖），SQLite WAL。
- **判题解析语义**（docs/04 §3 落地细节）：用户解集按"集合语义"比对（重复写同根不算错，
  缺根/多根算错）；数值题作答含符号视为 notation_error 而非判错；tolerance 缺省 1e-9。
- **M1 判题用例统计**：参数化条目 numeric 14 + equivalence 13 + equation 22 + boolean 12 = **61 ≥ 30**。

---

## 1. 待架构裁决疑点

1. **M3 真模型冒烟未执行**：本环境无 `LLM_API_KEY`。ai/provider（OpenAI 兼容 chat + JSON
   提取 + pydantic 校验 + ≤2 重试 + ai_logs）、OpenAICompatibleGateway（调用点 1/2/4/6/7/8）
   及"坏 JSON/断网降级不脏状态"均已单测覆盖（含 401 即停）；docs/08 M3 的"真实调用 DeepSeek"
   验收需用户提供 key（写入 .env 后运行 `pytest tests/test_live_ai.py`，测试已就绪）。
   按实现规则不阻塞推进，先记档。

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
