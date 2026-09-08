# 09 · 架构侧裁决记录（Architect Rulings）

> 架构侧（费曼/架构师）对实现工程师（Euler）在 `IMPLEMENTATION_NOTES.md` 中提出的
> 疑点与增补的正式裁决。裁决一经发布即生效；相应文档已同步（保持 docs 为唯一事实源）。
> 编号规则：R<序号>，内容为"问题 → 裁决 → 文档同步动作"。

---

## R1 · 会话推进 action `next`（docs/06 §2 增补）

**问题**：docs/06 的 action 枚举无"阶段前进"动作，而 docs/07 UI 有"明白了，看例题"按钮，
Euler 补充了 action `next`（讲解→例题→练习）。

**裁决**：✅ 批准。`next` 是流程推进必需动作，与状态机语义一致。
**文档同步**：docs/06 §1 `POST /session/step` 的 action 枚举已加入 `next`。

## R2 · 判题答案表达式语义与 `check.equation` 字段（docs/04 §2 增补）

**问题**：docs/04 样例中 `answer_expr` 写作 `(c-b)/a`（无花括号），实现落地为 **sympy 符号表达式、
参数作符号代入求值**（prompt/equation 用 `str.format`，answer_expr 用符号求值）；
`equation_solution` 模式的机器方程由 content 的 `check.equation` 字段提供（docs 样例未含）。

**裁决**：✅ 批准。双模板语义（花括号=文本格式化、无花括号=符号表达式）清晰且自洽；
`check.equation` 是 sympy 解方程判题的必要补充字段。
**文档同步**：docs/04 §2 增加字段说明（见该节"判题模式"后的字段注释）。

## R3 · 费曼评分轮次（docs/05 §5 解释）

**问题**：docs/05 表述"≤2 追问"，实现为首评 + ≤2 次追问 = 至多 3 次评分，3 次不过回炉。

**裁决**：✅ 与 docs/05 §5 第 4 步"3 轮仍不过 → relearn"一致，无需改动。

## R4 · 离线费曼启发式评分（无 API Key 桩）

**问题**：无 key 时口述 ≥20 字且含任一 core_concept → 各维 0.9，否则 0.35 → followup。

**裁决**：✅ 批准，但**仅限降级兜底路径**：真模型可用时此路径不得抢占（provider 可用性优先）。
该启发式不可作为"掌握"判定的正式依据，产品验收以真模型 evidence 为准。

## R5 · 时间存储约定（naive UTC）

**问题**：SQLite DateTime 列存 naive UTC（驱动读回无 tz）；JSON 状态内保留 aware ISO。

**裁决**：✅ 批准。统一写 UTC、展示层本地化，符合 docs/06 约定精神。

## R6 · M3 真模型冒烟待 key（未决，属用户动作）

**问题**：本环境无 `LLM_API_KEY`，`tests/test_live_ai.py` 被 skip（1 skipped）。

**裁决**：不阻塞引擎。**用户动作**：配置 `.env` 的 `LLM_API_KEY` 后运行
`pytest backend/tests/test_live_ai.py` 完成真模型验收；随后进行 docs/08 的真人走查
（浏览器学 1 节点 + 费曼 evidence）与 3 天复习观察。此三项完成后 M5 正式关闭。

---

## R7 · SQLite 写锁长事务热修（真人走查阻断 → 架构侧紧急处置）

**问题**：真人走查发现点击任意节点 `/session/start` 大多返回 500，日志为
`sqlite3.OperationalError: database is locked`（INSERT INTO sessions）。
根因：`service/session.py` 在数据库事务**未提交**时同步调用 LLM（explain 等可达 60–100s），
整个请求期间持有 SQLite 写锁；期间任何其它写请求（再次 start / 判题落库等）等待 5s 后超时报 500。

**裁决与动作（架构侧热修，Euler 需复审并吸收为长期设计）**：
1. `service/session.py::_call`：改为实例方法，**调用 LLM 前先 `db.commit()` 释放写锁**；
   5 处调用点同步传入 `db`。LLM 失败仍走离线兜底；事务边界 = 每次 LLM 前后各一事务。
