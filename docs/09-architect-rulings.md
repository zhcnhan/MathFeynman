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
---

## R25（补记）· 费曼追问语义 v1：补充回答并入评分（2026-09-09 · 由 R27 取代）

**问题**：费曼首轮未过后，学生回答追问被视为一次新提交，但评分永远只盯最初口述 → 追问形同摆设。

**当时裁决与实现**（7e7c684）：非首轮提交 = 对"追问"的补充回答 → 评估对象 = 合并稿
「最初讲解 + 【AI 追问】 + 【我的补充回答】」，followup 并入后清空；任务提示钉显；
练习纠错后可一键"换新题"（同批）。**用户实测仍不满 → 升级为 R27。**

## R26（补记）· 自定义学科纠错重生成走学科化出稿（2026-09-09）

**问题**：通用学科（行星科学等）内容纠错重生成误走数学 RoadmapEntry 路径 →
`ValidationError: RoadmapEntry level 非法学段`（generic ≠ math，不得复用数学 schema）。

**当时裁决与实现**（e4a9d6c）：`feedback._regenerate_node_now` 分支——通用学科节点
（`node_id.split(".",1)[0] not in LEVELS`）→ `outline.generate.generate_unit_content`
学科化重生成；后台异常不再静默吞（failed + 原因落库）；数学路径维持旧逻辑。已完成验收。

## R27 · 费曼追问语义 v3：混合制（补答认账 + 整合终验）（用户讨论决策 · 2026-09-09）

### 背景与证据（用户实测，s-f2decfcf.u01 费曼轮次 id=29→30→31）

| 轮次 | 内容 | 综合分 | 评分卡 |
|---|---|---|---|
| id=29 | 首轮"我真的不知道怎么讲…" | 0.0 | 全维 0（合理） |
| id=30 | 答追问1（太阳系组成+引力钩子） | 0.455 | correctness .6 / own_words .7 / evidence .3 / self_correction 0 |
| id=31 | 答追问2（"钩子拉力是否一样"→ 类地/类木成因，回答完整精彩） | **0.455** | **dims/evidence/comment 与 id=30 逐字相同；evidence 仍引 id=29"我真的不知道"** |

**两层问题**：
1. **评分锚定 bug（R25 遗留）**：每轮把「最初稿 + 所有追问 + 所有补充」拼成超长合并稿整体
   重评 → LLM 注意力被开头文字锚定，新增回答不进评分（id=31 为铁证：答得越精彩分越不动）。
2. **语义错位**：追问是"分步引导"（一次一个问题、自由发问、不保证覆盖全部任务点），
   通过线却是"完整讲解整段加权 ≥0.7"——评价对象不同；用户任务点"科学家怎么研究"未被
   追问也未答中（id=30/31 均卡此），学生感知"答了也不认 → 追问没意义"。

**用户决策（讨论结论，逐条拍板）**：费曼应同时验证 (a) 引导下能把缺口逐点答对（答对认账、
立刻加分、看得见）+ (b) 能完整独立讲明白（整合终验）→ **混合制**。参数：预算宽
（首讲 + ≤2 补答 + 终验可再试）、缺口保留可再追。

### 裁决规格（v3，取代 R25 的合并稿语义）

1. **两类提交，语义分离**：
   - `feynman_submit`（完整稿）：首讲 / 整合重讲。整体评分（feynman_evaluate）。
   - `feynman_answer`（补答）：只答当前追问。走**新增的缺口补答评分**，不是整体重评。
   - 不再拼接合并稿。`transcript` = 本轮学生文本（首讲=初始稿；终验=整合稿）。

2. **评分对象改革（治锚定）**：
   - 整体评分：`feynman_evaluate.transcript` = 本轮完整稿；新增上下文
     `previously_acknowledged`（账本已认可内容摘要）——学生没把已认可点重抄一遍不扣分。
   - 补答评分：新增轻量评估（复用 feynman_evaluate schema 或新 `gap_check` 调用，Euler 定）：
     输入 = task_prompt、rubric_dims、本轮追问、学生补充回答、目标缺口
     （维度 key + 学生视角缺口描述 + 上轮 evidence/comment）；
     输出 = `{gap_filled: bool, dimension_updates: [{key, score, evidence_quote, comment}]}`
     （只允许更新该缺口所属维度）。
   - **evidence 纪律（硬校验）**：评分卡 evidence_quote 必须逐字出自本轮提交文本。
     服务端做包含校验：evidence 不在本轮文本中 → 程序标记/降级，防"没读新内容还打分"。
   - 分数合成：账本维度分 = max(历轮该维度分, 本轮更新)；实时综合分 = Σw·账本 / Σw。

3. **缺口账本（flow.feynman 扩展）**：
   - 新增 `ledger`（各维度历轮最高分 + 缺口清单）；整体稿评分后，未达标维度的
     "缺什么"（从评分 comment/新输出提取）进入缺口清单 → 追问**定向**到最弱缺口
     （一次一个），不再自由发问 → 任务点漏问问题随之缓解（缺"研究方法"就追问研究方法）。
   - 追问生成输入（feynman_followup）增 `unmet_gaps`；主题仍可参考 socratic_followups。

4. **轮次预算（宽，用户拍板）**：
   - 整体稿评分（feynman_evaluate）预算 = 3（首讲 + ≤2 次终验）；
   - 补答预算 = 2（须有未答缺口；同一缺口答不对 → 保留缺口、可再追一次）；
   - 终验 <0.7 → 若补答/整体稿额度未尽 → 允许再补答后再终验；
   - 两额度尽或 3 次整体稿未过 → 回炉（relearn，沿用 _feynman_reset）。
   - `MAX_FEYNMAN_ROUNDS` 旧计数（3 次评分）被上述两额度取代；实现注意保持既有
     R10/R11/R17 测试分支语义（轮次上限 409、3 轮不过回炉、回炉清零）不回归。

5. **通过判定**：
   - 任意一次整体稿（首讲或终验）评分 ≥ threshold → pass → mastery；
   - 补答只涨账本与展示进度，**不能单独过关**（防"挤牙膏式被动应答"替代完整输出）。

6. **UI（FeynmanView / SessionPage）**：
   - 两个提交入口并存：有追问时主按钮「回答追问」= feynman_answer；副按钮
     「整合后完整重讲」= feynman_submit；无追问时「提交讲解」= feynman_submit。
   - 实时得分条：各维度账本分 + 缺口提示（"还差：科学家怎么研究——说出任意一种
     观测/探测方法即可"）+ 综合分/门槛进度条。答追问后立即刷新，看得见涨分。
   - task_pinned（环节任务钉显）保留。

7. **测试与验收（Euler）**：
   - 三条集成路径（离线桩驱动）：① 首讲 0.0 → 答追问（含核心词）→ 缺口维度分真实上升
     （断言 ledger 变化，不再出现"两轮逐字同分"）；② 首讲未过 → 补答补缺口 → 整合重讲
     含全部要点 → 整体 ≥0.7 → pass/mastered；③ 补答尽 + 终验仍 <0.7 → 回炉；
   - evidence 纪律校验测试（evidence 必须 ⊆ 本轮文本）；
   - 数据回归：行星科学 s-f2decfcf.u01 真人再走，确认"答追问后分数可见上升"；
   - 全量 pytest 不降（基线 291+2 离线）、前端 build、错误中文化（绝对规则不变）。

**文档同步**：本裁决；docs/05 §5 费曼流程更新为 v3（见该节）；docs/13 §3 工单已替换为
本裁决派工；IMPLEMENTATION_NOTES 由 Euler 实现时追加执行记录。
## R28 · R27 验收裁决（费曼追问 v3 · 2026-09-10）

**架构侧独立复跑（不采信汇报）**：pytest **305 passed + 2 skipped**（307 collected，exit 0，架构侧两次复跑一致）；
`npx tsc --noEmit` 通过；`npm run build` 通过（1.18s）；content validate **ok 26/54**；
audit 五学段全绿（cycles/content_prereq_violations/boss_unmatched/anchors_missing 全 0）；
git 链 187f0d0→443efb0→bfd5bea→a3dbddc 与汇报吻合；工作树干净。
代码审查确认：R25 合并稿拼接已**彻底移除**（`backend/app` 内无"【AI 追问】/【我的补充回答】"残留）；
`_enter_feynman` 现为单一定义且保留 R17 防御；补答只允许更新 `target_gap` 维度（越权键被丢弃）；
账本 max 合成、回炉清账本、evidence 归一化包含校验与 ×0.5 降级均按规格落地。
**结论：R27 功能验收通过**；以下 5 项为留档/更正项，不阻塞。

### F1（须更正汇报口径）· 真模型回归数字与留档不符
汇报称"整合终验 0.863 pass（1.0/0.8/0.85/0.6）、补答 correctness 0.0→1.0、综合 0.0→0.4"。
实测留档（`%TEMP%\mf_r27_live.db`，架构侧已复核）为：
- id=4 首讲 0.0（四维全 0，evidence_valid=True）→ id=5 补答 correctness **0.95**、账本综合 **0.38** →
  id=6 终验 **0.73** pass、本轮卡 **correctness 0.95 / own_words 0.55 / evidence 0.60 / self_correction 0.60**；
  session `stage=done, passed=True, rounds_done=2, answers_done=1`。
**定性结论成立**（答追问后分数可见上升、不再出现"两轮逐字同分/引文引旧文"、终验过线）——
但**数字须以留档为准**。另：该回归跑在**临时 DB**（非应用库 `backend/data/mathfeynman.db`），
应用库最新记录仍是 R27 之前的 id=31，用户真实节点未被改写（无数据风险）。
**给 Euler**：今后真模型回归必须留档——DB 路径 + 各轮 score/dims/evidence_valid 写入
IMPLEMENTATION_NOTES 对应小节；汇报数字直接取自留档，不得口述估算。

### F2 · session.py 行尾符翻转（整文件伪 diff）
443efb0 将 `backend/app/service/session.py` 由全 LF 改为全 CRLF（0→1340 CRLF），
致该文件 2448 行伪 diff、覆写 blame。仅此一文件（gateway/前端未翻转；仓库本身混用：
104 个 .py 为 LF，7 个历史 CRLF）。
**裁决**：列为下批微任务——`session.py` 归一化回 LF + 增 `.gitattributes`
（建议 `*.py text eol=lf`、`*.ts`/`*.tsx text eol=lf`；docs 的 CRLF 维持现状），防复发。

### F3 · 通过判定用"账本累计分"而非"本轮完整稿分"（留档待裁）
`_act_feynman` 的 `passed` 依据 = `fl.combined(ledger)`（维度历轮 max）≥ threshold，
而 R27 §5 字面为"任意一次**整体稿评分** ≥ threshold"。差异：补答抬高的维度分会被后续
平庸完整稿"继承"。本次实测两者同值（0.73）未触发偏差；防挤牙膏的底线（必须交完整稿）仍在。
**裁决**：✅ 接受现状（符合"答对认账"精神、且学生仍须交完整稿），但**列入用户裁定项**：
若要求"末次完整稿自身须过线"，改为对本轮 card 单独合成即可（一行改动）。

### F4 · 补答未补上后追问被清空（规格保真度）
`_act_feynman_answer` 结束时 `f["followup"]=None`，而 `feynman_answer` 要求存在追问 →
"同一缺口可再追一次"实际须**先再交一次完整稿**换取新追问（预算自洽：整体稿≤3 / 补答≤2）。
**给 Euler**：UI/文案把"稍后可再追一次"说清为"再交一次完整讲解后，会针对该缺口再问"。

### F5 · evidence 校验无最短长度门槛（加固建议）
现为"归一化（去空白/标点/省略号）子串包含"；极短引文（如单字）可平凡通过。
**给 Euler**：加最短归一化长度（建议 ≥6 字）才认定有效，否则按无效降级；与 F3 同批做。

**文档同步**：本裁决；NOTES §46–§47 已含实现记录（数字更正见 F1）；docs/13 §3 工单关闭（R27 ✅）。

### R28 补记（证据链澄清 + F6）

**F1 进一步核实**：`_dsh-local/r27_live.out`（utf-16，13:01:11 落盘）与临时 DB 完全一致——
首讲 0.0 → 补答 correctness 0.95 / 综合 0.38 → 终验 0.73 pass，dims 0.95/0.55/0.60/0.60，
事件 `feynman_passed` + `node_mastered`。而 NOTES §47 记录的**追问措辞也不同**
（§47："太阳系里最主要的成员是什么…" vs 日志："先不急着背名词…"）。
→ 判定：**存在两次真模型运行**，§47 记录的是较早一次，其 DB 与 stdout 已被后一次**覆盖**。
性质属"留档不可复现"而非编造；但结论不变——**留档必须每次独立命名、汇报须与留档一致**。

