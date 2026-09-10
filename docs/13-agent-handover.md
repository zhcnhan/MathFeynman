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
> **R33 已执行完毕（Euler，2026-09-10 · 待架构侧验收）**：
> ① 任务 A 文档尾巴——`docs/02` §3 目录树首行改 `YanHui/` 并按实测补齐实有目录；旧名 `MathFeynman`
> 全仓复核（40 处命中）并逐处分类"改 / 有意保留 / 不能改"；
> ② 任务 B 库名归一——库文件改名 `mathfeynman.db` → `yanhui.db`（备份 + SHA256 核对 + 六项计数
> 26/3/31/2/113/0 逐位一致），`.env` 同步；**另查出第二层根因：进程环境变量优先于 `.env`**
> （`load_dotenv()` 默认不 override，见 NOTES §54）；
> ③ 任务 C 真人验收清单（NOTES §55，用户动作，待用户走查）。
> 规格/工单：`.runtime/EULER_TICKET_INIT_R33.md`；实现记录：NOTES **§52–§55**；
> 提交：`51c6a62`（NOTES §52 + docs/02）、`b90c160`（NOTES §53/§54 + docs/15）、收尾提交（NOTES §55 + 本文件）。
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

## 4. 环境速查（新人必读）
- 服务：`powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`（前端 5173 / 后端 8000）；
  停止 `scripts\stop.ps1`；日志 `.runtime/backend.err.log`。
- 测试内容根已隔离（conftest 会话级临时副本）；真模型冒烟需 `MF_ALLOW_LIVE_AI=1`。
- `.env`（仓库根，git 忽略）：LLM_API_KEY 等；`MF_AUTO_EXTEND=1` 控制全自动续关；
  `LLM_MAX_TOKENS_PER_DAY=0` 不限额。
- 当前基线（**架构侧于 R32 独立复跑确认，2026-09-10**）：pytest **325 passed + 2 skipped**
  （327 collected，exit 0，130.48s；2 skipped = 真模型冒烟 test_live_ai + Phase C 验收 test_phase_c_live，
  均需 `MF_ALLOW_LIVE_AI=1` 且配 LLM_API_KEY 才执行）；audit 5 学段全绿（27/31/81/59/60）；
  content validate **26/54**（真实库，随运行期 auto 增补；测试 hermetic 基线 13 人工节点不变）；
  前端 `npx tsc --noEmit` 通过（`npm run build` 在受限沙箱内会因 esbuild 子进程 EPERM 失败，
  属环境限制而非代码问题，需在普通终端复核）；git 仓库不含 data/、_drafts、resume/。
  R30 前基线为 306+2（R30 批 +19 = F6 7 / F5 2 / flow 自愈 10）。
- 工作目录已改名：`D:\DeepseekHarness\YanHui`（旧名 MathFeynman；执行记录见 docs/09 R32 §3）。
- **数据库（R33 任务 B 已归一，2026-09-10）**：真实库＝`backend/data/yanhui.db`（六项计数
  user_nodes 26 / sessions 3 / attempts 31 / subjects 2 / concepts 113 / reviews 0）。改名前的旧库备份在
  `D:\DeepseekHarness\_backups\yanhui-db-20260910-160212\`（含 SHA256 核对记录）。
  ⚠️ **启动后端前先确认环境里没有旧值**：`load_dotenv()` 默认**不覆盖**已存在的环境变量，
  若终端继承了 `MF_DB_PATH=backend/data/mathfeynman.db`（旧 DSH 进程的残留），应用会**静默新建空库**——
  排查与处置见 NOTES §54 B4/B7。**建议重启 DSH/换新终端后再 `scripts\dev.ps1`。**
- `.runtime/pids.txt` 记的是 `dev.ps1` 启动的**父进程** PID（uvicorn 父 / cmd.exe 包装），真正 listen 的是
  **子进程**（实测：记录 9084/2944，监听者 19852/6816）——属正常现象，不是记录失效。`stop.ps1` 杀父进程后
  子进程随之退出（R33 实测通过）；但停服仍请**以端口复核**（8000/5173 无监听才算停干净）。
- `.venv` 改名后重建时曾漏装 dev 依赖（pytest 缺失）→ 已补装 `pytest 9.1.1`/`pytest-cov 7.1.0`
  （`pip install -e "backend[dev]"`）。**改名/重建 venv 后必跑这一步，否则基线不可复跑。**
- 品牌：YanHui（颜回）全科教练。当前工单见 §3（R32 已验收，下一批 R33）。

