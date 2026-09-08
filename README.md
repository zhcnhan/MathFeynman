# MathFeynman — AI 数学导师（费曼教学法自适应学习系统）

> 一个结合 LLM 的本地单机"智能导师系统"(ITS)：用知识图谱组织从小到大的全部数学内容，
> 以费曼学习法为核心教学法，程序主导流程、AI 在受控槽位生成内容，帮助用户捡拾断点、
> 顺序学习、进阶到 AI/量化所需的数学，并在合适时机敦促复习。

本仓库首先是一套**设计文档**（本 README 为入口），其次才是代码实现。
任何实现都必须以 `docs/` 下的文档为准；文档与代码冲突时，以文档为准并更新冲突的一方。

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/01-product.md](docs/01-product.md) | 产品愿景、三框架需求、边界与非目标 |
| [docs/02-architecture.md](docs/02-architecture.md) | 总体架构、分层边界、技术决策(ADR)与目录规划 |
| [docs/03-domain.md](docs/03-domain.md) | 确定性核心：知识图谱、掌握度、复习调度(FSRS)、用户画像 |
| [docs/04-content.md](docs/04-content.md) | 内容库文件格式、习题模板、内容生产流水线 |
| [docs/05-ai-integration.md](docs/05-ai-integration.md) | **AI 受控集成规范**：状态机、调用点 Schema、防幻觉、评分 Rubric |
| [docs/06-api.md](docs/06-api.md) | FastAPI 端点草案与 SQLite 表结构 |
| [docs/07-ui.md](docs/07-ui.md) | 界面与三种交互模式（工作台 / 分步引导 / 图形工具） |
| [docs/08-mvp.md](docs/08-mvp.md) | MVP 范围、里程碑与可勾选的验收清单 |
| [docs/09-architect-rulings.md](docs/09-architect-rulings.md) | 架构侧对 Euler 实现疑点的正式裁决记录 |
| [docs/10-progression.md](docs/10-progression.md) | **闯关式学习与内容自续**：关卡化体验、课程蓝图、自动生成闭环 |
| [docs/11-workorder.md](docs/11-workorder.md) | 成长型阶段总工单（分阶段执行，Euler 当前任务） |
| [docs/12-roadmap-master.md](docs/12-roadmap-master.md) | **课程蓝图总纲**：全学段地图规划、北极星与懒生成 |
| [docs/13-agent-handover.md](docs/13-agent-handover.md) | **Agent 交接协议**：新 Euler 续接的开机清单与行为公约 |

## 不可变决策（改动需先改本文档并重新评审）

以下决策是架构的锚点，实现过程中**不允许静默偏离**；确需修改时先更新本清单与对应文档：

1. **形态**：本地单机。本地进程 + 浏览器访问（类 Jupyter 用法）。数据存本地 SQLite，无账号、无云端。面向公众化是"以后加后端"，不改变引擎。
2. **技术栈**：Python 后端（FastAPI）+ TypeScript 前端（React + Vite）+ SQLite + sympy（确定性判题）+ KaTeX（公式渲染）+ JSXGraph（几何交互）。
3. **判题原则**：**凡是可确定性验证的，绝不让 LLM 判断对错**。数值/表达式题一律走 sympy；LLM 只用于生成与语言理解。
4. **AI 是被调用的函数，不是引擎**：教学流程由程序状态机编排；所有 LLM 调用点必须定义输入/输出 JSON Schema，输出先校验再落库，校验失败按规范重试或降级。
5. **内容库优先**：事实性教学内容来自 `content/` 结构化库，LLM 讲解时注入本课上下文并受概念白名单约束，禁止越级引入未学概念。
6. **LLM Provider 层使用 OpenAI 兼容接口**（默认 DeepSeek，base_url/模型可配置；本地 ollama 亦兼容）。模型按环节分级：重推理环节用强模型，轻环节用便宜/轻模型。
7. **分层边界**：`domain`（确定性核心）不得依赖 LLM 与 UI；`ai` 层只能通过 schema 化调用点与外界交互；UI 只消费 API。
8. **预算约束**：开发期"AI 写代码"预算 ≤ 200 元（走 DeepSeek 等低价 API/本类 AI 编码环境）。运行期模型 API 费用另计，但设计上默认低成本模型 + 省 token 结构。
9. **学习与自我拓展 = 系统层记忆 + 自续内容（北极星制）**：不做模型微调。个性化来自用户画像 + 掌握度 + 复习调度；内容扩展 = 全学段默认自动入库（source:auto），质量护栏：sympy 校验 + 概念白名单 + 掌握度/费曼通过作内容旁证 + 纠错反馈召回与主题熔断（docs/12 P4、`service/guardrails.py`）；人工锚点节点精写作为质量基准。运行期零人工审核（北极星，docs/10 §3 已同步）。

## 快速理解（30 秒版）

- 全部数学内容组织成一张 **知识图谱(DAG)**：捡拾=诊断断点、学习=主路径、AI 进阶=子树。
- 学一个知识点的闭环：**讲解 → 例题 → 练习(自动判题) → 费曼口述(你讲给 AI 听，按 Rubric 评分+追问) → 达标 → 进入 FSRS 复习队列**。
- 程序是骨架（图谱/判题/复习/状态机），LLM 是血肉（讲解措辞、出题变体、费曼评估的语义部分）。