2. `db.py`：增加 `PRAGMA busy_timeout=30000` 作为并发写等待兜底（防瞬时 500）。
3. **给 Euler 的长期建议**：讲解/评分这类慢 LLM 环节考虑移出请求事务（或异步任务 +
   轮询），并给"同一节点生成中"加防重入（避免并行重复调用 LLM）；前端已单飞（busy），
   建议复核。

**文档同步**：本裁决；代码注释已标注 R7。

## R8 · 数学渲染器容忍化重写（真人走查阻断 → 架构侧热修）

**问题**：真人走查确认页面**直接显示 LaTeX 源码**（如 `$\frac{7}{9}-...$`、孤立的 `$$`）。
根因：`frontend/src/components/MdMath.tsx` 为手写渲染器，行内 `$...$` 用
`/(\$[^$\n]+\$)/` 逐行匹配——**不跨行**；显示公式只认"行首 `$$`"；对 LLM 输出中
不规范的 LaTeX（公式折行、分隔符杂散、`$$` 与文字同行）零容错 → 直接按纯文本显示。

**裁决与动作（架构侧热修）**：
1. 重写 MdMath.tsx（R8 版）：先非贪婪整块配对 `$$...$$`（容忍跨行/行中）→ 清理孤立 `$$`
   → 行内 `$...$` 允许含换行、含中文或超长片段不当数学 → KaTeX 失败才降级 `<code>`。
2. **给 Euler 的任务**（复审 + 长期防复发）：
   - 代码复审本渲染器；
   - `ai/prompts.py` 增加 LaTeX 输出纪律（显示公式 `$$...$$` 单独成行、行内公式单行不折行）；
   - 对已缓存的脏讲解（如当前会话 lecture_cache）提供"重新生成讲解"入口或清理路径。

**文档同步**：本裁决；MdMath.tsx 头注释已标注 R8。

## R9 · 性能与走查打磨批次（Day1 走查反馈 → 架构裁决，交 Euler 执行）

**背景**：真人走查完成首节点闭环（可用性达标），反馈集中在等待体验与细节，裁决如下：

1. **讲解环节降速档**：`explain_node`（含重新生成）与 `ask` 的等待过长源于 heavy 档推理模型。
   **裁决**：`explain_node` 改为 `light` 档（deepseek-chat）：讲解是"基于注入讲解稿演绎"，
   不依赖深度推理，light 足够且快得多；`feynman_evaluate`/`feynman_followup` 维持 heavy。
   若实测质量明显下降可回滚并在本裁决留痕。
2. **等待可感知化（必须）**：前端所有 AI 等待点（讲解/提问/提示/费曼评分）显示
   "⏳ AI 正在思考… 已用时 Xs"（提交按钮禁用+计时），杜绝"像卡死"的观感。
3. **自测问题（asks）走数学渲染**：ExplainView 的 asks 逐条经 MdMath 渲染；全前端排查
   其它"含 LaTeX 却按纯文本渲染"的位置。
4. **复盘记录页**：加"← 返回/回仪表盘"导航；Session 页与复盘页导航一致性检查。
5. **费曼维度中文标签**：UI 层维护 key→中文映射（correctness=概念正确性、
   own_words=用自己的话、example_and_edge=例子与反例、self_correction=自纠能力），未知 key 显示原名。
6. **偶发"找不到页面"**：路由兜底（未知路径 → 仪表盘）+ 全局错误横幅；请用户下次复现时
   记录地址栏 URL 与浏览器控制台，供 Euler 定位（疑似 dev 路由/提交竞态，暂未复现）。
7. **流式输出（边生成边显示）**：列为 P1 优化候选，本轮不实现，避免范围膨胀。

**执行**：Euler 按 1–6 实现并跑全量回归；结果回报本裁决。

## R10 · 费曼追问 500 热修（Day1 走查第二轮发现 → 架构侧紧急处置）