**F6（新增 · 评分波动，建议列产品项）**：同一份整合稿在两次真模型运行中得 **0.863 / 0.73**
（差 0.13），且 0.73 仅高出 0.7 门槛 **0.03**。含义：**同一篇讲解可能"一次过一次不过"**（阈值抖动）。
R12 已有"边缘分 → 下一轮升 think"，但终验当轮无二次确认。
**建议（待用户裁定）**：终验落边缘带（如 [threshold−0.05, threshold+0.08]）时，用 think 档**复评一次取较高分**，
或至少向用户提示"本次接近过线、评分有波动"。属体验/公平性优化，不阻塞。

## R29 · 老会话费曼键缺失 → 500（真人阻断热修 · 2026-09-10 · 架构侧）

**问题（架构侧验收探针发现，非欧拉汇报项）**：R27 在 `flow.feynman` 新增 `answers_done` /
`followup_gap` / `ledger`，费曼分支按 `f["answers_done"]` **直接取值（非 `.get`）**；
而 R27 之前落库的老会话没有这些键。`_ensure_invariants` 只在 `practice`/`feynman` **整块缺失**时
才并入 `new_flow()`，且**仅在 `resume()` 调用**（`step()` 不经过）→ 老会话走 `feynman_submit`
时 `session.py:632 KeyError: 'answers_done'` → 500（前端"会话不可用"）。

**影响（真人阻断）**：用户应用库现存会话 `s-f2decfcf.u01:a7689b7ebf`（state=learning，
R27 前落库）正是该结构——用户验收 R27 新流程的**第一个动作**（打开该会话提交完整讲解）即 500。
属"必现、恰好挡在验收路径上"的阻断级缺陷。

**架构侧热修**（`backend/app/service/session.py`）：
1. 新增模块级 `_backfill_feynman_keys(f)`：按 `new_flow()["feynman"]` **setdefault 回填缺失键**
   （不覆盖已有值）；
2. 调用点三处：`step()` 入口（**无副作用**，`step` 是真正的 choke point）、
   `_act_feynman` 与 `_act_feynman_answer` 入口、`_ensure_invariants`（resume/响应路径）。
3. 教训留档：本次首修只改了 `_ensure_invariants` → **探针仍复现**（因其只被 `resume()` 调用）；
   证明"自愈点必须落在 `step()`，不能只在 `resume()`"。

**回归测试**：`backend/tests/test_r27_legacy_session.py`——构造"老结构会话"（剔除新键）→
`feynman_submit` 200 + 定向追问 + `answers_done=0` + 账本视图下发 → 回填**已落库** →
`feynman_answer` 200 且 `answers_done=1`。修复前该用例必现 KeyError。

**给 Euler（同类缺陷系统性排查）**：
- 该类问题 = **flow schema 演进无迁移**。请审计所有"后加且用 `[]` 取值"的 flow 键
  （含 practice/feynman 子键、ledger 结构、R21 lecture_cache 等），统一收敛为
  "读会话即深度补齐默认值 + 类型校验"的单一入口（建议 `_ensure_flow_shape(flow)`），
  并补"老结构会话"参数化用例（缺键/错类型/整块缺失 三种）。
- 纪律不变：新增 flow 键必须同时提供老会话兼容路径与回归用例。

**文档同步**：本裁决；`docs/13 §3` 已登记该热修；NOTES 由 Euler 追加（§48）。

## R30 · 费曼终验边缘带复评（用户拍板）+ R28/R29 遗留收口（2026-09-10）

**背景（R28 F6）**：同一份整合稿两次真模型运行得 **0.863 / 0.73**（差 0.13），后者仅高门槛 0.03 →
**同一篇讲解可能"这次过、下次不过"**（阈值抖动）。用户拍板：**接近及格线时用更认真的档位再评一次，取较高分**。

### F6 规格（终验边缘带复评 · 唯一新增功能）

1. **触发位置**：`_act_feynman`（完整稿整体评分：首讲/终验）单轮评分完成后判定，**不新增调用点语义**。
2. **触发条件（三者同时）**：
   - 本轮综合分落在**边缘带**：`threshold − 0.05 ≤ combined ≤ threshold + 0.08`
     （以 0.7 门槛为例 = [0.65, 0.78]；常量入 `ai/tier.py`，如
     `FEYNMAN_RECHECK_LOW = 0.05` / `FEYNMAN_RECHECK_HIGH = 0.08`，便于调参）；
   - 本轮所用档位**不是 think**（fast/light 才需要复评；已经 think 过就不再复评）；
   - 本轮**尚未复评过**（每次完整稿提交**最多复评一次**，禁止循环）。
3. **复评动作**：以 **think 档**重跑 `feynman_evaluate`（同一份稿、同一 rubric、同轮语境，
   含 `previously_acknowledged`）；**取两次综合分的较高者**作为本轮结果；
   两次评分卡都写 `attempts.meta`（`recheck: {used: bool, first_combined, second_combined, taken: "first|second"}`），
   事件流追加 `{"type": "feynman_edge_recheck", "first": x, "second": y, "taken": ...}`。
4. **状态与账本**：以较优那次的评分卡并入账本（`merge_card`，仍取维度 max）；`strategy`/`strategy_reason`
   记录实际采用的那次档位；评测失败（`AiCallError`）→ 保留首次结果，不因复评失败而失败。
5. **成本纪律**：仅在边缘带触发、且每次提交最多一次 → 单轮最多 1 次额外 heavy 调用。
6. **测试（离线桩）**：桩网关返回可控两次分数 →
   ① 带内（0.68）→ 触发复评、取较高（0.75）→ pass；
   ② 带外（0.40 / 0.90）→ **不触发**；
   ③ 首次即 think → 不触发；
   ④ 复评更低（0.68 → 0.60）→ **取首次** 0.68 且不 pass；
   ⑤ 复评抛错 → 保留首次结果且不 500；
   ⑥ 断言事件与 meta 字段，且每轮复评次数 ≤1。

### 其余遗留项（用户一并点头 · 交 Euler 下批）

- **F3（已裁定）**：通过判定**维持"账本累计分（维度历轮 max）≥ 阈值"**（用户点头：符合"答对认账"），
  不做"末次稿自身须过线"的收紧；本条仅记录口径，无需改码。
- **F2**：`backend/app/service/session.py` 行尾归一化回 LF（独立提交，纯 EOL，便于分离 blame）+
  新增 `.gitattributes`（`*.py`/`*.ts`/`*.tsx text eol=lf`；docs 的 CRLF 维持现状）。
- **F4**：补答未补上后追问被清空 → 文案（前后端）统一说明"**再交一次完整讲解后，会针对该缺口再问**"。
- **F5**：evidence 校验加最短长度门槛——归一化后 **< 6 字视为无效**（按无效降级 + 标记），
  同步更新相关用例。
- **R29 引申（flow schema 演进排查）**：审计所有"后加、且用 `[]` 取值"的 flow 键，
  收敛为单一自愈入口（如 `_ensure_flow_shape(flow)`：深度补齐默认值 + 类型校验），
  并补"缺键 / 错类型 / 整块缺失"三类老结构参数化用例。
- **F1 纪律（重申）**：真模型回归必须留档且**文件名唯一、不得覆盖**（DB + stdout 路径写入 NOTES），
  汇报数字一律取自留档。

**文档同步**：本裁决；docs/13 §3 工单已同步；实现记录由 Euler 追加 NOTES §48+。

## R31 · R30 验收裁决（F6 边缘带复评 + F4/F5/F2 + R29 引申 · 2026-09-10）

**架构侧独立复跑（不采信汇报）**：
- pytest **325 passed + 2 skipped**（327 collected，exit 0；架构侧以标记计数 + exit 0 独立确认，
  与 Euler junit 计数一致；基线 308/306+2 → +19 = F6 7 + F5 2 + flow 自愈 10）；
- `npx tsc --noEmit` exit 0；`npm run build` ✓ 1.03s；content validate **ok 26/54**；
  audit 五学段 **ALL_OK=True**（环/反向前置/boss 未匹配/锚点缺失全 0）；
- git 链 4f7990b→23fc603→49e5149→f66af5f→f8c856d→d110bd9 与汇报吻合；工作树干净；
- **F2 落实核验**：`git ls-files --eol backend/app/service/session.py` = `i/lf w/lf attr/text eol=lf`；
  `.gitattributes` 无 BOM、LF、UTF-8，三条规则（`*.py`/`*.ts`/`*.tsx text eol=lf`）就位，docs 未被牵连；
- **R29 热修未回退**：`test_r27_legacy_session.py` 仍全绿（行为被 `_ensure_flow_shape` 超集覆盖）。

**代码审查确认**（逐条对 R30 规格）：
1. F6 判定与比较都在**净化后的本轮评分卡**上做（`clean_card` / `card_combined`），
   入账用 `merge_clean_card` **避免二次 ×0.5 降级**——这是本轮最容易被写错的一处，实现正确；
2. 触发三条件齐备；复评复用**同一 ctx**（同稿/同 rubric/`previously_acknowledged`）；
3. 复评抛 `AiCallError` → 保留首次结果、不 500、事件 `second=None`；
4. 仅在 `second > first` 时采用，`strategy`/`strategy_reason` 记**实际采用**那次；
   `f["last_strategy"]` 同步为采用值；`meta.recheck` 四字段完整；
5. `edge_think` 仅在**采用 FAST** 时才置（已 think 则不再标）——比要求更严谨；
6. F5 `MIN_EVIDENCE_CHARS=6` 同时约束"过短"与"不在本轮文本"，且给出区分原因的中文说明；
7. F4 前后端同措辞（`session.py:907` / `SessionPage.tsx:26`），docs/05/06/07 同步；
8. `_ensure_flow_shape` 为幂等单一入口（整块缺失→默认；缺键→补；错类型→**单键**回退；
   ledger 复用 `normalize_ledger`），调用点 4 处；`_backfill_feynman_keys` 已删但行为被覆盖。

**结论：R30 全部验收通过、放行。**

### 疑点裁决（Euler NOTES §50 五条）

1. **边缘带判定取"本轮评分卡加权分"而非"是否会因此不过线"** → ✅ 接受现状（判定口径与入账口径
   一致，更易审计）。**列为可选微优化 F6-b**：加 `first_combined < threshold` 前置条件
   （一行），即可省掉"本轮本来就会过"时的复评开销；不阻塞，随下个**功能批**做（本批之后的立心批
   不改逻辑，故不塞进去）。
2. **`recheck.used=true, second_combined=null`（复评失败）语义** → ✅ 采纳现状：
   `used` = "**已尝试**"（留成本痕迹），`taken` 表示"**被采用**"。docs/06 §2.0 已按此写明，保持。
3. **带内复评仍不过 → 仍置 `edge_think`（相邻两轮各一次 think）** → ✅ 接受：单轮 ≤1 次额外
   heavy 调用的纪律未破；最坏成本已在 meta 可见。
4. **practice 整块缺失只补默认 + 中文 409，不做 stage 一致性回退** → ✅ 判断正确：
   属状态机语义变更，超出本批授权；已留档，需要时另裁。
5. **`_ensure_flow_shape` 在 `_response` 每帧调用** → ✅ 接受（幂等、实测无性能影响）；
   flow 结构若显著变大再加短路（留档）。

### 新增留档（架构侧观察）

- **F5 权衡**：最短 6 字会"错杀"短但合法的引文（如只引"移项"二字）→ 这是刻意的：
  evidence 应为**短语级依据**而非单词；若真机反馈误伤过多，再降到 4 字（常量已集中，改一格）。
- **F6 未跑真模型** → ✅ 可接受：本批需"分数精确落带"，只有桩能稳定覆盖；
  抖动证据已由 R28 F6 留档。用户浏览器走查仍是最终验收（见 docs/13 §3）。

**下一批（用户已定）**：立心清理（文档为主 + 代码内文案/注释可改，**逻辑不动**）+ 工作目录改名
`MathFeynman` → `YanHui`；规格见 docs/15 §6/§7。

**文档同步**：本裁决；docs/13 §3 已随批更新。

## R32 · 立心（身份级去数学中心化）验收裁决 + 清理与改名执行记录（2026-09-10）

> **编号澄清**：docs/15 §7C 曾拟把本批裁决编为 R31，但 R31 已被「R30 验收裁决」占用（见上节）。
> 故**本批裁决起用 R32**；此后 docs/15 中的「R31 裁决」一律读作 R32。

