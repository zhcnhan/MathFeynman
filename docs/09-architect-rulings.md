# 09 · 架构侧裁决记录（Architect Rulings）
> 适用范围：范围：裁决历史（永续追加；R7–R18 为 math-preset 与引擎通用依据混合，注意上下文）

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

## R14 · 蓝图总纲 P1–P4 与 ABC 修订批裁决（docs/12 全学段蓝图 · 2026-09-08）

**核验**：架构侧复跑 pytest=177+1、content validate 13/30、5 学段蓝图 audit 全绿、git 提交链
吻合（613dbee…4d0a2c8）、零残留。**结论：全部接受并批准**。疑点逐条裁决如下。

### ABC 修订批（IMPLEMENTATION_NOTES §10）
- ✅ s22 运算律列表位在分数块前：接受（学完四则立即强运算律，分数在其后出现语义无碍）。
- ✅ s23 比 依赖百分数链（生成会连带 s09/s10 主题内容）：接受；入库总量按传递展开计算。
- ✅ id 序号与列表学习顺序不一致：接受，列表位置为真源；未来工具一律按列表序。
- ✅ REVIEW D（middle 全段扩段）：确认为后续批次（优先级=用户进入初中下半程前）。

### P1 high / P2 college / P3 ai（§12–14）
- ✅ 条目规模口径：以仓库轻条目粒度为准（primary 26/high 80/college 56/ai 57），docs/12 §4
  已改（§5 粗估仅参考上限）。
- ✅ 顺序/归属：一次函数归 middle、high 以真实节点前置引用衔接——接受；middle 扩段前不占位。
- ⏳ **跨学段 prereq**（audit 只能引用本文件条目或库内节点，跨 level.yaml 引用缺失）：
  裁决=**批准设计，列为引擎增强**（roadmap schema/audit/pipeline/selfextend 联动），
  落地前以"学段顺序 + 文件头衔接假设"兜底（现 high/college/ai 均已此方式，可接受）。
- ✅ 骨架外主题（复数等）暂不纳入：接受，精核可触发增补批。
- ✅ requires_thinking 启发式/≈90% think、信息论位置、量化近单链、随机过程归 ai 主线、
  数值计算归 college 工具线：全部接受（ai/college 衔接以文档承载）。
- ✅ c43（回归）补链 c34：批准为蓝图微调项，随下一精核批执行（同文件跨 run prereq 可用）。

### P4 护栏与口径变更（§15）
- ✅ **北极星制入库策略**（全学段自动入库 + guardrails 熔断）批准，取代 docs/10 §3 混合制与
  README 不可变 #9 旧表述——架构侧已同步修订 docs/10 §3、README #9、docs/12 §4。
- ✅ 熔断恢复口径 = pending 清零即恢复（MVP 近似），接受；"整条重生成替换后才恢复"列后续增强
  （依赖 feedback.regenerate 消费管线）。
- ✅ 阈值 0.3 / ≥2 / ≥3 初值接受，常量集中 guardrails.py 便于调参；CLI 手动通道不熔断接受。

### 给 Euler 的后续任务（排期另定，非紧急）
1. 跨学段 prereq 引擎增强（schema 扩展引用 level.yaml 条目 + audit/pipeline/selfextend 联动 + 测试）。
2. c43 回归分析补 c34 前置（college.yaml 微调）。
3. feedback.regenerate 真正"重生成替换"消费管线（替代当前仅标 reviewed + 待脚本消费）。
4. （可选）复数等高中增补候选：等用户精核 high.yaml 时收集意见。
5. REVIEW D：middle 全段扩段，待用户初中进度接近边界时排期。

**文档同步**：README #9、docs/10 §3、docs/12 §4 已同步北极星制；本裁决。

## R15 · 全学段蓝图精核裁决（三路学科评审 + 架构侧 primary/middle，2026-09-08）

**方法**：high/college/ai 各由一名独立学科评审逐条核对（按课标/面向 AI 量化主线），
primary/middle 架构侧直接精核；college 衔接假设已用 high 实际条目交叉核对成立。
**详细报告与补丁规格**：`content/roadmap/REVIEW2-master.md`（全学段 A/B/C + 汇总补丁清单）。