**问题**：费曼口述**首轮未达标进入追问**时 500（"会话不可用"）。日志：
`ValidationError: FeynmanFollowupIn.previous_scores.0 Input should be a valid dictionary`。
根因：`flow.feynman.last_scores` 存的是"每轮评分卡 = 分维 dict 的**列表**"，
即 last_scores 是"列表的列表"；而 schema 要求：
- `FeynmanFollowupIn.previous_scores: list[dict]`（分维列表）—— 原代码传了整个 last_scores → 炸；
- `FeynmanEvaluateIn.previous_round: dict | None`（上一轮摘要）—— 原代码传了 card 列表 → 二轮评分也会炸（暂未暴露）。
首轮直接通过（≥0.7）不触发追问，故此前 E2E 与首节点走查（76 分一次过）均未命中。

**裁决与动作（架构侧热修）**：
1. `service/session.py`：followup 的 `previous_scores` 传**最近一轮评分卡**（`last_scores[-1]`）；
   evaluate 的 `previous_round` 构造摘要 dict `{round, combined, dims: 最近一轮卡}`。
2. **给 Euler**：补回归测试覆盖"费曼首轮未过 → 追问构造 → 二轮评分"全路径
   （现有 E2E 未覆盖该分支，属测试盲区）。

**文档同步**：本裁决；代码注释已标注 R10。

## R11 · 练习回炉 500 热修（Day1 走查第三轮发现 → 架构侧紧急处置）

**问题**：练习**连续答错 2 次**（或一轮 5 题未达标）触发"回炉讲解"时 500。日志：
`AttributeError: 'SessionService' object has no attribute '_practice_reset_cycle'`。
根因：`_practice_reset_cycle` 是**模块级函数**（session.py L110），但 `_cap_fail_cycle` 与
`_relearn_explain` 用 `self.` 调用 → 运行期 AttributeError。该分支自 M2 即存在，
**测试从未覆盖**（答错 2 次回炉 / 5 题 cap 回炉均无用例），属第二个测试盲区。

**裁决与动作（架构侧热修）**：
1. 两处调用点去掉 `self.`，改调模块函数；编译 + 全量回归 139 passed 复跑确认。
2. **给 Euler**：
   - 补 E2E：练习连续答错 2 次 → relearn_explain（stage 回 explain、事件流正确、200）；
     一轮 5 题未达标 → cap 回炉；费曼 3 轮不过 → 回炉（同函数路径）；
   - **做一次 service/session.py 的分支覆盖审计**（pytest-cov 或人工核对），消除"未测分支
     上线后才炸"的模式——R10/R11 连续两处均由此产生。

**文档同步**：本裁决；代码注释已标注 R11。

## R12 · 模型动态自适应策略（用户讨论决策 → 架构裁决，交 Euler 执行）

**背景**：用户反馈"大多数数学场景快模型够用，偶发/进阶才需思考模型"，要求灵活可调。
讨论结论（用户选定）：内容难度自适应为主 + 三个自动升级触发 + 全局三档模式 +
答题过程即时切换 + 流式输出纳入本批。

**1. 模型策略解析器（新模块，如 `ai/tier.py`）**
对每次 AI 调用，决策链：`基础档(内容) → 升级触发 → 用户覆盖`，输出 `fast | think`。
- 基础档：学段 primary/middle/high → fast；college/ai → think；节点内容标记
  `feynman.thinking: true`（或顶层）→ think（内容库字段可选，缺省按学段）。
- 升级触发（升级为 think）：
  a. 费曼：首轮 fast 评分综合分 ∈ [threshold−0.15, threshold+0.10]（边缘）→ 下一轮评估用 think；
     轮次 ≥2 → think。
  b. 超纲答疑：fast 答疑返回标 `out_of_scope/needs_more_info` → 同一问题自动用 think 重生成一次
     覆盖回复（用户感知为"这个问题值得深思"）。
  c. 学段/内容基础即 think 者（见基础档）。
- 用户覆盖（优先级最高）：
  - 全局模式 `model_mode: smart | light | deep`（存画像 profile）：
    light = 触发 a/b 关闭、college/ai 仍 think（保持进阶底线）；deep = 全部 think；smart = 上述规则全开。
  - 每次提交的即时覆盖：请求 payload `think_deep: true|false|null`，对**该次调用**生效。

