# 11 · 成长型阶段总工单（Growth Work Order）

> 生效：用户确认（2026-09-08）。执行人：Euler。总纲：docs/10-progression.md；
> 背景裁决：docs/09（R11/R12 继续有效）。
> 约定：**分阶段执行、每阶段单独汇报**（改动清单 + 测试结果 + 可验收点），
> 不要全部做完才汇报；docs 是唯一事实源；不动架构决策；每步跑全量回归（基线 139 passed
> + 1 skipped）与 `content validate`；进度与疑点记入 IMPLEMENTATION_NOTES.md。

---

## 阶段 1：收尾既有裁决（docs/09）

1. **R11 遗留**：`service/session.py` 分支覆盖审计 + 补 E2E（练习连错 2 次回炉、一轮 5 题
   cap 回炉、费曼 3 轮不过回炉——覆盖 R10/R11 同款盲区）。
2. **R12-a 模型策略**：`ai/tier.py` 解析器。决策链 `基础档(学段/content)→升级触发→用户覆盖`：
   - 基础档：primary/middle/high→fast；college/ai→think；内容可 `feynman.thinking:true` 覆盖。
   - 触发（升 think）：费曼首轮 fast 评分 ∈ [threshold−0.15, threshold+0.10] → 下轮 think；
     费曼轮次 ≥2 → think；答疑 fast 回复 `out_of_scope` → 自动 think 重生成覆盖。
   - 覆盖：画像 `profile.model_mode ∈ smart|light|deep`（light 关触发但保 college/ai think；
     deep 全 think）；单次提交 `payload.think_deep` 覆盖该次。
   - schema 补充：answer_question 输出 `out_of_scope:bool`；feynman_evaluate 输出 `confidence`(可选)。
   - 涉及调用点：explain / answer / hint / feynman_evaluate / feynman_followup。
   - 设置页三档模式；学习/费曼/答疑界面"⚡快 / 自动 / 🧠深度"即时切换；评分卡标注本次所用档。
3. **R12-b 流式输出**：`POST /session/step` 支持流式（SSE）或独立端点；LLM 文本增量下发，
   最终仍回完整 JSON 状态（"渲染指令=状态机"契约不变）；流不可用自动回退整体 JSON；
   覆盖讲解/答疑/费曼评分卡/追问；前端打字机效果。协议改动同步 docs/06 §2、docs/07。

## 阶段 2：关卡化体验层（docs/10 §2.1）

4. content 关卡分组元数据：stage/topic → 关卡；新增**首领关卡（boss）节点类型**：
   主题综合题 + 费曼综述"把本主题整体讲一遍"，通过 = 学段小结完成 + 解锁下一学段入口
   + 触发一次复习整合。解锁复用现有掌握度/前置逻辑，不建第二套引擎。
5. 前端关卡地图视图（增强/替代裸图谱）：关卡进度、星级、通关与"下一关生成中…"提示。

## 阶段 3：课程蓝图 + 内容自续闭环（docs/10 §2.2/2.3，核心）

6. **课程蓝图**：`content/roadmap/primary.yaml` 先行（小学全序列；条目轻：标题/学段/主题/
   目标/前置猜测/难度/是否需思考模型），小学蓝图人工精核后再扩其余学段。
7. **gen_content 真实实现**（替换占位）：按蓝图主题组批量 AI 出稿 → 自动校验（结构/无环/
   模板渲染/**每题 sympy 验算，broken=0**）→ 按入库策略落 stages 或 `_drafts`。
8. **自续触发**：当前阶段接近学完（mastered ≥90% 或用户点"继续下一关"）→ 后台生成下一主题组；
   每日 token 限额（LLM_MAX_TOKENS_PER_DAY）内执行、不阻塞学习；完成 UI 通知新关卡。
9. **入库策略（默认混合制）**：primary/middle 校验全过自动入库并标注 auto；high+ 进 `_drafts`
   待审。讲解/题目带"纠错反馈"按钮：标记复核 → 自动重生成替换。
10. **端到端验收（docs/10 §4）**：用户可从当前进度连续通关小学段，系统自动生成并解锁
    初中代数第一批，全程无需找开发者加内容/代码（仅使用纠错反馈）。

## 汇报协议
- 每阶段：改动文件清单 / 测试结果 / 与 docs 冲突或需架构裁决的疑点 / 可验收点说明。
- 阶段 3 再拆小步，逐步汇报：**蓝图 → 流水线 → 自续触发 → 入库策略 → 端到端**，
  每小步一个汇报，避免一次性憋大招容易翻车、难排查。
- 验收方式约定：**后端有改动一律先重启服务（stop.ps1 → dev.ps1）再实测**；
  每阶段交付后由用户在浏览器实际游玩验收，不是只看测试绿。
  - 阶段 1 验收：答题/费曼/提示的速度与"⚡/自动/🧠"切换、流式打字机效果；
  - 阶段 2 验收：闯关地图可见、通关解锁下一关、"下一关生成中…"提示；
  - 阶段 3 验收：连续通关小学段时系统自动生成并解锁初中代数第一批（docs/10 §4）。
- Euler 每阶段汇报后，用户会把汇报转交架构侧（Feynman/架构师）过目把关，再进入下一阶段。
