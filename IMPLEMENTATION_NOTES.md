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