**背景**：R31 指定的下一批 = 立心清理（文档为主 + 代码内文案/注释可改，**逻辑不动**）+
工作目录改名 `MathFeynman` → `YanHui`。立心三条精神基调见 docs/15 §6、README「演进与立心」。

### 1. 架构侧独立复跑（不采信汇报）

| 项 | 实测 | 与记录比对 |
|---|---|---|
| `pytest backend/tests` | **325 passed + 2 skipped / 327 collected，exit 0**（130.48s，离线） | 与 R31 基线逐位一致 ✅ |
| `content validate` | **ok，26 节点 / 54 练习** | 与 docs/13 §4 一致 ✅ |
| roadmap `audit()` 五学段 | **27 / 31 / 81 / 59 / 60；环 0 / 前向前置 0 / 锚点缺失 0 / boss 无主 0 / 内容不变式违规 0** | 与 R31 记录一致 ✅ |
| 前端 `tsc --noEmit` | exit 0 | ✅ |

**环境修复（属改名余波，非缺陷）**：`.venv` 在目录改名后重建时**漏装 dev 依赖**——`pytest` 不在环境中
（`No module named pytest`），基线不可复跑。已按 pyproject 补齐：`pytest 9.1.1` / `pytest-cov 7.1.0`
（运行时依赖 29 项本已齐全）。**记录为改名后的标准收尾步骤。**

### 2. 立心与清理验收

1. **身份级去数学中心化主体已完成**（提交 `92b6ff9`）：产品定义（README/docs/01）、**运行时 LLM 角色**
   （`ai/drafting.py` 出稿 prompt、`ai/prompts.py` ContextBlock）、包描述（`pyproject.toml`）均已去数学中心。
2. **代码内文案/注释清理（本批未提交部分）**：后端 5 文件（`ai/gateway.py`、`api/subjects.py`、
   `domain/graph.py`、`outline/generate.py`、`service/path.py`）+ 前端 5 文件
   （`ExercisePanel`、`SubjectSwitcher`、`DashboardPage`、`OutlinePage`、`SubjectsPage`）
   + docs 4（02/06/07/13），**逐条复核确认零逻辑变更** ✅。
   要点：`math preset` 硬编码文案 → 「预置学科」；guided 步骤文案去掉"设未知数/列方程"的数学专属措辞；
   `SubjectSwitcher` 的"数学"改为取学科 `label`；graph 学段错误文案补"（通用学科即所属分组非法）"。
3. **历史裁决 R1–R30 保持原样**，未改写（决策链证据口径，符合 docs/15 §7A-3）。
4. 缺陷：本批未完成「代码内全量 math-only 措辞清扫」——残留面（如 `MathInput` 组件命名、数学专属
   guided 文案、`docs/03` 图谱/总序 math-preset 标签）**列 R33 或后续清理批**，不阻塞本批验收。

### 3. 工作目录改名执行记录（`MathFeynman` → `YanHui`）

- ① 目录改名已执行；`_dsh-local/start-dsh.ps1` 的 `$Workspace` 已同步为 `D:\DeepseekHarness\YanHui`；
  仓库内**唯一**残留绝对路径是 `.runtime/EULER_TICKET_R30.md` 首行的旧路径（**该文件 git 忽略、不随批入库**）。
- ② `.venv` 已重建（`pyvenv.cfg` 指向 `D:\DeepseekHarness\YanHui\.venv`）；泄漏项见 §1（本轮已补 pytest）。
- ③ 旧库名：`backend/data/mathfeynman.db`（真实进度：user_nodes 26 / sessions 3 / attempts 31 /
  subjects 2 / concepts 113）仍在盘上。**根因**：`.env` 的 `MF_DB_PATH` 仍写旧名 → `db.py`
  `_migrate_legacy_db_path()` 的"新名不存在才迁移"前置不成立 → 迁移永不触发；
  代码默认值（`config.py`）与文档（NOTES §0）其实均已是 `backend/data/yanhui.db`。
  **处置**：`.env`（git 忽略）+ `.env.example`（入库）同步为 `yanhui.db`，迁移交给既有代码路径自动完成
  （**须停后端后重启**，避免改名时旧进程占着 WAL/SHM）——见 §4。#2。
- ④ 前端 `node_modules` / `vite` 缓存随目录搬移正常（`dist` 为 9/10 改名后产物）。
- ⑤ git 远端与镜像不受影响（`.git` 随目录搬移）。

### 4. 遗留与派工

**R33 批（交 Euler，小，纯文档/测试路径一致性 + 配置口径统一）**
1. 文档旧路径同步：`docs/02-architecture.md` 目录树中 `颜回（YanHui）/` 含全角括号，改为
   `YanHui/`；`docs/15 §7B` 的执行清单改为**已完成**并保留勘察结论（作改名手册）。
2. `.env.example` 的 `MF_DB_PATH` 由 `backend/data/yanhui.db` 保持（入库口径即新名）；
   同步 `IMPLEMENTATION_NOTES` 的库路径说明；`.env`（本地）由用户侧同步或由 Euler 在停服后改。
3. `backend/tests/conftest.py` 的 `MF_DB_PATH` 已隔离到临时根（无需改），仅复核。

**用户动作（R33 真人验收清单，沿用 R31 转载）**
- 真人浏览器走查：重开遗留会话 `s-f2decfcf.u01:a7689b7ebf`，走"首讲 → 补答 → 整合重讲"，
  确认分数可见上升、得分条 / 缺口提示 / 额度徽标正确（R29 修复后不再 500）；
- 真实 SearXNG 端到端（自托管后配 `MF_SEARCH_PROVIDER`/`MF_SEARXNG_URL`）；PDF 上传 UI；
  math 停用/重启用 UI 演示；材料可追溯重生成。

**架构侧已办（本批）**
- DSH 会话存储事故的**预防动作**：`.dsh` 全量备份（robocopy 权威比对 Files 52886 / Mismatch 0 /
  FAILED 0）、旧版 0.1.2 缓存**双改名屏蔽**（目录名 + `bin.js`→`bin.js.disabled-bak`，阻断启动器
  "探 `bin.js` 存在性"的发现路径），并以启动器自身算法验证其唯一解析到 0.1.5。属会话基础设施，
  不涉及仓库改动。
