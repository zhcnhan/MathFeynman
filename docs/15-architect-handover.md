# 15 · 架构师交接（Architect Handover）—— 本会话延续用

> 你是"架构师/费曼"角色的延续会话：负责**讨论、裁决、文档化、把关 Euler 汇报与路线**，
> 不写实现（实现归 Euler）。仓库内全部记忆外置，本文件 = 你的开机清单与当前状态。

## 1. 开机清单（新架构师按序执行）
1. 读 `README.md`（不可变决策、演进声明、文档导航）+ 各 docs 头部"适用范围"标签。
2. 读 `docs/09`（R1–R22 裁决史——你的决策依据链，务必读最新 R21/R22）与 `docs/14`（通用教练总纲，含 §8–§10 最新决策）。
3. 读 `docs/13`（Euler 交接，含行为公约：docs 唯一事实源、中文错误绝对要求、每步回归、git 提交）。
4. 读 `IMPLEMENTATION_NOTES.md`（实现运行日志，最新到 §3x）与 `USER_FEEDBACK.md`。
5. 其余 docs/01–12 按需精读（判题/状态机/AI 集成/总序/蓝图）。
6. **基线验证**：`pytest backend/tests` 期望 **258 passed + 1 skipped**（此后随新批上升）；
   `content validate` 绿；audit 5 学段全绿（27/31/81/59/60）；git 干净。
7. 与用户确认身份后，追加本文件"会话续接"记录（时间 + 基线）。

## 2. 角色纪律（你如何不“失忆地”工作）
- 一切结论落到 docs/09 新裁决（下一个 R 编号）+ 对应文档；一切进度/疑点让 Euler 落
  IMPLEMENTATION_NOTES。**文档是记忆，对话只做讨论。**
- 把关 Euler：每批回来先独立复跑（pytest/audit/validate/git），再给裁决（R 号）与放行。
- 维护规则常青：docs 唯一事实源；错误必须中文；Euler 每里程碑 git 提交；范围内改动前先改文档。

## 3. 当前状态（截至 2026-09-09）
- 产品：通用费曼教练（docs/14）已过 Phase A（A1–A4），数学=preset（总 Outline 258 单元），
  通用学科端到端（行星科学）真人验证通过；Euler 侧三块吸收批 + 中文化已完成（258+1）。
- 基线：pytest 258+1；audit 5 学段全绿；docs 14 篇（R1–R22）；git 提交含最近 8812995。
- **进行中/待办（最重要）**：
  a) 已向用户给 Euler 派 **Phase B 整合工单（B1 学科化真内容·行星科学试点 → B2 题目多样 →
     B3 内容来源策略+材料层 → B4 学科移除可恢复·math 不再特殊 → B5 回归验收）**，文本在
     用户手中，**待用户粘给 Euler**；用户读 docs/14 §8–§10 与 docs/09 R22 可获得规格源。
  b) R21 档位联动讲解缓存已实现（b660949）；其回归用例补入下一 Euler 批次清单。
  c) 数学内容（roadmap 到段精核/内容懒生成）持续治理项照旧。
- 待裁决空档：无（R22 已清）；新裁决从 **R23** 起。

## 4. 常见口径（前车之鉴，直接沿用）
- 错误响应体嵌套 `{detail:{error:{code,message 中文}}}`；500 不裸堆栈（docs/06/13）。
- 判题 sympy L1（math preset）；语义走费曼 rubric；通用学科评估插件分 L1/L2/L3。
- 学科生命周期=移除可恢复；内容源策略 ai|import|web|mixed；材料=候选清单+本地导入（不整本下载）。
- 蓝图/大纲 status 为转正单一真源；总序权威（R18）；概念层管"换大纲不丢进度"（Phase A）。

## 5. 环境速查
- 服务 scripts\dev.ps1（前端 5173/后端 8000）；日志 .runtime\backend.err.log。
- .env：LLM_API_KEY / MF_AUTO_EXTEND / LLM_MAX_TOKENS_PER_DAY；git 三端镜像 git-mirror（GitHub↔Gitee，
  仓库 zhcnhan/MathFeynman 与 gengzisama/MathFeynman）。
- 用户是"架构师↔Euler"之间的唯一中继：你给指令文本，用户粘贴；Euler 汇报由用户带回。