**2. 涉及调用点**：explain_node / answer_question / hint_on_error（少用 think）/ feynman_evaluate /
feynman_followup。schema 需补：answer_question 输出加 `out_of_scope: bool`；feynman_evaluate
输出加 `confidence`（供边缘区间决策参考，非必须字段）。

**3. 流式输出（SSE）**：本批实现，协议由 Euler 细化并同步 docs/06 §2 与 docs/07
（建议：`POST /session/step` 加 `?stream=1` 或以独立 SSE 端点下发 LLM 文本增量，最终仍以
原 JSON 状态响应收尾，保证前端"渲染指令=后端状态机"契约不变）。重生成/讲解/答疑/费曼文本均可流式。

**4. 测试与验收**：tier 解析器单测（学段×触发×覆盖矩阵）；流式端点与回退（流不可用→整体 JSON）测试；
全量回归不降（当前 139）。建议 Euler 分两段汇报：先 1+2（策略层），验收后再 3（流式）。

**文档同步**：本裁决；代码注释标注 R12；docs/02 §4、docs/05 调用点表、docs/07 设置页
将在实现稳定后由架构侧同步修订。

## R13 · 在线"内容自续"500 热修（AI 出稿器服务侧接入缺失 → 架构侧紧急处置）

**问题**：用户点击"继续下一关"报 500。日志 `TypeError: 'NoneType' object is not callable`
（pipeline.generate_entry → drafter(entry)）。根因：`selfextend.extend` 在
`use_ai=True`（已配 LLM_API_KEY）时把 drafter 直接置 None（注释称"AI drafter 由 scripts 侧
接入"）——但 `/api/selfextend/run` 是服务端入口，从未接线 → 有 Key 用户必炸；
scripts CLI 的 `_ai_drafter_factory` 只服务命令行。属阶段 3 交付的接线缺口，测试（离线桩）
未覆盖"有 key 的在线路径"。

**裁决与动作（架构侧热修）**：
1. 新增 `backend/app/ai/drafting.py`：`make_ai_drafter(settings)` 收编原 scripts 的 AI 出稿
   （CALL_DRAFT_CONTENT schema 化、light 档、无 key → None、输出非法 → DraftingError）。
2. `selfextend.extend`：有 key → `make_ai_drafter`，工厂失败即抛错（**不**静默回落桩，防
   stub 占位内容被 auto 策略误入库）；无 key → 桩（机制可用）。
3. **给 Euler**：复审 + 将 scripts/gen_content.py 的重复出稿逻辑改为复用 ai/drafting，
   消除双份漂移；补"有 key 在线路径"的接线测试（mock provider，不真调 API）。

**文档同步**：本裁决；代码注释已标注 R13。

**R13 补记（2026-09-08，同题继续修复，均已实测）**：
- 在线生成真实调用后暴露三层问题并逐一修复：① draft_content 用 json_object 但提示词无
  "json" → 400（提示词改为输出 `{"draft_md": "…"}`，且 scripts 复用 backend ai/drafting 去重）；
  ② AI 输出缺 feynman 必填 → 提示词内置节点骨架；③ 漏结尾 `---` → 铁律约束。
  已端到端实测：AI 出稿 2 条（13s），front-matter/sympy 校验全过（样本已清理）。
- **给 Euler**：补"有 key 在线出稿"接线测试（mock provider）与出稿失败自动修复重试
  （当前靠提示词，稳健性可再提升）；测试对 stages/_drafts 写入的清理需健壮化
  （本次发现中断测试残留 auto 文件致图谱校验失败，架构侧已人工清理）。

---

- 架构侧独立验证（2026-09-08）：11 个内容节点真实存在；Euler 复审回归 136 passed/1 skipped
  经架构侧复跑确认（2.11s exit 0）；前端 tsc 通过。完整套件用户侧命令：
  `.\.venv\Scripts\python -m pytest backend\tests`。