- **备份政策（用户 2026-09-10 定，长期有效）**：备份一律落 `D:\DeepseekHarness\_backups\`（不放桌面）；
  **只备份当前运行版本**（此刻 0.1.5-rc.1）的数据，**旧版（0.1.2）缓存/救援副本一律不留档**
  （格式不兼容，留存只会造成二次事故）；命名 `dsh-full-<版本>-<时间戳>`；**先复制 → 核对计数与
  大小/哈希 → 通过才删原份**；**不写 `.ps1` 脚本**，用现成工具逐步执行。
  据此，事故当天的救援副本 `projcache-backup-20260910-151100`（旧缓存、含 `.corrupted-151023` 残骸）
  **已删除**；旧版 0.1.2 的 npx 缓存（`DISABLED-1e7f6d9597241db0`，24951 文件 / 222.5 MB）
  **亦已删除**；回收站随后一并清空（302 项 / 约 4.45 GB，含肇事脚本 `rename-to-yanhui.ps1` 与旧显示名
  的 `MathFeynman验收清单.html`）——**旧版痕迹至此全部清除，不可恢复**。
  现存唯一备份 = `dsh-full-backup-20260910-153523`（52886 文件 / 723 MB，内含 0.1.5-rc.1）。
- **改名/升级类操作纪律（R32 §5 重申）**：改工作目录名 / 切 DSH 版本 / 升级 DSH **禁止同一时间窗叠加**，
  且动手前先备份。

### 5. 流程纪律新增（改名/升级类操作）

**改名或切换 DSH 版本之前，必须先冻结并备份**（本批教训）：① 停服务；② `.dsh` 全量副本；
③ 再改名/换版本；④ 改名后同步"文件内声明的路径"（`cwd`/`identity.cwd`）与启动脚本；
⑤ 复跑基线。**三项高危操作（改工作目录名 / 切 DSH 版本 / 升级 DSH）禁止在同一时间窗内叠加。**

**结论：立心与清理**（文档 + 代码内文案/注释，逻辑不动）**验收通过、放行**；
改名执行记录如上，遗留项按 §4 派工。

## R33 · R33 批验收裁决（onboarding + 文档尾巴 + 库路径归一 · 2026-09-10）

**架构侧独立复跑（不采信汇报）**：pytest **325 passed + 2 skipped / 327 collected，exit 0**
（121.6s，离线，与 §2 基线逐位一致）；`content validate` **ok 26/54**；roadmap `audit()` 五学段
**27/31/81/59/60**，`cycles`/`prereq_missing`/`anchors_missing`/`content_prereq_violations`/
`boss_unmatched` **全 0**（非零项均为 `covered/pending/topic_runs` 信息项）；`npx tsc --noEmit` exit 0；
提交链 `51c6a62 → b90c160 → 7eec2fc → c9f61ba → 2c08a57 → 79c18a6` 与汇报吻合，工作树干净；
本批 diff 仅 4 文件（NOTES / docs/02 / docs/13 / docs/15），**零代码改动** → 测试数字不变有解释力。

**真实库校验（架构侧只读复核）**：`backend/data/yanhui.db` `integrity_check=ok`，
六项计数 **user_nodes 26 / sessions 3 / attempts 31 / subjects 2 / concepts 113 / reviews 0**
与迁移前逐位一致；两学科（math + 行星科学）与遗留会话 `s-f2decfcf.u01:a7689b7ebf` 均在库 →
**迁移未丢任何数据**。旧三件套已移出 `backend/data/`（备份于
`_backups\yanhui-db-20260910-160212\`，含误建空库残骸子目录）。

### 1. 结论：通过、放行

Euler 自证的四项基线全部由架构侧独立复现；文档改动逐行复核为**写实**（目录树按实测补齐、
删除 3 个不存在的组件名、历史叙述保留）；`_backups\` 下的库备份与"误建空库证据"均实存。

### 2. 新增根因（比 Euler 报告更精确）与唯一安全修法

- **第一层**（R32 §3 已记）：`.env` 写旧名 → `db.py` 的迁移前置不成立。
- **第二层**（Euler 本批发现，属实）：`config.py` 用 `load_dotenv()`（python-dotenv **默认不覆盖**
  已存在的环境变量），而当前 DSH 进程环境里残留**进程级** `MF_DB_PATH=backend/data/mathfeynman.db`
  → **只改 `.env` 永不生效**；重启即静默新建空库。
- **第三层（架构侧本次勘察所得，本批未记）**：真正让残留得以生效的入口是
  **`scripts/dev.ps1`** —— 它 `Start-Process` 启动 uvicorn 时**从不设置 `MF_DB_PATH`**（第 34–39 行），
  因此后端**继承调用终端的环境变量**。后果：从"带残留的终端"（DSH 内、或任何旧终端）跑
  `dev.ps1` → 又指回旧库名、再建空库。**这是用户最可能踩到的那一步。**

**裁决：唯一安全修法 = 在 `scripts/dev.ps1` 显式设定 `MF_DB_PATH`（定值指向
`backend/data/yanhui.db`），不采用 `load_dotenv(override=True)`。理由（架构侧隔离实验证据）**：

```
环境变量(残留)=from_process_env
load_dotenv()          -> from_process_env    （现状：.env 被压住）
load_dotenv(override)  -> from_dotenv_file    （能修好——但会砸掉测试隔离）
```

`backend/tests/conftest.py` **先**设 `os.environ["MF_DB_PATH"]=<临时库>`（L54）、**后**才
`from app.main import app`（L79）。一旦 app 侧改 `override=True`，`.env` 的
`backend/data/yanhui.db` 会**反过来覆盖临时库 → 测试直接写真实库**。故该修法**禁止**。
`dev.ps1` 显式设定不影响测试（测试不经过该脚本）。附带要求：脚本内加一行读回校验，
启动前若发现生效值与目标不一致则**中文报错中止**（把"悄悄建空库"变成"响亮失败"）。

### 3. 疑点裁决（Euler 六条）

1. **是否 `load_dotenv(override=True)` / dev.ps1 显式设值** → **禁止前者**（见 §2）；
   **采纳后者**并入 R34（含读回校验）。
2. **`.gitignore` 是 GBK、中文注释乱码** → **确认属实**（架构侧字节级复核：无 BOM、UTF-8 严格解码
   失败；GBK 解出可读中文，但部分行是 UTF-8/GBK 混杂的二次乱码）。**列入 R34 清理**：重写为
   UTF-8 无 BOM、注释恢复为可读中文。属配置文件、非逻辑，改后 `git check-ignore` 复核。
3. **NOTES §51「库路径遗留」已过时** → **保留原文不改写**（它是架构侧写作当时的时点记录，
   与"历史裁决不改写"同口径）；已在该段**上方追加**"R33 已处置，本段为时点记录"标注（本次架构侧提交）。
4. **提交 `51c6a62` 消息只标 §52、实际含 docs/02** → **接受**，不 rebase、不改历史
   （未推送；"提交正文与验收正文"不一致已主动披露，信息披露比历史洁净更有价值）。
5. **旧库备份 `mathfeynman.db.bak-20260908-220309`**（224 KB，9/8） → **暂留**（见 §4 用户动作）；
   它是 9/8 的旧快照、非本次迁移产物，与"旧版不留档"政策无冲突但已无用途。
6. **`stray-from-misconfigured-restart\`（误建空库证据）** → **暂留**至本轮验收结束（它是第二层根因的
   实证），R34 收尾时随用户确认删除。

### 4. 用户动作（唯一未闭项 = 真人验收）

- 服务已就绪：后端 8000 / 前端 5173（Euler 冒烟：`/api/health`、`/api/dashboard`、`/api/subjects`、
  `/api/selfextend/status`、`/api/campaign`、前端 `/` 与同源 `5173/api/health` 均 200）。
- **验收清单见 NOTES §55 / 工单任务 C**：核心是**费曼 v3 混合制**（R27–R31 这套从未真人测过）——
  遗留会话 `s-f2decfcf.u01:a7689b7ebf` 走「首讲 → 补答 → 整合重讲」，看**答追问后分数是否可见上升**、
  得分条 / 缺口提示 / 额度徽标是否正确、主副双提交入口是否清晰；另含 F6 边缘带横幅、真实 SearXNG、
  PDF 上传、math 停用/重启用、材料可追溯重生成。
- `_backups\` 下两份遗留（旧库 .bak 与 stray 空库证据）确认后删除。

**文档同步**：本裁决；docs/13 §3/§4、docs/15 §3 已由 Euler 随批同步；NOTES §52–§56 为本批实现记录、
§51 增时点标注；R34 工单 `.runtime/EULER_TICKET_R34.md`。

## R35 · 可答性（Answerability）：所有学科的出题前置条件（用户拍板 · 2026-09-10）

> **来源**：用户真人走查行星科学时当场发现——"讲解里只讲了类木行星**整类**体积大，
> 题目却问**哪颗**体积最大；我零基础怎么答？"用户定性："这是产品级的地基问题，所有学科都要考虑，
> 包括以后加入的。"**严格度由用户拍板：严格 + 允许挑战题存在（须单独生成、可点、可取消、可放弃、极高自由度）。**

### 1. 问题定义（三层根因）

1. **约束错位**：系统真正强制约束的只有**讲**（概念白名单：不许多讲新概念）；
   **问**（练习 / 费曼任务 / socratic / 运行时小思考）**完全不受约束** —— 白名单防得住"讲超纲"，
   防不住"问超纲"。
2. **类别错误：把"关于世界的问题"当成"关于本课的问题"**。两者必须分开：
   - **提问内容**："讲解里说类木行星的体积怎么样？" → 复述即可，零基础可答 ✅
   - **提问世界**："太阳系**体积最大**的行星是哪颗？" → 这是**尚未教过的外部事实**，
     被伪装成练习题 ❌（用户命中的原例）
   - 更隐蔽的一类：**层级错配**——讲解给了"类木行星（整类）体积大"，
     题目却要求"对**个体**排序/比较"（如"哪颗最大""类地四颗的远近关系"）。
     这**不是**从已述事实能推出的，除非讲解明确给出个体的比较关系。
3. **生成器没有"学生见过什么"的模型**：`feynman_followup` 虽已按 `unmet_gaps` 定向，
   但看不到"本单元到底教了哪几句"；`explain_node` 生成"🤔 引导确认"时，prompt 只要求
   "学生应能自己回答的检查问题"，**没有任何'只能问已讲过的'约束**。
   当 `prereqs` 为空（第一单元）时，"它与你学过的内容有什么联系"这类问题**在法律上无解**。

### 2. 原则（R35 的核心，一句话）

> **任何向学习者提出的问题（练习 / 费曼任务 / socratic / 🤔 小思考 / 追问）都必须可从"系统已经
> 讲给他的话"得出**：要么是**复述已述事实**，要么是**由 ≥2 条已述事实经明确推理规则推出**。
> 否则该问题**不许出**。

配套两条前提：

- **零基础假设**：没教过的一律认为学习者不会（不假设常识、不假设课外知识）；
- **已教集合 = 本单元已述事实 ∪ 前置单元已述事实**（且前置必须已掌握）。
  **`prereqs` 为空时，只有本单元自己讲的内容算数。**

### 3. 规格（交 Euler）

**S1 · 声明式知识包（schema 增补，`content/schemas.py`）**
- `taught_facts: list[{id, text}]`：本单元**显式陈述**的全部事实/关系句（封闭集合）；
- `derivable: list[{conclusion, premises[fact_id], rule}]`：本单元允许的**推理**——
  结论、所依据的事实 id、以及所用推理规则（普适逻辑如分类/蕴含/排序传递，或本单元显式教过的规则）。
- **判定基准**：出题/追问只能引用 `taught_facts` ∪ 前置单元的 `taught_facts`；推理只能走 `derivable`。

**S2 · 引文纪律（从"评分"扩展到"出题"）**
- 每道**核心题**、每个 socratic 主题、每条运行时 🤔 小思考、每次追问，都必须携带 **`basis`**：
  引用的 `taught_facts` id + **讲解原文引文**（服务端做**包含校验**，沿用既有 evidence 归一化口径与
  ≥6 字最短门槛）；推理题另需 `premises` 与 `rule`。
- **校验失败 → 该问题不得入库 / 不得下发**（自动生成时重试；重试仍失败则**丢弃该题**，不许硬塞）。
- 这是既有"evidence 必须逐字出自本轮文本"的**同一把尺子**，从 LLM 评分扩展到题目生成。

**S3 · 挑战题（用户定：单独生成、可点、可取消、可放弃、极高自由度）**
- 题目分池：**核心题池（计入掌握与费曼）** 与 **挑战题池（完全不上算）**；
- 挑战题**永不出现在默认流程里**，「挑战一下」按钮由用户主动触发、**须单独调模型生成**；
- 单题 UX：**可点**（开始作答）·**可取消**（放弃本次、直接回到讲解/下一题）·**可放弃**（
  明确"这题我不会/我不感兴趣"，**无任何后果**）；**不设额度、不计轮次、不影响任何进度**；
- 必须**显式标注**"挑战题：需要讲解之外的知识，答不出不影响任何进度"；
- 挑战题的作答与评分：**记入复盘**，但**绝不并入费曼账本**、**绝不参与 mastery 判定**、
  **绝不消耗**整体稿/补答额度。

**S4 · 追问纪律（R27 补强）**
- 追问**必须先逐字引用学生刚说过的话**，并指出"这句话缺了什么"；
- 学生若没提供可引用的实质内容（如只写"我不知道"）→ **禁止硬造发散题**，
  返回 `reteach`（退回讲解补讲），而不是逼他"思考"；
- socratic 模板（"举实例 / 边界 / 与学过的内容联系"）**不得作为默认兜底**下发：
  它们必须先在 `taught_facts/derivable` 里找到依据，否则不下发。
  其中"与**你学过的**内容联系"在 `prereqs` 为空时必须**禁止**。

**S5 · 自动质检（护栏）**
- `pipeline.validate_candidate` 增一道**可答性检查**：不合规 → 重生成，仍不合规 → 该题丢弃；
- **可复现的审计方法（本裁决留档）**：用"零基础学生模型"（只给讲解原文 + 严格禁令）
  逐题判定 `answerable`；实测脚本见 NOTES 对应节，任何批次的验收都可复跑。
- 与既有 guardrails 同一入口：可答性问题率进"纠错/熔断"口径。

**S6 · 运行时 🤔 小思考与教学内容对齐**
- `explain_node` 的 `asked_to_confirm` 生成必须在 prompt 里注入**讲解正文 + 白名单 + 引文要求**：
  每条小思考必须能在讲解原文里找到依据（校验同上）。

**S7 · 学习者侧反馈入口**
- 每道题旁提供「**这题我没法答（讲解里没有）**」按钮；点击 → 记录一次"可答性投诉"、
  **该题不计入失败/不扣分**、并进护栏统计（作为"讲解太空/出题越界"的信号）。

**S8 · 适应范围（用户原话：所有学科，当下的与以后加入的）**
- **对所有 subject 生效**：preset（math）与 custom、内容源 `ai|import|web|mixed` **一律**；
- 导入类内容**同样**需要 `taught_facts` 声明（可由 AI 从导入材料提取，但**必须过校验**）；
- 数学允许"更为发散"的思考题（用户已说明），但**仍须遵循 S6/S7**：
  发散不等于可以问没教过的东西；数学的发散题**归入挑战题池**（S3）。

### 4. 取舍与代价（用户已知并接受）

- 生成变严 → **重试与失败变多、token 成本上升**；与"北极星=零人工审核 + 省 token"存在张力，
  用户已表态接受（"否则学生会被反复卡在没学过的东西上，这正是我踩的坑"）。
- **副产品（正面）**：这把尺子同时是**内容质量质检器**——连一道合法题都出不出来，
  说明**这份讲解本身太空**，正是当前最该被发现的毛病（auto 内容首当其冲）。
- `taught_facts` 会**让讲解与题目真正同源**：R35 之后，"讲什么"与"问什么"第一次被同一份声明绑定。

### 5. 执行（R35a / R35b 两步）

- **R35a（先行，已出问题内容）**：行星科学 u01/u04 —— 把"木星体积最大"等**事实补进讲解**，
  或**删掉越界题**（二选一，以"讲解能否干净地补上"为准）；补 `taught_facts`；修 3 条模板追问；
  u01/u04 的 `worked_examples` 为空，需补例题（"给例子"是学习者最需要的支撑）。
- **R35b（引擎）**：S1–S8 全量落地 + 全库 27 节点体检 + 验收（可答性审计必须 0 不可答）。

### 6. 待架构侧复核 / 用户验收

- 本裁决为**产品级前置条件**，S1–S8 属架构决策，实现细节交 Euler（工单
  `.runtime/EULER_TICKET_R35.md`）；R35a 完成后由用户复看 u01/u04；R35b 完成后按 S5 审计复跑。

### 7. 实测审计结论（架构侧，2026-09-10 · 真模型）

方法：**零基础学生模型**——只给讲解原文 + 严格禁令（不许用课外知识、不许猜），逐题判 `answerable`。

| 单元 | 受检 | ❌ 不可答 | 真越界项 |
|---|---|---|---|
| s-f2decfcf.u01 | 11 | 4 | `f3`「体积最大的行星」——讲解从未比较任何两颗行星的体积（**用户命中原例**） |
| s-f2decfcf.u04 | 10 | 4 | `c2`（难度3）正解含"**统计涨落**"——该概念讲解里从未出现，只在选项里第一次冒出 |
| **合计** | **21** | **8** | socratic 三连占 6 项：u01/u04 各 3 条全灭（指代不明 + u01 `prereqs` 为空） |

**反向发现（重要）**：运行时生成的 **🤔 小思考 6/6 全部可答**，且质量明显好于 socratic 模板
（u01："请按离太阳由近到远说出八大行星…"；u04："举一个生活中的例子说明风/水/冰如何改变表面"）。
→ **病根不是"模型不会出题"，而是"没人告诉它学生只见过哪几句"。** 这直接支持 S1/S2/S6 的修法：
把**已教事实**显式化并注入生成 prompt，比事后过滤更根本。

**审计自身的教训（留档）**：第一版脚本**没把选择题的 `options` 喂给"学生"**，导致它回"题目没给选项、
无法判断"——把 1 道合法题误判为不可答（9 → 8）。**凡用模型做审计，必须把作答所需的全部材料一并给出**，
否则量到的是自己的漏洞。该坑已写入工单 §5，审计脚本要求入库长期保留。

## R36 · 大纲起草读材料 + 「由易到难·零基础读一本书」通用化（用户指令 · 2026-09-10）

### 0. R34-fin 验收结论：**通过**

架构侧独立复跑（不采信汇报）：pytest **325 passed + 2 skipped**（111.5s，exit 0）、
`content validate` **ok 25/48**、audit 五学段 **27/31/81/59/60** 错误项全 0、`tsc --noEmit` exit 0、
提交链 `e09f6d7 → a92d2e7 → 8ce8582` 吻合、工作树干净；DB 计数与汇报逐位一致
（nodes 28 = 25 enabled + 3 disabled(走查残影)、user_nodes 25 全 locked、ai_logs 42）。
**批准确认**；两处遗留（见 §3）随本批一并处理。

### 1. 决策一：**大纲起草必须能读材料**（用户原话："起草大纲那个当然也要读材料啊"）

**问题（架构侧核实）**：现链路是「先起草大纲（只吃 `brief`）→ 后生成单元内容（此时才注入材料）」，
顺序倒置——用户上传一本书，**大纲阶段完全看不到它**，产出的纲可能与书无关。

**裁决**：`POST /subjects/{sid}/outline/draft` **必须**注入该学科的引用材料。
**材料是可选输入**：无材料 → 退化为现状（`brief`/启发式），**不得报错**。

**规格（D1–D4）**
- **D1 注入**：起草 prompt 注入 `materials_summaries()`（`outline/materials.py`，**既有函数**）——
  标题 + 来源 + 摘要；材料超量时按"分节摘要 + 章节骨架"降级（见 D4 预算）。
- **D2 逐单元溯源**：AI 起草的每个单元**必须带 `materials: [{title, section}]`**（该单元的骨架来自材料的哪一节）；
  服务端校验：引用的材料**必须真实存在于该学科引用库**，否则该单元**驳回重生成**。
- **D3 大纲层溯源**：采纳时记录 `source_materials: [material_id…]`，并在大纲页显示"本大纲依据的材料"。
- **D4 预算**：注入**受 `LLM_MAX_TOKENS_PER_DAY` 保护**；材料总注入量设上限（建议按字符截断 + 分节摘要），
  **不允许**"整本书塞进一次调用"。
- **D5 通用**：与学科无关（不因 math 是 preset 而豁免；preset 的 outline 由 roadmap 派生，此路径不适用，
  但**自定义学科一律适用**）。

### 2. 决策二：**"由易到难 · 零基础读一本书学会一个学科"作为通用默认**（用户再次强调）

**既有依据（并非新立）**：`docs/01 §1`（用户初中辍学 → 捡拾/学习/进阶）、`docs/01 §4`（从小学水平起步）、
`docs/12 §1`（"从小学一路学到 AI 进阶结束"）。**本裁决把它从"数学愿景"提升为所有学科的通用默认。**

**规格（P1–P5）**
- **P1 骨架**：每份大纲的单元顺序**必须构成一条由易到难的学习路径**——
  `prereqs` 有向无环（校验器**已有**环检测）+ **顺序与难度一致**（先修单元的 `difficulty` 不得高于后继）。
- **P2 零基础起点**：**第一个单元（`prereqs` 为空）必须能被完全零基础者学会**——
  与 R35 的零基础假设**同源**：首单元不得假定任何前置概念。
- **P3 分组即关卡**：`group`（关卡组/主题组）用于表达"章/阶段"的推进层次；组内先易后难。
- **P4 每一跳可答**：单元内容的讲解与题目遵循 R35；**难度提升只能靠"已教事实的累积"**，
  不得靠"默认学习者知道"。
- **P5 进度语义**：不新增引擎——沿用现有掌握度 + FSRS；"学完一本书"＝沿大纲顺序推进到末单元。

### 3. 两处遗留（随本批修）

- **L1 仪表盘停用横幅不显示（真缺陷，Euler 发现，架构侧已核实）**：
  `frontend/src/pages/DashboardPage.tsx:44` 取 `/subjects`（**默认不含已移除学科**）→ L50 `find("math")`
  得 `undefined` → L51 回退 `true` → L95 的横幅永不渲染。
  **修法（二选一，Euler 定）**：① 改取 `/subjects?include_removed=1`；② 或改由 dashboard 响应直接给出
  "预置学科是否停用"（**架构侧倾向 ②**，避免前端为看一个布尔值去拉全量学科列表）。
- **L2 走查在真实库留痕**：`nodes` 多 3 行 `s-r34walk.*`（enabled=0）+ `user_nodes` 25 行（全 locked）。
  **裁决：清理**（走查产物不应留在用户真实库；清法按 NOTES §57.2e 已写好的 SQL，**执行前先备份库**）。

### 4. 派工

R36 交 Euler（工单 `.runtime/EULER_TICKET_R36.md`），与 R35 **合批执行但分两次汇报**：
先 L1+L2（极小，清现场）→ 再 D1–D5 + P1–P5（机制）。
**R35a 的作业对象重新指定**：行星科学已硬删，改用**用户即将新建的 PDF 学科**做端到端靶子
（`content/stages/` 不得回灌已删内容）。

### 5. R36 任务 L 验收（2026-09-10 · 架构侧独立复跑）

**结论：L 批通过，放行 D/P。**

| 项 | 架构侧实测 | Euler |
|---|---|---|
| pytest | **326 passed + 2 skipped，114.8s，exit 0**（= 基线 325+2，+1 为新用例） | 一致 |
| `tsc --noEmit` | exit 0 | 一致 |
| 活体 `/api/dashboard` | `preset_subject = {"id":"math","label":"数学","enabled":false}` | 一致 |
| 库态 | `nodes=25`、`enabled=0` **为空**（`s-r34walk` 已清）、`edges=28`、`user_nodes=0`、 `ai_logs=38`（走查 4 行已清）、`integrity ok` | 一致 |
| 备份 | `_backups\yanhui-r36-before-clean-20260910-172524\` 三件套在 | 一致 |

**L1 代码审查**：后端按 `kind=="preset"` 查（**不硬编码 math**，符合通用性第 10 条）、
停用态**如实下发**（不加启用过滤）；前端改 `presetOff` 驱动、**去掉第 4 个请求**、label 取自响应。
**采纳方案②正确**：横幅问的是"预置学科生命周期状态"，用 `/subjects`（契约=启用中的学科）反推属**契约误用**
——这正是缺陷根因，直出后该类"推断失配"风险结构性消失。**并要求把旧缺陷成因写进断言**（已做）。

### 6. 疑点裁决：`user_nodes=25` 是**引擎语义，不是残留**（Euler 发现，架构侧复核确认）

**核实**：`service/library.py::sync_content` 末尾对每个 user 调 `recompute_states`
（`progress.py:85-88`），后者对**图中每个节点** `db.add(UserNode(..., state=AVAILABLE|LOCKED))`。
故后端**每次启动**都会为全部 enabled 节点建默认行 → `user_nodes=0` 只是**清完那一瞬**的瞬态。

**裁决：接受现状，不改引擎。** 理由：① `docs/03 §4`/`docs/06 §3` 本就把 `user_nodes` 定义为
"按节点维护状态"的**物化表**，启动重算是**幂等**的；② 读路径（`state_map`）已能按需计算，
改成"按需建行"属**引擎语义变更**，收益（省 25 行）与代价（写路径分支、聚合口径、回归面）不成比例；
③ 它**不污染真实数据**（全 `LOCKED`、无 `mastered`），也不影响任何显示（dashboard/graph 仍空）。

**但记两条纪律**：
- **验收目标更正**：L2 的目标**不是** `user_nodes=0`（不可持久），而是
  **"无走查产物"** = `enabled=0` 的 `s-r34walk.*` 为 0、走查 `ai_logs` 已清、计数与 R34-fin 基线可比。
  已同步进 R36 工单，**后续批次勿再把 `user_nodes=0` 当验收项**。
- **不许**为凑"0"而反复清库（那是与引擎语义对抗）；若将来真要按需建行，**另开裁决**。

### 7. R36 任务 D+P 验收（2026-09-10 · 架构侧独立复跑）

**结论：D/P 批通过，R36 全部关闭。**

| 项 | 架构侧实测 | Euler |
|---|---|---|
| pytest | **341 passed + 2 skipped，115.1s，exit 0**（328→343 collected，+15 新用例） | 一致 |
| `content validate` | **ok 25/48** | 一致 |
| `tsc --noEmit` | exit 0 | 一致 |
| 冒烟复原 | `content/subjects` 仅 math、`s-r36smoke` 行数 **0/0** | 一致 |
| 提交链 | `adc0b89 → ae2c8f7 → 6b589b7 → 3bf1ca8 → b292c74` | 一致 |

**关键实现审查**：
- **`content/citations.py`（第 3 项复用要求达成）**：引文纪律**单一实现**（`normalize` / `is_valid` /
  `invalid_reason` / `check`，`MIN_QUOTE_CHARS=6` 与 R30 F5 同值），`feynman_ledger` 已**委托**且语义不变，
  R35 的 `basis` 可直接调用 → **不许再写第二份包含校验**。
- **P1 校验器**：只比对**同大纲内**的前置（`index.get(p)`；内容节点/跨文件引用跳过），并**豁免
  `source=="roadmap"`** → 判据偏**宽松**（只会漏检、不会误拒），方向正确。
- **D3 反查不信客户端**：采纳时按 `materials[].title` 服务端反查 `material_id`，引用不存在的材料→中文 422。
- **前端**：大纲页新增「本大纲依据的材料」横幅 + 逐单元「依据材料」行，且起草区明示"会读上方引用材料"。

### 8. 本批最重的发现（值得单独立纪律）：**活体冒烟抓到"静默失效"**

Euler 用**真模型**跑「建临时学科 → 上传材料 → 起草 → 采纳 → 硬删」，第一次发现
**每个单元 `materials=[]`、`source_materials=[]`**——模型即使给了引用也到不了服务端。
**根因**：`ai/calls.py::OutlineDraftUnit` **未声明 `materials`**，而 `provider.chat_json` 用
`model_validate` 校验输出，**pydantic 默认丢弃未声明字段** → 整条溯源链**静默失效**。
**假 provider 的单测天然测不出**：测试直接喂 dict，**绕过了 schema**。

**裁决**：**立为纪律**——**"新增 AI 输出字段必须三处同改：schema 声明 + prompt 说明 + 一条 schema 往返用例"**。
（本轮已是同类问题第 N 次：R29 老会话 flow 键缺失、R30 F5 evidence 校验、本次 schema 丢字段 ——
**凡"模型输出 → 服务端"的字段，都必须有一条端到端往返断言**。）

### 9. 疑点裁决（Euler 四条）

1. **math 15 处难度倒置 → 是否治理数据？**
   **架构侧独立复算 = 12 处**（primary 4 / middle 1 / high 1 / college 2 / ai 4；按校验器同口径，
   即只数**同文件内**前置）。Euler 报 15 应为**更宽口径**（含跨学段/内容节点引用）。**差异不影响正确性**
   ——校验器只会漏检、不会误拒。
   **裁决：R36 阶段豁免 `source=="roadmap"` 成立**，理由三条：① **学习顺序由总序（R18）决定，不是由
   `difficulty` 决定**——`difficulty` 只影响出稿档位（1/2→fast、3→think），故这些倒置**不产生"先学难后学易"**，
   只是"档位选得不够准"；② roadmap 是**人工治理资产**，不该被起草校验器反向重塑；③ 改 258 单元数据会
   牵连 audit 与既有基于内容的测试，**风险 > 收益**。
   **登记为数据治理项**（调标签使之一致，低风险），**不阻塞任何事**；与 §58-9 同一条目。
2. **P4 机器校验待 R35** → **确认**，R35b 收尾项，发 R35 工单时**点名**。
3. **材料注入只做"分节摘要"（每节 ≤400 字开头）** → **接受现状**，登记为**可选增强**：
   大部头书籍注入的是"每节开头若干字"，可能偏薄。`MF_OUTLINE_MATERIAL_MAX_CHARS=6000` 可调；
   若用户实测觉得大纲仍与书脱节，**再加一次轻模型语义摘要**（成本上升，届时另裁）。
   **裁决理由**：先让用户实测，用体验决定是否付这份成本（与 R35"先证据后机制"同一方法论）。
4. **AI 输出 schema 与 prompt 字段一致性纪律** → **见 §8，已升格为纪律**。

### 10. R35 必须"长在旧机制上"（用户要求：**所有功能有机融合，不许自相矛盾**）

**用户原话**："不要忘了一定能让我程序所有功能有机融合在一起，不要自己打自己有任何矛盾"。
**裁决：R35 的所有新增件必须挂在既有件上**，逐条约束如下（**实现即验收项**）：

| R35 新增 | **必须复用**的既有机制（禁新建平行机制） |
|---|---|
| `taught_facts`（声明式知识包） | **扩展既有概念层** `concepts` 表（`subject_id/concept_id/label/aliases_json`）——它是**概念白名单的现成注册表**；`taught_facts` 是"概念 + 事实句"的加厚，**不是第二套概念系统** |
| 前置知识 = 已掌握的前置单元 | **复用概念层 `user_concepts`（掌握证据）**，不要另造"已学事实表" |
| S2 `basis` 引文校验 | **复用 `content/citations.py`**（R36 已收敛，`MIN_QUOTE_CHARS=6`）——**禁止第二份包含校验** |
| S3 挑战题 | **复用现有练习/判题/复盘链路**；挑战题池只是**标记位**，不新建题目体系；**不得**触碰费曼账本与额度（R27 机制） |
| S7「这题我没法答」 | **复用 `feedback` 表**（已有 `kind` + `exercise_id` + `status/result`）→ 新增一种 `kind`，**不新建表** |
| S5 可答性质检 | **接既有 `service/guardrails.py`**（`TRIP_RATIO=0.3` 熔断管道），**不另立阈值体系** |
| S6 🤔 小思考约束 | **复用 `ai/prompts.py::context_block` 的注入范式**（`[教学内容真源]` 已有），**不另写一套 prompt 组装** |
| 对用户的解释文案 | **复用既有中文错误口径**（`api/errors_zh.py`，中文叙事已在 R20 确立） |
| 复习（FSRS） | **复习只考已教事实**——与 R35 同源，属本裁决的推论，**不新增引擎** |

**三条"不许自相矛盾"的红线**：
1. **不许出现两套"已教/已会"判定**：`taught_facts` 与既有 `core_concepts`/概念层必须**同源同表**，
   否则"大纲说教过 / 出题说没教过"会互相打架。
2. **不许多头记录学习者反馈**：纠错反馈（`feedback.py`）、费曼复盘（`feynman-history`）、
   可答性投诉（S7）三者**共享存储、语义标注清晰**，**不得**各自建表或互相覆盖。
3. **不许让挑战题污染任何既有语义**：挑战题作答**不得**进费曼账本、不得参与 mastery、
   不得消耗整体稿/补答额度、不得计入 `user_nodes` 掌握统计（仅记复盘）。

**验收即一致性自检**：实现完成后，出一张"**融合对照表**"（每条新增件 → 复用点 → 一句断言/用例），
**任一新增件找不到复用点，必须说明为什么必须新建**（默认答案是"不新建"）。

### 11. R35a（生成端接入）验收裁决（2026-09-10）

**结论：机制部分通过；证据部分按 Euler 自述"待跑"，据实分开记 —— 证据产出后另裁。**

架构侧独立复跑（不采信汇报）：pytest **349 passed + 2 skipped，118.5s，exit 0**
（343→351 collected，**+8 新用例，既有 343 条未改**）、`content validate` **ok 25/48**、
audit **27/31/81/59/60**、`tsc --noEmit` exit 0；提交链 `f9e68c8 → 8b0fe8a → 947ccb3` 吻合；
**探针污染已清干净**（`content/subjects` 仅 math、`git ls-files` 无 `r35probe`、库内 0 行、integrity ok）。

**代码审查**：`content/answerability.py`（186 行）接口清晰——`clean_facts`（**事实句必须逐字出自讲解**，
复用 `content/citations.py` 同一把尺子）/ `clean_derivable`（前提须为已声明事实 id + 非空规则）/
`check_basis`（**推理题须 ≥2 前提 + rule、且落在本单元 `derivable` 内**）/ `gate_node`（**逐条丢弃 +
中文原因**，不整份失败）。**删掉了硬编码的三条 socratic 模板套话**——正是审计判死的那三条 ✅。
**R36 §8 接线纪律已遵守**（`CALL_UNIT_CONTENT` 输出 schema 同步声明新字段 + 往返用例）。

**对 Euler 三条疑点的裁决**

1. **`taught_facts` 是否要落 `concepts` 表（融合红线①）** → **不加 `concepts.facts_json`；
   `taught_facts` 保持节点本地**。理由：`concepts` 是**概念注册表**、`user_concepts` 是**掌握证据**，
   把"事实句"灌进掌握证据表**会污染等价判定**（Euler 的直觉正确）。
   **真正满足红线①的做法**：给 `TaughtFact` 加**可选 `concept_id`**（指向既有 `concepts` 注册表做**归一化**
   ——数学那 83 条标签正是干这个的），于是"**讲过的概念**"与"**出题考的概念**"共用同一套归一化 id，
   而"**这句事实**"仍只在节点内。若将来需要跨学科复用事实，再按 `outline` 概念层映射扩展，**留到那时**。
   **同时补一条（R35b）**：把本单元的 `taught_facts[].concept_id` 与 `concepts` 注册表**校验一致**
   （不得引用未注册概念）。
2. **数学/roadmap 参数化模板题的 `basis` 口径** → 采用 **(a)+(c)**：
   - **(a) 模板级 `basis`**：模板题的"已述事实" = 该节点讲解里**支撑该模板的那条规则句**（引文即规则句）；
     参数化生成**不产生新知识**，故**不解到每道渲染题**；`check` 校验"模板 `basis.quote` 逐字出自本节点讲解"。
   - **(c) 数学路径降优先级**：math preset 已受 R18 总序 + `roadmap.pipeline.validate_candidate`（sympy 验算）
     治理，**本批验收不要求打通**；R35b 做到"**模板级 `basis`**"即可，不必逐题。
   - **(b) 豁免**：**仅用于**"模板渲染确实不引入语义步"的已证明情形，**默认不用**。
3. **`audit_answerability.py` 是否需要 CI 门槛** → **不随常规 CI 跑**：它与 `test_live_ai`/`test_phase_c_live`
   同属**真模型冒烟**（需网络、费 token、非确定性），必须 `MF_ALLOW_LIVE_AI=1` 手动触发。
   **手动门槛（写进 docs/13 §4）**：① R35b 每次**改动生成器后**必须手动跑一轮全库审计；
   ② 上线/发版前跑；③ 日常 CI 只跑**离线结构性校验**（新增的 `answerability` 单测 + `content validate`）。
   文件名不带 `test_` 前缀（不被 pytest 收集）是**正确**的，请在文件 docstring 里写明"这是工具不是测试"。

**关于 math 难度倒置 15 vs 12（口径澄清已确认）**：Euler 的 15 = 12 同文件内 + **3 条跨学段边**
（`college.c16←high.h47`、`college.c44←high.h06`、`ai.a11←college.c20`）；校验器只比对同文件内前置 →
**只漏检、不误拒**，非缺陷。**R36 §9① 的豁免裁决不变**；3 条跨学段项补入数据治理清单。

**纪律记功**：Euler **主动自曝**探针污染真实内容库并立规（"调试脚本必须同时隔离 `MF_CONTENT_ROOT`
与 `MF_DB_PATH`；提交前查 `content/` 产物"）——**这是正确行为，记一笔**。补充要求：**任何"写 content/ 或
真实库"的脚本，除非是授权的生成流水线（`outline/generate.py` / `content/pipeline.py`），一律用临时根 +
临时库运行**。

### 12. R35b-P0 验收 + **模板题语义缺陷**（架构侧独立复现 · 2026-09-10）

**P0（S6 🤔 小思考对齐 + S7 可答性投诉）验收：通过。**
架构侧独立复跑：pytest **358 passed + 2 skipped**（360 collected，+9 用例）、`content validate` **25/48**、
audit 全绿、`tsc` exit 0。代码与复用点符合 §10 融合约束（S6 复用 `context_block`；
**S7 复用 `feedback` 表加 `kind="answerability"`、不建表**；裁定 1 的 `concept_id` 指向既有注册表）。

### ⚠️ 重大发现：**模板题的"标准答案"与题面/条件自相矛盾**（Euler 发现 s27，架构侧复现并扩大）

Euler 报出 `primary.s27/ex1`（求 LCM 却用 `a*b`、且无 `constraint`）→ 架构侧扫描**全部 28 个模板题**，
**独立复现出至少 4 个同类缺陷**（题面原文，非推测）：

| 节点/题 | 题面 | 答案式 | 产物 | 缺陷性质 |
|---|---|---|---|---|
| `primary.s27/ex1` | 求 {a} 和 {b} 的 LCM，**其中 {b} 是 {a} 的倍数** | `a*b` | 25 / 48 / 35… | **条件未强制**（题干说假话）+ **公式与该条件矛盾**（该条件下 LCM=b）+ `a==b` 必错 → **每个 seed 全错** |
| `primary.s12/ex1` | 小明有 **7** 元，买 **8** 元文具，**还剩几元** | `a-b` | **-1 元** | 缺 `a>=b` 约束；小学内容出现负数 |
| `primary.s23/ex2` | 66 个苹果按 5:7 分，**小明分得多少个** | `total*x/(x+y)` | **55/2 个** | 缺整除约束 → **半个苹果** |
| `primary.s02/ex2` | 计算 **39-47** | `a-b` | **-8** | 小学减法出负数（缺 `a>=b`） |

**根因（比单个模板写错更深）**：`answer_expr` 与题干 prompt **由同一次 LLM 调用同时产出**——
**它是"自证"的**；生成器既当出题人又当答案人，**没有任何独立验算**。
既有 `content validate` 只验"能渲染 / 可解析 / `constraint` 成立 / sympy 能算"，
**验不出"答案与题面语义是否一致"**（`answer_expr` 就是被信任的那个标准）。

**危害**：判题以 `answer_expr` 为准 → **学生答对会被判错、答错会被判对**；且数学题出现负数/半个苹果
属**内容质量事故**（比"不可答"更严重：不可答只是问超纲，这个是**教错**）。

**裁决**
1. **判为 P0 内容缺陷，优先修**（用户可见，且在库里）。修法 = **重生成**该批 auto 节点，
   **不是**手改单条（手改会被下次重生成覆盖，且不解决根因）。
2. **R35b 增一道内容闸门（并入 P2"数学路径"一起做）**：`content/pipeline.py` 增
   **语义自检**——
   - **领域合理性（通用，所有学科）**：对模板渲染 N 个 seed，校验结果**不违反题面隐含的领域约束**
     （数量/金额/个数非负；"多少个"必须为整数）——**可由内容声明 `unit`/`kind` 或题面关键词推导**，
     且必须能在**无 LLM** 下跑（纯确定性）；
   - **数学（math preset）**：标准答案**不由 LLM 声明**，改为**用 sympy 独立计算**并与 `answer_expr`
     比对（如 LCM 题必须 `sympy.lcm(a,b)`）；不一致 → 拒绝入库；
   - `constraint` **必须强制题面里的每一个条件**（如"b 是 a 的倍数" ⇒ `b % a == 0`）——
     **题面不得说出未被约束保证的话**。此条纳入"造错必报"用例。
3. **顺带全库体检**：28 个模板题逐条过（含人工节点的"题面泄漏"类问题，如 `middle.0102` 的
   prompt 把"比如 x=5"写进了题面）；产出缺陷清单 + 处置（重生成 / 修模板）。
4. **优先级**：**该闸门是 P1(S3/S4) 的前置**——不先堵住，后续每次生成都可能在污染内容库。
   故顺序改为：**语义自检闸门 + 全库体检 → 再 S3/S4**。
5. **现场恢复**：`primary.s27` 等缺陷节点在修复前**不应被用户看到**——修复方式二选一（Euler 定）：
   (a) 直接从库中移除该批 auto 节点，待闸门就绪后重新生成；(b) 立即重生成并过新闸门。
   **倾向 (b)**，但若闸门未就绪则先 (a)，**宁可少内容，不可教错**。

### 12.1 ⚠️ 闸门必须**学科无关**（用户追问后架构侧追加的硬约束）

**用户追问**："他这个修复不会只修数学吧？" —— **风险确实存在**：上表 4 例**恰好都出在数学**，
容易让实现滑向"数学专用补丁"。**明确裁定**：

**闸门分三层，只有第二层与学科相关**：

1. **通用层（所有学科，必须过）**：`渲染 N seed → 校验结果不违反题面隐含/声明的领域约束`
   （数量/金额/个数**非负**；"多少个/几只/几元"**必须整数** 等）。**机制与学科无关**——
   它吃的是**内容声明的谓词**，不是"数学规则"。**任何学科的内容都必须过这一层。**
2. **L1 验算插件层（按学科注册，math 是第一个）**：math → sympy 独立验算并与 `answer_expr` 比对。
   这是 `docs/14 §2.4` 早已定义的 **L1 结构化可验**插件的**一个实例**，**不是数学特权**；
   将来"数值+单位""代码沙箱"等按**同一插件接口**注册。
3. **无 L1 的学科（史地政文/概念类等）**：**答案对不对机器验不了** —— 这不是漏做，而是**如实分界**；
   它们仍必须过**通用层 + R35 可答性 + 既有护栏**（人工锚点 / 纠错反馈 / 熔断）。
   **禁止**用"没有验算器"当借口跳过通用层。

**实现红线（写进验收）**：
- **不许出现 `if subject == "math"` 之类的分支**；L1 验算必须走**注册表/插件接口**按学科解析。
- 通用层的谓词必须**由内容显式声明**（推导不出来就要求声明），**不许猜题面关键词**（易误判）。
- **验收必交**：一条"**换学科仍成立**"的用例 —— 至少证明**通用层对某个非数学学科同样生效**
  （可用测试内容或 s-* 临时学科构造"金额为负/个数非整"的缺陷并断言被拒）。

### 13. R35b 闸门验收：**部分通过** —— 4 个缺陷真修好，但**闸门漏过第 5 个**（架构侧发现）

**通过部分**：pytest **368 passed + 2 skipped**（370 collected，+10）、`validate` ok、
audit 五学段全绿、`tsc` exit 0；三层结构（通用层 / L1 注册表 / 无 L1 如实标注）**真落地**、
**无 `if subject == "math"`**；**必交的非数学用例已交**（`s-testsubj` 无 L1 → 金额为负/个数非整被拒）。
`primary.s27/s12/s02/s04` 四个缺陷节点**重生成后确实修好**（题面与约束、答案自洽，逐 seed 复验）：

- `s27/ex1`：`constraint: b % a == 0`、`answer_expr: b` —— 正确；
- `s12/ex1`：`constraint: a >= b` —— 正确（不再出负数）；
- `s02/ex2`：`constraint: a >= b and a % 10 < b % 10` —— 正确（且保证"个位不够减需退位"）；
- `s04/ex1`：`constraint: a % b == 0` —— 正确（不再丢"余数"）。

### ⚠️ 但 `primary.s23/ex2` **仍然是错的，且被闸门判为"通过"**

**题面**：化简比 `{m}:{n}` 后，前项与后项的和是多少？ → 16:20 化简 4:5，**和 = 9**。
**系统给的答案是 36**（15:18 → 应为 11，系统给 33）。

**根因是三重的（层层套娃）**：

1. **求值器有坑**：`templates.eval_answer_expr` 用 `sympify(expr, locals=<仅参数名>)` ——
   `sympify("gcd(m, n)")` 在无 `gcd` 环境下**把未知函数静默当成 `1`**（默认 `strict=False`）→ `16/1+20/1 = 36`。
   **模板作者写的表达式在数学上完全正确**，是求值器解析不了它。
2. **L1 验算器另有一套正确求值**：`l1_math._param_values` 的 `_LOCALS` **注册了 `gcd`** →
   算出 **9**。于是 `expect` 与 `answer_expr` 在 **L1 那套**里**都是 9 → 一致 → 通过**。
3. **闸门对比的两侧走的是同一套（L1 的）**，**从未触碰"判题真正用的那一套"** →
   **闸门用正确的尺子量了两遍自己，没量学生实际看到的那把**。

**影响面（架构侧全局扫描）**：`gcd`/`lcm` 用错的情况**仅 `s23`（ex1/ex2）两题**——
其余 27 个模板的表达式只含四则运算，两套求值器结果一致，**未受此坑影响**。

### 14. 裁决与修法

1. **P0：合并求值路径（根治）** —— **`templates.eval_answer_expr` 必须改为
   `sympify(expr, locals=数学函数环境, strict=True)`**，与 `l1_math._LOCALS` **共用同一份**函数表；
   未知名/无法解析 → **抛中文错**，**禁止静默当 1**。
   **这不只是修一个坑**：现在"表达式怎么解析"有**两份实现**（`templates` / `l1_math`），
   本身就是**并行机制**（违反融合约束"默认不新建"）。**必须收敛为单一实现**
   （建议 `content/exprs.py`：一份 `parse/eval` + 一份函数表，两边共用）。
2. **闸门必须校验"实际求值路径"**：新增断言——**`eval_answer_expr(answer_expr)` 的结果必须等于
   L1 独立验算结果**（即"学生看到的答案"= "独立算出的答案"）。**这条才是真正防住本类的闸门**。
   并把"两套求值不一致"列为**违规**（不是 finding）。
3. **`expect` 不得自证**：**`semantics.expect` 与 `answer_expr` 文本完全相同 → 违规**
   （s23 的 `expect` 就是照抄 `answer_expr`，等于没验）。`expect` 必须是**独立表述**
   （如 s27 用 `b`、s23 应写 `m/gcd(m,n) + n/gcd(m,n)` 之外的独立写法，或按"化简后前项+后项"分步声明）。
4. **收紧"未声明 `expect`"的定性（这是架构侧工单写漏的，我认账）**：
   **数学模板未声明 `expect` → 必须有 L1 验算兜底**；**无 L1 兜底且未声明 → 视为违规**
   （当前仅记为 finding，等于放行）。**非数学学科**仍按"如实分界"，但须**显式标注**
   "本模板无独立验算"，且计入护栏统计。
5. **修 `s23`（ex1/ex2）**：改 `constraint`/`answer_expr` 或**重生成**，**必须过新闸门**。
   同时**重跑影响面**：任何当前"答案依赖未知函数被当 1"的模板**一律重生成**。
6. **修体检工具的两个自伤**：① `audit_template_semantics.py` 在 Windows 控制台
   **打印 emoji 崩溃（GBK）** → 加 `PYTHONIOENCODING` 兜底或改用纯文本标记；
   ② "违规 0" 必须**排除 finding**，避免读者误以为全库已验证。
7. **本批结论**：闸门方向对、覆盖了通用层与 4/5 缺陷，但**验收不通过**——
   **先做 1–6，再报。**（原定的 S3/S4 继续后置；`template-level basis` 与本修法同线，可一并做。）

### 15. R35b §13 修复批验收（2026-09-10）：**通过**

架构侧独立复跑：pytest **373 passed + 2 skipped**（375 collected，+5 用例，闸门共 15 条）、
`validate` ok 25/50、audit 全绿、`tsc` exit 0；提交 `797e190`。

**关键三条逐条独立验证（不采信汇报）**：
1. **求值路径单一化真达成**：`content/exprs.py` 为唯一实现，`templates` 委托之，`l1_math` 私有实现已删 →
   **判题路径** `16:20 → 9`、`15:18 → 11`（此前 36/33）✅；
2. **未知函数不再静默当 1**：`foo(m,n)+1` → **中文 `ExprError`**（含"未知名"与受支持函数清单）✅；
3. **`expect` 自证已清零**：修复后模板的 `expect` 均为**独立写法**
   （`lcm(a, b)`、`gcd(a, b)`、`a + (-b)`、`floor(a / b)`、`a * 1 / (1 + 2)` …）✅。

**架构侧口径更正（自查）**：§13 我列的"未声明 expect"清单里 s23/s27 的显示有误——`expect` 声明在
**`template.semantics`** 下，我读的是 `ex.semantics`（节点级），故误判为"无"。**实际 s23/s27 已正确声明。**
教训与 §14-4 同源：**验收读数据要确认层级**，不同层级同名字段会造成假结论。

### 16. 两条剩余裁决（本批提出，交下一批）

**① 全部模板（含人工锚点）必须声明 `expect`** —— **裁决：要，且属数据补充、非重写**
- 现状：`semantics_stats = {templates: 30, violations: 21, verified: 9, unverified: 21}` ——
  21 条未声明者多为**人工锚点**（`middle.*`、`primary.0101–0104`）。
- **裁决**：**人工锚点也补 `expect`**；这**只是加字段**（解题路径、评分、节点 id 全不变），
  **不违反"锚点不得改动"红线**（该红线禁的是改 id/锚点语义，不是禁止补充元数据）。
- Euler 不以重生成覆盖人工内容是**正确判断**（记功）；补声明应与重生成**分开**做。
- 补完后的验收：`semantics_stats.violations == 0`，且 `verified` 覆盖全部模板。

**② 题面泄漏：8 处命中，且**人工锚点也有**（架构侧新证）**
- `middle.0102/ex1-3`：题面写「直接填数字，**如 x=7**」——**说"填数字"却给 `x=` 形状**，
  且该示例与答案形状一致（`answer_expr` 产出 `x = 2`）；
- 另有 `middle.0202`（"如 -5"）、`primary.0102`（"如 3/5"）、`0103/0104`、`s04` 等 8 条命中（Euler 已登记）。
- **裁决：必修**（P1，与 `expect` 补声明同批）。修法：**示例改为占位形式**（`如 x=…` / `如 3/5 这种形式`），
  **不得等于任何 seed 的答案**；并把"题面含答案原样"升级为**闸门违规**（当前仅是 finding/告警）。
  **理由**：这是**直接漏答案**——比"问超纲"更直接地毁掉练习价值。

**优先级（更新，取代 §14-7 的后续安排）**：
```
P0（已完成）求值单一化 + 闸门三硬规则 + s23 修复
P1  全部模板补 expect（含人工锚点，纯数据） + 题面泄漏修复（8 处） + 二者进闸门
P1  数学路径 template-level basis（复用 semantics.expect/requires）
P2  S3 挑战题双池 / S4 追问 reteach / P4 机器校验 / 融合对照表补全 / docs 06-07 同步
P3  用户 PDF 学科的 A2 端到端审计（靶子就绪后）
```
**数学当前处于停用态**（用户不可达），故 P1 不阻塞用户体验，可按上述顺序从容做完再交。

### 17. 架构侧自查：**审计注意力过度集中在数学**（用户质疑 · 2026-09-10）

**用户质疑**："我们是全科教练，为什么你大部分修复都围绕数学？"

**架构侧认账并留档（原因 + 风险 + 纠正）**：

1. **事实**：§12–§16 的内容修复（28 模板体检 / 补 `expect` / 题面泄漏 / 求值器合并）**全是数学**，
   而**数学此刻处于停用态、用户不可达** —— **优先级确实偏低**（技术规格对，投入产出比不对）。
2. **原因（三条）**：① **有内容才暴露缺陷**——真实的非数学内容当前**为 0**（行星科学已硬删、
   PDF 学科未建），"只有数学可查"不等于"数学优先"；② **"独立验算"这层天然只有数学有**
   （sympy 是唯一的 L1 验算器），故该层用例与 bug 必然长在数学上；③ **真问题**：
   把"数学特有的技术缺陷"当成"全科级事故"反复开裁决。
3. **必须说清的边界**：**闸门本身不是数学件**——① 通用层（非负/整数/离散量）与
   ③"无 L1 如实标注"**对所有学科生效**；只有 ② 是数学。
   但目前**只有数学喂过这条路径，非数学路径一次都没跑过**。
4. **尚未被覆盖的风险（留给 PDF 学科验收）**：同一类问题在非数学学科的**形态不同**——
   非数学**没有 L1 验算**，"正确答案本身错误 / 选项互相矛盾 / 与材料不符"**当前抓不住**，
   只能靠 **R35 可答性 + 用户纠错反馈 + 熔断**。"机器验不了"是**如实分界**，不是已解决。
5. **纠正**：数学那摊**收尾即止**（§16 的 P1 一次打包做完，不再连开裁决）；
   **验收焦点转向用户新建的 PDF 学科**——它第一次让**非数学路径**运行，
   预期会暴露**数学不会有的缺陷**（如选项自相矛盾、正确答案与材料不符），**那才是本轮的真正考试**。

### 18. R35b §14（步骤 1–4）验收（2026-09-10）：**通过**；步骤 5–6 按 Euler 自述未做

架构侧独立复跑（不采信汇报）：pytest **376 passed + 2 skipped，136.5s，exit 0**（378 collected，+3）；
`content validate` **ok 25/50**；audit 五学段全绿；`tsc` exit 0；
**`guardrails.semantics_stats() = {templates: 30, violations: 0, verified: 30, unverified: 0, l1_subjects: ['math']}`** ✅
（与汇报逐位一致）；**人工锚点 id 红线守住**（5 个锚点文件逐条比对，节点 id 与题目 id 序列**完全未变**）。

**逐项核实**
1. **题面泄漏清零 + 升为违规** ✅：`verify.leak_problems()` 设计正确——**只扫提示/示例片段**
   （`hint_segments()`，即括号内与"如/例如"之后），题干正文里的参数数字**不算泄漏**。
   架构侧直接调用复核：`primary.s27/ex1` 的 `hint_segments = []` → `leak_problems = []`（**无误报**）。
   **Euler 对我 §16 口径的更正成立**：我此前把"参数值出现在题干"（`0103/0104/s04` 等 5 处）算作泄漏，
   **是我的假阳性**，认账。
2. **30 条模板全补 `expect`** ✅：`violations=0 / verified=30 / unverified=0`；
   `expect` 为独立写法（`Rational(c - b, a)`、`b * a`、`10 * floor((a+5)/10)` …）——
   **纯加字段、解题路径与节点 id 未动**（与 §16 裁决一致）。
3. **模板级 basis** ✅ 但**精度不足**：架构侧实测 **30 条模板 → 仅 19 条不同引文**（最多重复 3 次），
   且部分引文是**开场白**（如"同学们，今天学习…"）而非"**支撑该模板的规则句**"。
   **引文校验通过率 100%**（0 条不在讲解中）→ 不是幻觉，但**引用得不够准**（Euler 已如实自述，记功）。
   **裁决：列为提升项**（下批与 docs 同步一起做），**不阻塞**。
4. **P4 机器校验** ✅（R36 欠账已还）：`check_progression()` 两条——引用必须已教（`basis.fact_ids ⊆ `
   本单元 ∪ 已学前置单元的 `taught_facts`）；**加难必须加事实**（难度高于全部前置却零新增已述事实 → 违规）。
   已接生成端，含正例与造错用例。

**边界（Euler 诚实分界，架构侧认可）**：**步骤 5（S3 挑战题双池）与 6（S4 追问 `reteach`）未做**，
步骤 7 仅补了本批四行、`docs/06/07` 未同步。**理由是会话上下文预算到顶**——
**"做完做净、不留坏状态"的判断正确**，优于硬塞半成品。

**下一批（开工第一件事）**：S3 + S4 + 模板 basis 语义精细化 + `docs/06/07` 同步 + 融合对照表补全。
**建议**：Euler 上下文已到顶，下一批**开新会话**接手（`docs/13 §1` 开机清单 + `IMPLEMENTATION_NOTES §58` 挂账总表
即为其单一入口，记忆已外置，无损）。

### 19. R35b 收尾批（步骤 5–7）验收（2026-09-10）：**通过 —— R35 主线收口**

架构侧独立复跑（不采信汇报）：pytest **392 passed + 2 skipped，144.5s，exit 0**（394 collected，+16）；
`content validate` ok 25/50；audit 五学段 27/31/81/59/60；`tsc` exit 0；`vite build` exit 0；
`semantics_stats = {templates:30, violations:0, verified:30, unverified:0}`；
**basis 引文独立复算**：30 条 → **26 条不同引文**、重复仅 4 组×2（均为"同节点同规则支撑两题"）、
**逐字失败 0、开场白 0**；提交链 `955724c → 7395b26 → b1e2bca`。

**代码审查亮点**
1. **挑战题四账未污染——而且修法是白名单**：`models.PROGRESS_KINDS = ("exercise","feynman")`，
   `/api/dashboard.today_done` 按白名单过滤。**用白名单而非"排除 challenge"黑名单，方向正确**
   ——**以后新增任何 `kind` 默认不计入进度**，不会因新增种类而再次污染。**这是本轮最有价值的一处修正**。
2. **实测复核（重启后端后）**：`GET /api/history/challenge → 200`（空列表 + 中文声明"仅复盘用，不计入任何进度"）；
   `GET /api/dashboard` 键为 `preset_subject/recommended_node/due_reviews/breakpoints/stats`——
   **无 `challenge` 键**，证"挑战题永不出现在默认流程"的红线成立。
3. **落库口径单一**：挑战题唯一落库点 = `attempts.kind="challenge"`，复盘复用同一读法，**未建表**。

### 20. 疑点裁决（Euler 四条）

1. **`reteach` 不翻转 `stage`（与文档字面"退回讲解"有出入）** → **采纳 Euler 的方案，并修正文档措辞**。
   理由：翻回 `explain` 会**让已通过的练习重新出题并再次计入 practice 账目**——那是**真实的副作用**；
   而教学意图是"**让你回去看讲解**"，属 **UI/导航**语义，**不需要**改状态机。
   **裁定**：`stage` 保持 `feynman` 不变；响应带讲解原文 + `next_action="reteach"`；
   **前端**在进入 reteach 时显示"**回看讲解**"入口（可展开讲解、可重读），学生看完**重新提交完整稿**。
   **必交断言**：reteach 后 **费曼账本 / 两个额度 / practice 计数 / `user_nodes` 均不变**，
   且随后**能正常再次提交并通过**。**文档（docs/05/06/07）措辞统一为"**回看讲解（阶段不变）**"**，
   避免下任读字面又去翻 stage。
2. **挑战题刷新后不恢复（刻意不进默认 payload）** → **确认现状**；但要求**补一条**：
   挑战题落库在 `attempts(kind="challenge")` 且 `GET /history/challenge` 已就绪 →
   **前端应能在复盘页看到**；**若将来要让"刷新仍在"，走该读端点回填，不得把它塞进默认 payload**
   （否则就变成"半个默认流程"，破坏 S3 的独立性）。此为**可选增强**，不阻塞。
3. **basis 引文语义贴合度仍需人读** → **接受为已知边界**（机器只能判"逐字 + 非开场白"）。
   本轮已从 19 → 26 条不同引文、开场白归零；**残留 4 组重复经核为合法**（同规则支撑两题）。
   **登记为"人工抽读项"**，随用户走查一并看。
4. **`has_quotable_content` 是语言层启发式** → **接受**：确定性前置只拦"明显敷衍"，
   半敷衍交第 2 层模型判——**方向安全**（宁可多给一次机会，不可误判学生敷衍，符合"减少审判感"基调）。

**R35 主线状态：S1–S8 全部落地并验收**（可答性 / 引文纪律 / 挑战题双池 / 追问 reteach /
🤔 小思考对齐 / 可答性投诉入口 / 全学科覆盖 / 语义自检闸门）。
**剩余唯一验收项 = A2 端到端审计**（用户新建 PDF 学科后：**不可答 = 0**），
那也是**非数学路径的第一次真考试**。

## R37 · 教材真源化（Source-First）：AI 先读懂教材，再由教材出一切（用户指令 · 2026-09-10）

### 0. 用户指令（原话要旨）

> "这部分**不用节省成本**。我导入教材，他就应该**教会我这本教材的一切**——大纲、题目、AI 去**直接理解这本教材**然后出具，**各种东西都应该这样**。"

**性质**：**产品级地基变更**——把"教材＝参考"升级为"**教材＝权威真源**"。
**取代/加强** R36 的 D1–D5（"材料为可选输入、220 字摘要、分节摘要降级"）。

### 1. 病根（架构侧读码结论，供实现者理解方向）

现链路实为"**教材仅供参考、AI 自由发挥**"：

```
上传 PDF → 全文落盘 ✅ → 生成单元时只注入【每份材料正文前 220 字摘要】
        → AI 用自己的知识写讲解/出题/声明 taught_facts
        → 服务端只校验"basis 引文 ⊆ 【AI 自己刚写的讲解】"