**裁决（采纳要点）**：
- 必修：high 补复数（high.h40b）；college 补 SVD/PCA（c34b）、随机过程初步（c43b 可选条目，
  ai 主线 a42–a49 维持）、c15 补 c07、全表补 thinking；ai 补贝叶斯推断（a04b）、变分 ELBO（a25b）、
  ADMM（a17b）、KKT 深化（a12 扩）、ARIMA/单位根（a46 扩）。primary/middle 无阻断。
- 建议优化与待学科项按 REVIEW2 清单执行（h79 前移、鞅/布朗顺序、各 prereq 微调等）。
- C 项定夺：三角函数线不扩（课标淡化）；数学归纳法按选学标注；导数止于高中标准（接受）；
  建模探究不单列条目（记设计边界）；极坐标/参数方程默认不列（扩展候选）；随机过程归 ai 主线。
- **执行**：以 REVIEW2-master.md 为规格交 Euler"精核补丁批"（只改 roadmap yaml + audit 再生 +
  全量回归，基线 177+1；既有 id 不动；新增沿用续号风格）；用户到段前滚动转正不变。

**文档同步**：本裁决 + REVIEW2-master.md。

## R16 · A/B/C/D 段复核裁决（跨学段 prereq、纠错重生成、middle 扩段、傅里叶 · 2026-09-08）

架构侧复跑：pytest=188+1、content 13/30、audit 5 学段全绿（26/31/81/59/60）、git 链与汇报吻合。

- **A 段生成语义**：跨学段前置"未落地→剔除引用 + audit.cross_gaps/selfextend 缺口提示、不占位补齐"
  → ✅ 批准（与 loader/图谱"内容不得指向不存在节点"一致；学段顺序推进兜底，北极星懒生成不变；
  未来如需"前置学段首批自动补齐"单独立项）。
- **C 段一次函数不占位 high.0201**：解释正确（占位将造成 middle↔high 掌握倒锁）→ ✅ 批准。
- **B 段口径**：无 key → auto 纠错记 failed（不排队、不回落 stub）；guardrails 未处置口径扩为
  pending|regenerating|failed、恢复=regenerated/reviewed → ✅ 批准（防失败重试误解除熔断；
  为 R14 原"pending 清零即恢复"的合理超集）。
- **D 段未闭合 6 项**：全部留档候选（c34/c43 互注随下次精核；SVD 幂法扩展候选；鞅严格化 =
  需要时新增"条件期望/测度基础"条目，默认直觉级够用；极坐标/复数候选待用户到段；c15b 滚动精核）。
- **遗留**：真人全自动冒烟（MF_AUTO_EXTEND=1 通关链路）为下一步用户侧验收。

**文档同步**：本裁决；NOTES §18–21 已为执行记录。

---

## R17 · 费曼轮次回炉未清零 → 409 锁死（真人使用发现 · 2026-09-08 架构侧热修）

**问题**：用户在费曼口述提交时收到 409（`费曼轮次已达上限，请重新学习后再来`），且口述文本
在浏览器端丢失（请求被拒+刷新）。根因：费曼 3 轮不过触发"回炉重学"（`_relearn_explain`）时
只重置了练习轮次，**未重置 `feynman.rounds_done`** → 用户重学后再次进入费曼即命中轮次上限，
永远 409。此前 500 修复（R10）后的 E2E 未覆盖"3 轮失败→回炉→再次费曼提交"路径（测试盲区）。

**裁决与动作（架构侧热修）**：
1. 新增模块级 `_feynman_reset(f)`（rounds/passed/last_*/followup 全清零）；
   `_relearn_explain` 与 `_cap_fail_cycle` 调用；`_enter_feynman` 防御：进入时轮次已满即复位
   （兼容历史遗留会话）。
