# 13 · Agent 交接与续接协议（Handover & Continuity）

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

## 3. 当前活动工单（新实例的第一个任务）
1. **若上一 Euler 的"blueprint 修订批 A/B/C"尚未完成或未经架构侧核实**：先按
   `content/roadmap/REVIEW-blueprint.md` + 用户最新批指令完成（改 primary/middle.yaml 的
   A/B 项 + roadmap.audit 锚点存在性检查 C 项），跑审计更新 ROADMAP_AUDIT.md，全量回归。
2. **蓝图总纲（docs/12-roadmap-master.md）分阶段 P1→P4**：
   - P1 high.yaml 全段草案（audit 绿 + 更新 ROADMAP_AUDIT + 3 条锚点级示例草稿）；
   - P2 college.yaml 全段草案（含与 high 衔接假设）；
   - P3 ai.yaml 全段草案（含依赖 college 衔接说明，默认 thinking:true）；
   - P4 high+ 自动入库护栏升级（北极星配套，与 P1 一并评审）；
   - 每阶段独立汇报；只写蓝图不生成内容；验收见 docs/12 §4。
3. 疑点：不得改动 docs/12 骨架本身；范围外问题记 IMPLEMENTATION_NOTES 待裁决。

## 4. 环境速查（新人必读）
- 服务：`powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`（前端 5173 / 后端 8000）；
  停止 `scripts\stop.ps1`；日志 `.runtime/backend.err.log`。
- 测试内容根已隔离（conftest 会话级临时副本）；真模型冒烟需 `MF_ALLOW_LIVE_AI=1`。
- `.env`（仓库根，git 忽略）：LLM_API_KEY 等；`MF_AUTO_EXTEND=1` 控制全自动续关；
  `LLM_MAX_TOKENS_PER_DAY=0` 不限额。
- 当前基线（最近核实）：173 passed + 1 skipped；content validate 13 节点/30 练习；
  primary/middle 蓝图 draft 待精核；high/college/ai 蓝图未建（docs/12 目标）。