```
**缺的是与教材的绑定**：只保证"讲解与题目自洽"，**不保证"讲解与教材一致"**；
教材没讲的东西**照样会被当成"已教"来考学习者**。

### 2. 新的真源优先级（实现须逐条落实）

> **教材原文 > 用户补充材料 > 大纲 brief > 模型自有知识（仅可解释/举例，不可引入新事实）**

- **有材料时**，模型自有知识**只能用于**解释、类比、举例、衔接——**不得引入教材未陈述的事实/数字/结论**；
- **无材料时**（用户没传教材）→ 退回现状（AI 起草），并**显式标注"本内容无教材依据"**。

### 3. 规格（R37-S1 … S9）

**S1 · 材料读取不设"省 token"瓶颈**（用户明确不省成本）
- 注入**不再**默认 220 字摘要 / 6000 字符总预算；改为**按结构（章节/页）注入完整正文**；
- 书太大时用**结构化分段处理**（按章节分批调用/分层摘要），**不得**用"前 N 字"糊弄；
  新配置项**默认宽松、可调至不限**（`MF_MATERIAL_INJECT_MAX_CHARS=0` 表示不限）。

**S2 · 大纲＝书的目录，且必须全覆盖**
- 起草大纲时**先产出"书的章节地图"**（章 → 节），再由它派生大纲单元；
- **每个章节必须映射到 ≥1 个大纲单元**；未映射的章节 → **违规**（不得悄悄丢）；
- 单元的顺序/`prereqs` **以书的顺序为主**，只在**书本身有前置矛盾**时才允许调整并**说明理由**；
- **允许合并**（一节太小）与**允许拆分**（一节太大），但**必须记明"由书中哪些节合成/拆自哪一节"**。

**S3 · 讲解＝把该教材段落讲全、讲通**
- 单元的`taught_facts` **必须逐字出自教材原文**（不是出自 AI 自己写的讲解）；
- 讲解 = 对**教材该段**的**完整演绎**（允许换措辞、举例、加类比；**不许省略要点、不许加教材外事实**）；
- **教材该节没讲到的**，一律不算"已教"。

**S4 · 题目/例题/rubric 全部由教材派生**
- 每道题 `basis` 的引文**必须能在教材原文里找到**（复用 `content/citations.py` 同一把尺子）；
- `worked_examples` 优先取自书中例题；书里没有则**由书中内容构造**，且**须标注"据教材 X 节构造"**；
- **费曼 rubric** 也按教材的知识点组织（"这本教材认为该掌握什么"）。

**S5 · 新增校验：教材锚定（Material Binding）**
- 闸门增**第三类校验**：**每条 `taught_facts` / `basis.quote` 必须能在该学科材料正文中逐字找到**；
- **找不到 → 拒绝入库**（生成时重试一次，仍不行则**丢弃该题**；事实句找不到则**整单元失败**）；
- **违规信息为中文**，且**说明缺什么**（便于用户判断"是书的这一节没讲，还是模型编了"）。

**S6 · 覆盖账本与"教材未覆盖"的显式化**
- 每个单元记录：来源材料 + 节标签 + **覆盖状态**（完整/部分/未覆盖）；
- 材料有、内容无法覆盖时 → **明确告知用户"教材未覆盖此单元"**（中文），**不得编造**；
- 大纲页显示**总覆盖账**：`已覆盖节数 / 总节数`，并列出**未覆盖清单**。

**S7 · 扫描/图片版 PDF 的诚实边界（否则"教会一切"的前提不成立）**
- 入库时检测**文本层健康度**（每页字符数）；**无文本层/极稀疏** → **明确中文告知**：
  "本书是扫描版、未提取到文字，请先 OCR 或改用文本版"；
- **不做 OCR**（本地无 OCR 引擎）；但**必须如实报告**，不得静默生成一本"没读到书的大纲"。

**S8 · 大纲阶段也要读得到书的结构**
- 起草大纲不能只看摘要：须注入**章节目录 + 目标章节正文**（按 S1 的分段策略）。

**S9 · 既有机制一律复用（融合约束不变）**
引文尺子（`citations.py`）、闸门三层结构、材料存储（`content/subjects/<sid>/materials/`）、
学科生命周期、`attempts/feedback` 表——**均不新建平行机制**。

### 4. 与既有裁决的关系

- **加强** R36 D1–D5：D1"可选输入"→ **有则权威**；D2 溯源从"节标签"→ **逐字可验**；
  D4"预算/降级"→ **改为不省成本 + 结构化分段**；D5"学科无关"**不变**；
- **加强** R35：可答性的"已教集合"从"AI 写的讲解"**上移一层**到"**教材原文**"；
- **不冲突**：数学 preset 走 roadmap 路径，本裁决只作用于**有材料的自定义学科**。

### 5. 代价与前提（用户已知并接受）

- **token 成本上升**（用户明示不省）——受 `LLM_MAX_TOKENS_PER_DAY` 保护，仍**留审计痕迹**（`ai_logs`）；
- **长书需分段处理**：单次调用塞不进整本 → 采用"章节地图 + 逐章生成 + 跨章一致性复用"；
- **教材质量参差**：教材本身写错时，系统会**忠实继承错误**——这属"真源"的固有取舍，
  由**用户纠错反馈 + 熔断**兜底，**不假装系统能识别教材错误**。

### 6. 派工

交 Euler（工单 `.runtime/EULER_TICKET_R37.md`）。**建议开新会话接手**（`docs/13 §1` 开机清单）。
**验收锚点（用户动作）**：用户导入一本真实教材 → 大纲覆盖全书章节（未覆盖清单为空或逐条可解释）
→ 任选单元的题目/讲解**能在书里找到出处**（抽 3 条人工核对）→ A2 审计"不可答 = 0"。