2. 用户卡住会话已在 DB 复位（无需重学）；全量回归 188+1 复跑通过。
3. **给 Euler**：补 E2E"费曼 3 轮不过 → 回炉 → 重学 → 再次费曼可正常提交"；
   前端为长口述加草稿自动保存（本地），防止异常路径丢字。

**文档同步**：本裁决；代码注释标注 R17。

## R18 · 蓝图总序权威化：全学段教学/题目顺序严格化（用户指令 · 2026-09-08）

**背景问题（用户使用中发现）**：学习顺序出现错位——分数乘除（0104）先于乘法口诀（s03）可学、
四则混合（0101）与分数意义（0102）为根节点、整数 boss(0199) 门禁含分数节点、乘法口诀内容
前置被生成期静默剔除等。根因：**"能否学"由各内容文件手写 prereq 决定，与权威课程序（roadmap）脱节**。
用户指令：所有学段（小学/初中/高中/大学/AI进阶）教学与题目顺序**一环扣一环，绝对不许再错位**。

**架构裁决：学习进度由蓝图总序权威驱动（roadmap-authoritative progression）**
1. **总序语义**：对每个学段，roadmap 条目（含跨学段 prereq，A 段能力）构成学习图；某内容节点
   "可学"当且仅当：其所属蓝图条目 e 的全部蓝图前置（同文件+跨学段）已**达成**（达成=覆盖节点已
   mastered，覆盖=锚点节点或该条目 auto 节点），且 e 未达成；boss 节点另需其所属主题组全部条目
   达成。内容文件里的手写 prereq 仅作内容结构参考与展示，**不再单独决定可学性**（防再错位）。
2. **强制闭环**：仪表盘推荐、图谱可点、/session/start、复习推进全部过同一"总序门禁"；
   违反总序的请求直接 409 invalid_state。audit 新增不变式：任何内容节点不得引用"蓝图序中位于
   其后"的条目覆盖节点（防未来手写倒退），boss 与主题归属由 content.topic ↔ roadmap.topic 映射。
3. **数据/蓝图修正（随批执行）**：s03 内容 prereq 回填 [primary.s02]；新增小学蓝图条目
   "因数·倍数·质数合数·公因数公倍数（约分通分基础）"并正确入链（整数除法后、分数前）；分数
   锚点所属蓝图条目补该前置；boss 0199 主题映射/改名避免"整数 boss 含分数"（改"数与运算首领战"）。
   已掌握进度按覆盖节点迁移，不丢。
4. **验收 = 绝对不错位**：五学段各抽样链 E2E：早阶未达 → 409；依序掌握 → 下一环解锁；boss 门禁；
   图谱可用集 ⊆ 总序允许集；audit 无反向引用；全量回归不降（基线 188+1）。

**文档同步**：本裁决；实现按此规格，细化后回填 docs/03/05/06/07 相关小节。

## R19 · docs/14 Phase A 验收裁决（通用教练框架 A1–A4 · 2026-09-09）

架构侧复跑：pytest=245+1（72s exit 0）、audit 5 学段全绿、content 24/47、git 链与汇报吻合、
产物齐全（outline/{schemas,store,concepts,math_preset,generate,draft}、api/subjects、
service/outline_gate、content/subjects/math/outline.yaml 258 单元）。**批准全部完成**；
疑点逐条裁决如下：

- A1：objectives 上限=5（schema）且 AI 起草 ≤3 → ✅；重生成历史仅 git（不落盘归档）→ ✅ MVP；
  大纲文件=content/subjects + subjects 表为真源 → ✅ 双载语义；delete custom 学科进度级联 →
  Phase B backlog（删除前先 reset 语义）。
- A2：概念精确归一 MVP → ✅（aliases/同义合并入 docs/14 §7#3 治理）；core_concepts 兜底 → ✅；
  显式重置不清 attempt/session 审计 → ✅ 默认口径（如需连清另裁）；boss 概念经 core_concepts 进
  概念层（证据重复集语义无害）→ ✅ 保留。
