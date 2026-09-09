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
- 红线：判题只走 sympy；LLM 输出必过 schema 校验；domain 零 LLM 依赖；`content/stages/`
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
> 历史批次（R1–R23、docs/14 Phase A A1–A4、Phase B B1–B5、**Phase C C1–C5**）已完成并
> git 提交（基线 **pytest 291 passed + 2 skipped（离线默认）**、audit 5 学段全绿
> （27/31/81/59/60）、content 26/49、subject=math 总 Outline 258 单元已建、通用学科闭环 E2E 已锁）；
> 详见 IMPLEMENTATION_NOTES §9–§44、docs/09 R1–R23。

1. **docs/14 Phase A 已验收（R19）、Phase B 已验收（R23）、Phase C C1–C5 完成**（NOTES §40–§44）：
   C1 外部检索后端 provider 抽象（默认未启用 + 可配自托管 SearXNG + LLM 候选 + select 抓正文）、
   C2 PDF/文档解析（pypdf 分页/分节 kind:pdf）、C3 学科停用过滤 UI + 学科管理收敛、C4 backlog
   （heuristic 单选乱序+answer_index 同步 / PUT 405 复查留档）、C5 回归与真模型验收（行星科学
   10 单元 AI 内容 + 材料可追溯来源实测通过）。**C6 汇报收尾（本批）**；剩架构侧裁决与真人
   浏览器验收（验收清单见 NOTES §44 与 docs/08 M5 剩余真人项）。
2. 后续派发视用户验收与需求：docs/14 §7 待细化项（大纲 schema 升级、标签归一策略细化、题目
   交互块落地顺序/信息架构、AI 起草跨单元题面去重等）与数学内容持续治理（roadmap 到段精核/
   内容懒生成）。
3. 疑点与口径冲突：记 IMPLEMENTATION_NOTES"待架构裁决"；涉及 docs/02/03/05/06/07/14 的语义
   变更在实现时顺带同步。

## 4. 环境速查（新人必读）
- 服务：`powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`（前端 5173 / 后端 8000）；
  停止 `scripts\stop.ps1`；日志 `.runtime/backend.err.log`。
- 测试内容根已隔离（conftest 会话级临时副本）；真模型冒烟需 `MF_ALLOW_LIVE_AI=1`。
- `.env`（仓库根，git 忽略）：LLM_API_KEY 等；`MF_AUTO_EXTEND=1` 控制全自动续关；
  `LLM_MAX_TOKENS_PER_DAY=0` 不限额。
- 当前基线（最近核实，2026-09-09 Phase C 收尾）：pytest **291 passed + 2 skipped**
  （293 collected；2 skipped = 真模型冒烟 test_live_ai + Phase C 验收 test_phase_c_live，
  均需 `MF_ALLOW_LIVE_AI=1` 且配 LLM_API_KEY 才执行）；audit 5 学段全绿（27/31/81/59/60）；
  content validate **26/49**（真实库，随运行期 auto 增补；测试 hermetic 基线 13 人工节点不变）；
  git 仓库不含 data/、_drafts、resume/。品牌：YanHui（颜回）全科教练。当前工单见 §3
  （Phase A/B/C1–C5 完成 → 架构裁决/真人验收待收尾）。
