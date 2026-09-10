# 13 · Agent 交接与续接协议（Handover & Continuity）
> 适用范围：范围：流程永续 —— 新 Euler 交接协议（当前活动工单见 §3，docs/14 Phase A）

> 目的：当实现工程师（Euler）会话上下文耗尽/重启新实例时，新实例可在**不依赖旧对话**的
> 前提下无痛续接。本仓库的全部"记忆"已外置在以下文件中；新实例按本文档的"开机清单"
> 顺序自取上下文，然后从"当前活动工单"继续。身份约定：任何新实例都被视为 **Euler 的延续**，
> 代号仍为 Euler；首次续接请在 IMPLEMENTATION_NOTES.md 追加一节记录"会话续接"时间与基线。

## 1. 开机清单（新实例按顺序执行，全部完成后才动代码）

1. 读 `README.md`（含不可变决策 9 条 + 文档导航）。
2. 读 `docs/12-roadmap-master.md`（北极星/蓝图总纲，当前最重要目标）与
   `docs/10-progression.md`、`docs/11-workorder.md`（成长型闭环与工单约定）。
3. 读 `docs/09-architect-rulings.md`（架构裁决史，重点最新几条 R13/R12/R11 及补记）。
4. 读 `IMPLEMENTATION_NOTES.md` **全文**（实现运行日志，含里程碑 M0–M5 与阶段 1–3 进度、
   "待架构裁决"区、§9 最近批）。
5. 读 `USER_FEEDBACK.md`（用户反馈与分诊记录）、`content/roadmap/REVIEW-blueprint.md`
   （蓝图精核建议）、`ROADMAP_AUDIT.md`（蓝图自查现状）。
6. 其余 docs/01–08 按需精读（判题/状态机/AI 集成规范等重点在需要改对应模块时读）。
7. **基线验证**（未验证前不修改任何东西）：
   - `.\.venv\Scripts\python -m pytest backend/tests` → 期望 **173 passed + 1 skipped**（若 ABC 修订批
     已落地则更高；以 IMPLEMENTATION_NOTES 记录为准）；
   - `.\.venv\Scripts\content validate`（或 python -m app.content validate）→ 期望 ok、nodes 数 13+；
   - `git status` 应干净（或仅有未提交的合法改动）。
8. 在 IMPLEMENTATION_NOTES.md 追加：`## N. 会话续接（<日期>）—— 基线复核通过：pytest=<实际>，
   content=<实际>`，并列出本次续接前最后已知状态。

## 2. 行为公约（沿用至今，必须遵守）
- docs 是唯一事实源；与代码冲突以 docs 为准并记录；改动架构决策=不可变清单，需先改
  README/docs 评审（架构侧/用户批准）。
- 红线：判题只走学科 L1 判题器（math=sympy）；LLM 输出必过 schema 校验；domain 零 LLM 依赖；`content/stages/`
  既有节点与锚点 id **不得改动**；每阶段跑全量回归 + content validate；测试/生成不留
  残留文件（stages/_drafts 事后必净）。
- 进度与疑点：全部写入 IMPLEMENTATION_NOTES.md（进度节 + "待架构裁决"节），不靠对话记忆；
  拿不准不擅改、不等待——按文档落地并记疑点，完成汇报时列出。
- 汇报格式：改动清单 / 测试结果 / 疑点 / 可验收点。用户会把汇报转架构侧过目。
- git：**每完成一个可验证里程碑提交一次快照**（`git add -A; git commit -m "<phase>: <摘要>"`），
  提交信息标注阶段，便于回滚与 diff。
- **错误中文化（绝对要求，2026-09-09 起）**：所有对外（API/前端可见）的错误**必须带中文说明**
  ——HTTPException/校验错误/未捕获 500 一律给出人话（含原因与可操作提示），禁止把原始英文
  traceback/pydantic 原文直接暴露给前端；前端网络层对无后端文案的状态码也给中文兜底文案；
  新增/改动端点都要满足；sample 级测试锁定。