- A3：大纲**单元 status 为转正单一真源**（primary=reviewed、其余=draft）；roadmap 文件头历史注释
  不动（源文档状态），精核转正时同步 status → ✅；v1 标签渐进覆盖（懒生成常态）→ ✅；
  level 语义抽离仅"非 LEVELS=fast 基础"锁定，NodeDoc 放宽待 Phase B → ✅ 现范围；
  boss 不入 outline（首领=关卡层概念，通用学科"里程碑"语义 Phase B 定义）→ ✅。
- A4：通用内容出稿=确定性 stub、真模型学科化（讲解/rubric 模板/语义题块）属 Phase B → ✅；
  通用学科主题熔断/token 限额接线 → Phase B 待办；outline_gate 无缓存可接受 → ✅；
  通用内容 prereqs=[]（顺序权威=大纲门禁）、UI 依大纲展示依赖 → ✅（UI 细化 Phase B）；
  E2E 以服务层达成替代浏览器费曼 → ✅（真人验收项在 /subjects 实测，配 LLM_API_KEY）。
- 附加治理（已测试锁定）✅：s27 红线段（s04<s27<s06）、0 掌握起点链=primary.s01、
  结构重组进度不丢、math 总序门禁（R18）未被 A4 分流破坏。

**给 Euler 的 Phase B backlog（不阻塞，先立档）**：通用学科熔断/token 限额接线；学科化
讲解出稿与 rubric 模板、语义问答题目块；delete_subject 进度级联（reset 后删）；outline 门禁
缓存（多学科大量节点时）；通用"里程碑/首领"单元语义；roadmap 文件头注释与大纲 status 统一
（精核批随转正做）。

**文档同步**：本裁决；docs/13 §3 当前工单已更新（Phase A ✅，待真人验收与 Phase B 派发）。

## R20 · 热修吸收 + 错误中文化 验收裁决（Euler 三块 · 2026-09-09）

架构侧复跑：pytest=258+1（74s exit 0）、git 链 d1859e8→9dfc25c→be5990b、工作树干净、
content validate 24/47。**批准完成**；疑点逐条裁决：

- **错误响应体**：以嵌套体 `{"detail":{"error":{"code","message(中文)"}}}` 为准（前端已双包装
  兼容；测试已锁）；docs/06 §1 已同步该表述。改扁平需另裁（牵动测试/前端，无必要）。
- 500 类别小字典 + 未知 →"系统处理"：✅ 接受（真实原因只进日志）。
- delete custom 学科后内容节点以 disabled 保留（R18 sync 语义）：✅ 接受；物理删除+仅留日志
  另裁留档（Phase B 可选）。
- outline_gate 指纹 = mtime_ns+size：✅ 接受 MVP；极端同指纹覆盖风险已有 `clear_outline_cache`
  兜底，可后续换内容 hash（留档）。
- 补充采纳（块1 内）✅：OutlineUnit.title 改必填（杜绝空 title 静默入库）；slugify 对齐数字开头。

**给 Euler 的 backlog 更新**：R19 backlog 中两条（delete 级联、outline 缓存）已被块3 完成，从清单移除；
新增可选留档（错误体扁平化/物理删除/内容 hash 指纹）。

**文档同步**：本裁决；docs/06 §1、docs/13 §2 已含中文化与嵌套错误体口径。

## R21 · 档位联动讲解缓存 + R22 · 内容源/学科生命周期决策（2026-09-09）

- **R21**：切换全局档位后，非"手动单次指定"的旧讲解缓存自动按新档位重生成（session
  _payload_explain 联动，显式单次存 explicit 不被翻回）。✅ 已实现并测试（b660949）。
- **R22（用户决策，docs/14 §8–§10 已记录）**：
  1. 每学科可选**内容来源策略**（AI 全生成 / 本地教材导入 / 联网候选清单 / 混合），用户自选；
     数学同能力（不独特）。
  2. 材料边界：联网=候选清单→勾选→本地化；本地导入自有/授权 PDF/文本；**不整本自动下载**。
  3. 学科生命周期统一"**移除可恢复**"：删除任何学科（含 math）= 列表移除+清进度+停用，
     文件/roadmap 留盘可重新启用；启动不复活被移除的 math（尊重停用标记）。
  4. 试点：自定义学科"完整可学"首批打磨对象 = 用户已建的「行星科学」（Phase B 交付真内容）。

