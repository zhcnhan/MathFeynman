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
> 历史批次（R1–R24、docs/14 Phase A A1–A4、Phase B B1–B5、Phase C C1–C5、**R27 费曼追问语义 v3**）
> 已完成并 git 提交（基线 pytest 305 passed + 2 skipped（离线默认）、audit 5 学段全绿、
> content 26/54）；详见 IMPLEMENTATION_NOTES §9–§47、docs/09 R1–R27。

1. **R27 费曼追问语义 v3（混合制）—— ✅ 已实现并验收**（docs/09 R27 全规格 + docs/05 §5 v3 +
   本 NOTES §46 后端实现 / §47 真模型回归）：
   ① 两类提交分离（`feynman_submit`=完整稿 / `feynman_answer`=补答）；R25 合并稿拼接已删除；
   ② 评分对象 = 本轮文本 + `previously_acknowledged`；evidence 服务端**归一化包含校验**（违规降级标记）；
   ③ `service/feynman_ledger.py` 缺口账本（维度历轮最高分 + 缺口清单）+ `feynman_gap_check`
      补答评估（调用点 13，light，只更新缺口所属维度）；追问定向 `unmet_gaps`（一次一个）；
   ④ 预算：整体稿 ≤3、补答 ≤2；额度尽/3 次未过 → relearn（`_feynman_reset` 含账本清零）；
      R10/R11/R17 分支语义经回归锁定（409/回炉/清零）；
   ⑤ UI：费曼视图双提交入口 + 实时得分条（账本维度分 + 缺口提示 + 综合分/门槛进度 + 额度徽标）；
   ⑥ 测试：`backend/tests/test_feynman_v3.py` ×11 函数 / 14 用例（三条集成路径 + evidence 纪律 +
      账本不降级 + 补答不越权 + 已认可上下文）；全量 pytest 305+2 离线；前端 tsc/build 通过；
      真模型走查（行星科学 u01）实测：首讲 0.0 → 答追问 0.4 → 整合终验 0.863 pass。
2. **待架构裁决（本轮新增，NOTES §46 疑点）**：evidence 校验取"归一化包含"而非严格逐字（LLM 排版
   差异）；降级系数 0.5 不归零；预算按次数计；离线启发式分档仅影响无 key 演示；`_enter_feynman`
   重复定义缺陷已修（原 R17 防御实际未生效）。
3. 后续派发视用户验收与需求：docs/14 §7 待细化项、数学内容持续治理（roadmap 到段精核）。
4. 疑点与口径冲突：记 IMPLEMENTATION_NOTES"待架构裁决"；涉及 docs/02/03/05/06/07/14 的语义
   变更在实现时顺带同步。

## 4. 环境速查（新人必读）
- 服务：`powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`（前端 5173 / 后端 8000）；
  停止 `scripts\stop.ps1`；日志 `.runtime/backend.err.log`。
- 测试内容根已隔离（conftest 会话级临时副本）；真模型冒烟需 `MF_ALLOW_LIVE_AI=1`。
- `.env`（仓库根，git 忽略）：LLM_API_KEY 等；`MF_AUTO_EXTEND=1` 控制全自动续关；
  `LLM_MAX_TOKENS_PER_DAY=0` 不限额。
- 当前基线（最近核实，2026-09-09 R27 收尾）：pytest **305 passed + 2 skipped**
  （307 collected；2 skipped = 真模型冒烟 test_live_ai + Phase C 验收 test_phase_c_live，
  均需 `MF_ALLOW_LIVE_AI=1` 且配 LLM_API_KEY 才执行）；audit 5 学段全绿（27/31/81/59/60）；
  content validate **26/54**（真实库，随运行期 auto 增补；测试 hermetic 基线 13 人工节点不变）；
  前端 `npx tsc --noEmit` + `npm run build` 通过；git 仓库不含 data/、_drafts、resume/。
  品牌：YanHui（颜回）全科教练。当前工单见 §3（R27 已完成并验收 → 待用户真人复看 + 架构裁决疑点）。