## 3. 当前活动工单（新实例的第一个任务）
> **R30 已验收通过（R31，2026-09-10）**：F6 边缘带复评 + F5/F4/R29 引申/F2 全部通过、已放行。
> **立心批（身份级去数学中心化 + 文档清理 + 工作目录改名）已由 R32 验收通过**（2026-09-10）：
> 主体提交 `92b6ff9`；代码内文案/注释清理为**未提交工作树**（14 文件，逐条复核零逻辑变更）。
> **下一批 = R33（小批）**：文档/配置一致性收尾 + 用户真人验收清单；规格见 docs/09 R32 §4
> 与 `.runtime/EULER_TICKET_R32.md`。
>
> **R33 已由 R33 裁决验收通过、放行**（架构侧独立复跑：pytest 325+2 / content 26/54 /
> audit 27/31/81/59/60 / tsc exit 0；真实库 `yanhui.db` integrity ok 且六项计数 26/3/31/2/113/0
> 与迁移前逐位一致）：① 任务 A 文档尾巴（`docs/02` §3 首行改 `YanHui/` 并按实测补齐实有目录；
> 旧名 `MathFeynman` 全仓 40 处命中逐处分类）；② 任务 B 库名归一（备份 + SHA256 + 计数逐位一致，
> `.env` 同步；**另查出第二层根因：进程环境变量优先于 `.env`**，见 NOTES §54）；
> ③ 任务 C 真人验收清单（NOTES §55，**用户动作，待走查**）。
> **下一批 = R34（小批收尾）**：`scripts/dev.ps1` 显式设定 `MF_DB_PATH` + 读回校验（根因第三层：
> 启动脚本不设值 → 继承终端残留环境变量 → 静默建空库）＋ `.gitignore` GBK 编码修复；
> 规格见 docs/09 **R33 §2/§3** 与 `.runtime/EULER_TICKET_R34.md`。
> 规格/工单：`.runtime/EULER_TICKET_INIT_R33.md`；实现记录：NOTES **§52–§55**；
> 提交：`51c6a62`（NOTES §52 + docs/02）、`b90c160`（NOTES §53/§54 + docs/15）、收尾提交（NOTES §55 + 本文件）。
>
> **R34-fin 收尾批已完成（Euler，2026-09-10 · 待架构侧验收）**：数据清空后的合规确认——
> ① 回归全绿：pytest **325+2 / 327**、content validate **ok 25/48**（清空所致，如实记录）、
> audit **27/31/81/59/60**（未受影响）、`tsc` exit 0；
> ② 清空后体验：math 停用态下 `/api/dashboard`、`/api/graph`（0 节点 0 边）、`/api/campaign`（关卡 0 节点）
> 均**空但 200**；学科列表落到「已移除」分组（**未真点重新启用**，保住现场）；
> 新建学科 → 起草大纲 → 采纳 → 懒生成内容 → 硬删，全链路 **0 个 500、错误全中文**；
> ③ **发现 1 处显示层缺陷**：仪表盘"数学已停用"横幅**不显示**（NOTES §58-6，一行可修，待裁决）；
> ④ 口径登记：**auto 内容随生成即入版控**（NOTES §57.3，未写自动提交逻辑）。
> 记录：NOTES **§57**（本批）+ **§58「待架构裁决 / 未决」= 挂账总表，续接先读**。
>
> **R36 任务 L 已完成（Euler，2026-09-10）**：
> ① **L1 修仪表盘停用横幅**（提交 `1c121f3`）——采纳架构侧倾向的**方案②**：`GET /api/dashboard`
> 直出 `preset_subject{id,label,enabled}`，前端不再从 `/subjects`（默认隐藏已移除者）反推；
> 新回归用例双向锁定，pytest 由 325+2 → **326+2**（328 collected）。活体验证：math 停用时
> `presetOff=true` → **中文横幅会显示**；vite dev 已在服务新源码。
> ② **L2 清现场**——先备份（`_backups\yanhui-r36-before-clean-20260910-172524\`，SHA256 自证）后清理：
> `nodes 28→25`（3 行走查残影永久清除）、`ai_logs 42→38`（仅清走查那 4 次调用）、`user_nodes→0`；
> **登记**：`user_nodes` 会随后端启动被 `sync_content` 重建（引擎语义，非残留）。
> 详见 NOTES **§59**。
>
> **R36 任务 D＋P 已完成（Euler，2026-09-10 · 待架构侧验收）**：
> ① **D1–D5 大纲起草读材料**：`/outline/draft`（与 custom 的 regenerate）注入该学科引用材料的**分节摘要**
> （唯一入口 `outline.materials.draft_materials`；`MF_OUTLINE_MATERIAL_MAX_CHARS` 预算 + 截断/丢弃留痕；
> **材料可选，无材料退化为现状不报错**）；单元带 `materials:[{title,section}]` 溯源（真实章节名或逐字引文，
> 复用 `content.citations` 同一把尺子），不成立 → **驳回重生成一次** → 仍不成立剔除并记问题；
> 采纳时**服务端**反查写入 `source_materials`（不信客户端自报）；大纲页显示「本大纲依据的材料」。
> ② **P1–P5 由易到难·零基础**：`validate_outline_doc` 新增"先修 difficulty 不得高于后继"（中文 422；
> **`source=="roadmap"` 豁免**——math 预设实测 15 处倒置，属数据治理项，见 NOTES §60.5）；
> 首单元零基础 / 分组表达章阶段 / 难度只能靠已教事实累积 → 写进 prompt（**P4 机器校验待 R35**，明记）。
> ③ 提交：`adc0b89`（引文尺子收敛）→ `ae2c8f7`（config.py 纯 EOL）→ `6b589b7`（D+P）→
> `3bf1ca8`（AI 输出 schema 声明 materials——**活体冒烟实测踩到的接线缺口**）。
> 回归 **341 passed + 2 skipped / 343 collected**（+15 用例）；validate 25/48、audit 27/31/81/59/60、tsc 0。
> 记录：NOTES **§60**（含真模型活体冒烟两次对照与 math 倒置清单）。
> 提交链：443efb0（后端账本/双提交）→ bfd5bea（UI）→ a3dbddc（协议）→ 65282e9/8927a20（R28 裁决）
> → fe9902d（R29 热修 + 回归用例）→ b1c1b05（R30 规格）
> → **4f7990b（F6）→ 23fc603（F5）→ 49e5149（F4）→ f66af5f（R29 引申 flow 自愈）→ f8c856d（F2 行尾）**。
> 基线 pytest **325 passed + 2 skipped**（327 collected，离线；R30 前为 306+2）、
> tsc/build 通过、content 26/54、audit 五学段全绿。
> 详见 docs/09 R27（规格）/ R28（验收）/ R29（热修）/ R30（本批规格）、NOTES §46–§50。

1. **R30 F6（已实现）· 费曼终验边缘带复评**：完整稿评分落边缘带
   `[threshold−0.05, threshold+0.08]` 且本轮非 think、且本轮未复评过 → 用 **think 档复评一次**，
   取较高分入场；两次卡都记 `attempts.meta.recheck` + 事件 `feynman_edge_recheck`；
   复评失败保留首次；**每次提交最多复评一次**。常量在 `ai/tier.py`。
   测试 `backend/tests/test_r30_edge_recheck.py`（7 用例，离线桩）。
2. **R30 其余项（已实现）**：
   - F2 行尾治理：`session.py` 归一到 LF（纯 EOL 提交 `f8c856d`）+ `.gitattributes`
     （`*.py`/`*.ts`/`*.tsx text eol=lf`）；
   - F4 文案：补答未补上 → 前后端统一"再交一次完整讲解后，会针对该缺口再问"；
   - F5 加固：evidence 归一化后 <6 字视为无效（降级 + 标记），用例 2 条；
   - R29 引申：flow schema 演进收敛为单一自愈入口 `_ensure_flow_shape`（缺键/错类型/整块缺失），
     用例 `backend/tests/test_r30_flow_shape.py`（10 条）。
3. **F3（已裁定，无需改码）**：通过判定维持"账本累计分（维度历轮 max）≥ 阈值"。
4. **F1 纪律**：真模型回归留档文件名唯一、不得覆盖；汇报数字取自留档。
5. 真人浏览器验收（用户动作）：重启后端后打开遗留会话 `s-f2decfcf.u01:a7689b7ebf`
   （R29 修复后不再 500），走"首讲 → 补答 → 整合重讲"，确认分数可见上升、得分条/缺口提示/额度徽标正确。
6. 疑点与口径冲突：记 IMPLEMENTATION_NOTES"待架构裁决"（本批 5 条见 §50）；涉及
   docs/02/03/05/06/07/14 的语义变更在实现时顺带同步。

> **R35（可答性 S1–S8）已全部落地，R35b 收尾批完成（Euler，2026-09-10 · 待架构侧验收）**：
> S1–S8 的实现分四次提交落地——`§61`（S1/S2/S5/S6/S7 + A3 例题）→ `§62`（S6/S7 收口）→
> `§63/§64/§65`（语义自检闸门 → 求值路径单一化 → 题面泄漏清零 + 30 模板补 `expect`/模板级 `basis` + P4 机器校验）
> → **`§66`（模板 basis 引文语义精细化 + S3 挑战题双池 + S4 追问 `reteach` + docs 06/07/04/05 同步 + 融合对照表）**。
> **基线（本批实测）**：pytest **394 collected / 392 passed + 2 skipped / 0 failed**、
> `content validate` **ok 25/50**、audit 五学段 **27/31/81/59/60（ok=True）**、`tsc --noEmit` exit 0
> （另 `vite build` exit 0）、`semantics_stats = {templates:30, violations:0, verified:30, unverified:0}`。
> **下一步（R35 最终验收）**：**用户新建的 PDF 学科就绪后跑 A2 全链路审计（"不可答 = 0"）**
> ——那是 R35 的最终验收，也是**非数学路径的第一次真考试**（架构侧 §17 收口，NOTES §58-1）。
> 开工入口照旧：**本节 → `IMPLEMENTATION_NOTES §58`（挂账总表）→ `docs/09` R35/R35b §18 与 §66 相关裁决**。

## 4. 环境速查（新人必读）
- 服务：`powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`（前端 5173 / 后端 8000）；
  停止 `scripts\stop.ps1`；日志 `.runtime/backend.err.log`。
- ⚠️ **库路径务必走 `dev.ps1`**：手工 `uvicorn` 时须自行确保 `MF_DB_PATH` 未被**终端残留环境变量**
  劫持（`config.py` 用 `load_dotenv()`，python-dotenv 默认**不覆盖**已存在的环境变量）；
  被劫持会指回 `mathfeynman.db` 并**静默新建空库**（R33 实测踩过；R34 已让 `dev.ps1` 显式定值 +
  读回校验兜底）。根因链见 docs/09 R33 §2。
- 测试内容根已隔离（conftest 会话级临时副本）；真模型冒烟需 `MF_ALLOW_LIVE_AI=1`。
- **可答性/模板体检审计（工具，不是测试）的手动门槛（docs/09 R35 §11 裁定，长期有效）**：
  `backend/tests/audit_answerability.py`（零基础学生模型逐题判 `answerable`；**选择题必须把 `options`
  一并喂给"学生"**）与 `backend/tests/audit_template_semantics.py`（模板语义体检）——
  ① **每次改动生成器后**必须手动跑一轮全库审计；② **发版前**跑一轮；③ **日常 CI 只跑离线结构性校验**
  （答案可答性单测 + `content validate`）。两者文件名**不带 `test_` 前缀**（pytest 不收集、不随 CI），
  需网络与 LLM_API_KEY。跑法：`$env:MF_ALLOW_LIVE_AI=1; .\.venv\Scripts\python backend/tests/audit_answerability.py`。
- `.env`（仓库根，git 忽略）：LLM_API_KEY 等；`MF_AUTO_EXTEND=1` 控制全自动续关；
  `LLM_MAX_TOKENS_PER_DAY=0` 不限额。
- 当前基线（**Euler 于 R35b §66 收尾批复跑确认，2026-09-10**）：pytest **392 passed + 2 skipped**
  （394 collected，exit 0；2 skipped = 真模型冒烟 test_live_ai + Phase C 验收 test_phase_c_live，
  均需 `MF_ALLOW_LIVE_AI=1` 且配 LLM_API_KEY 才执行）；audit 5 学段全绿（27/31/81/59/60）；
  content validate **ok 25 节点 / 50 练习**；前端 `npx tsc --noEmit` + `vite build` 均通过；
  git 仓库不含 data/、_drafts。
  > 注：**pytest 数字不随真实库清空变化**——`backend/tests/conftest.py` 在导入 app 之前就隔离了
  > `MF_DB_PATH`（临时库）与 `MF_CONTENT_ROOT`（会话级内容副本），真实库与测试完全隔离。
  > 历史基线：R30 前 306+2 → R30 325+2 → R33 325+2 → R34-fin 325+2 → R35a 349+2 → R35b-P0 358+2
  > → §13 373+2 → §14 376+2 → **§66 392+2**。
- 工作目录已改名：`D:\DeepseekHarness\YanHui`（旧名 MathFeynman；执行记录见 docs/09 R32 §3）。
- **数据库（R33 任务 B 已归一为 `backend/data/yanhui.db`，2026-09-10）**：
  - **清空后现状**（docs/15 §3.1 + NOTES §57.2e/§59.2）：`subjects 1`（math，**enabled=0 停用**）、
    `nodes 25`（走查残影 3 行已于 R36 L2 清除）、`edges 28`、`concepts 83`、
    `user_nodes 0`（**瞬态**：后端启动时 `sync_content→recompute_states` 会为全部 25 个内容节点
    重建默认 `locked` 行，属引擎既有语义，非走查残留——见 NOTES §59.2）、
    `sessions/attempts/reviews/feedback/relearn_logs/user_concepts` **全 0**、`ai_logs 38`；
    清空前整份归档在 `_backups\yanhui-before-wipe-20260910-170347\`；R36 L2 清理前的库备份在
    `_backups\yanhui-r36-before-clean-20260910-172524\`（含 SHA256）；R33 迁移前旧库备份在
    `_backups\yanhui-db-20260910-160212\`。
  - ⚠️ **启动后端前先确认环境里没有旧值**：`load_dotenv()` 默认**不覆盖**已存在的环境变量，
    若终端继承了 `MF_DB_PATH=backend/data/mathfeynman.db`（旧 DSH 进程的残留），应用会**静默新建空库**——
    排查与处置见 NOTES §54 B4/B7。**`dev.ps1` 已显式定值 + 读回校验（`17646f8`），仍建议换新终端启动。**
- `.runtime/pids.txt` 记的是 `dev.ps1` 启动的**父进程** PID（uvicorn 父 / cmd.exe 包装），真正 listen 的是
  **子进程**——属正常现象，不是记录失效。`stop.ps1` 已升级为**按进程树停止**（`e55c8b3`）+
  按命令行兜底清理；停服后仍请**以端口复核**（8000/5173 无监听才算停干净；刚停时的"仍在响应"可能是
  TIME_WAIT 假象，等几秒再判定）。
- `.venv` 改名后重建时曾漏装 dev 依赖（pytest 缺失）→ 已补装 `pytest 9.1.1`/`pytest-cov 7.1.0`
  （`pip install -e "backend[dev]"`）。**改名/重建 venv 后必跑这一步，否则基线不可复跑。**
- 品牌：YanHui（颜回）全科教练。当前工单见 §3（R32 已验收，下一批 R33）。