**文档同步**：本裁决；docs/14 §8–§10、README/13 随批次执行时同步。

## R23 · Phase B（B1–B5）验收裁决（2026-09-09）

架构侧复跑：pytest=269+1（82s exit 0）、content 26/49（真实库，测试 hermetic 13 基线不变）、
git 链 B1→B5 与汇报吻合、工作树干净。**批准完成**；NOTES §34–§38 疑点逐条裁决：

- B1 #1 heuristic 单选"正项恒第 1 项"做题套路 → **修**：heuristic 生成时按确定性种子打乱选项顺序
  并同步 answer_index（AI 路径选项本已自然分布）。列为下批微任务。
- B1 #2 fill_text 归一化 MVP 范围 → ✅ 接受（繁简/标点变体随 docs/14 §7#3 治理）。
- B1 #3 跨轮次题面去重 → ✅ 暂不要求（稳定题组+校验已足），可选项留档。
- B4 #1 "移除=大纲/内容留盘可恢复"（soft 清进度/概念）→ ✅ 符合 R22/docs/14 §9 口径；无需
  removed_outline 重建语义。
- B4 #2/#3 停用学科的 UI 级隐藏（仪表盘/地图/图谱按 enabled 过滤）→ 列为后续"学科管理/设置"
  批次（引擎侧 start=409/locked 已是安全底线，视觉打磨延后）。
- B3 #1 外部检索后端 → Phase C（当前离线明确提示满足 MVP）；#2 PDF 二进制解析 → 引解析器时扩展
  （上传契约已预留分节文本）；#3 heuristic 不用材料改写题目（仅来源标注，AI 路径承担改写）→ ✅ 合理。
- B5 #5 偶发 PUT outline 405 → 留档（不可复现，疑似路由注册顺序环境偶发；已规避；复现再查）。

**给 Euler backlog 追加（小）**：heuristic 选项乱序+answer_index 同步；停用学科 UI 过滤随学科管理批次。

**文档同步**：本裁决。

## R24 · Phase C（C1–C6）验收裁决（2026-09-09）

架构侧复跑：pytest=291+2 离线（87s exit 0，+2 skip=live 需 MF_ALLOW_LIVE_AI=1）、audit 5 学段全绿、
content 26/49、git 链 c365412→107ccad 与汇报吻合、工作树干净。**批准完成**；疑点裁决：

- 检索 provider 仅 SearXNG（扩展位已留）：✅ 接受；**真实端到端=用户自托管 SearXNG 后复验**（用户动作，代码已 mock 锁定）。
- robots/noindex 未逐条解析：✅ 接受（仅用户勾选 + text/html + 上限）；可选改进留档。
- PDF 无 OCR：✅ 接受（扫描版提示 OCR/粘贴）；20MB/400 页/8000 字上限可配。
- AI 起草跨单元题面去重：✅ 按 R23 B1#3"可选"口径接受；需严格化时另立。
- PUT outline 偶发 405 未复现：✅ 留档（OpenAPI+live 双守卫已加；复现再查路由注册顺序）。
- soft 移除对 preset(math) 清全量内容进度（docs/14 §9 的超集）：✅ 接受——移除=停用并清进度，
  "重新启用"从空进度重新开始，符合可恢复语义；已在 NOTES 注明超集口径。

**backlog 收敛**：R23 遗留两条已闭合（heuristic 乱序 C4、停用 UI 过滤 C3）；本轮新增可选留档
（robots 解析、PDF OCR、跨单元去重、SearXNG 真机复验=用户动作）。

**文档同步**：本裁决。

---

- 架构侧独立验证（2026-09-08）：11 个内容节点真实存在；Euler 复审回归 136 passed/1 skipped
  经架构侧复跑确认（2.11s exit 0）；前端 tsc 通过。完整套件用户侧命令：
  `.\.venv\Scripts\python -m pytest backend\tests`。


