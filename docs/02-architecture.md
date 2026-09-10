# 02 · 总体架构与技术决策（ADR）
> 适用范围：范围：通用核心架构（分层/ADR）。将随 docs/14 Phase A 泛化（subject/outline/concept 层），勿照搬其中的数学专属实现细节

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (React + Vite + TS)                                │
│  KaTeX 公式渲染 · JSXGraph 几何 · 三交互模式 · 本地仪表盘       │
└───────────────────────────▲─────────────────────────────────┘
                            │ HTTP/JSON (localhost)
┌───────────────────────────┴─────────────────────────────────┐
│  FastAPI 后端 (Python 3.11+)                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  api/        REST 端点（薄）                          │   │
│  │  service/    用例编排：教学会话状态机、费曼流程、复习    │   │
│  │  domain/     纯逻辑核心：图谱/掌握度/FSRS/画像 ← 零 LLM │   │
│  │  ai/         LLM Provider 抽象 + schema 化调用点 + 校验 │   │
│  │  content/    内容库加载/模板渲染/题目生成               │   │
│  └──────────────────────────────────────────────────────┘   │
│  SQLite (本地文件)         content/ (结构化内容, git 管理)     │
└─────────────────────────────────────────────────────────────┘
        │
        └── LLM: OpenAI 兼容接口（默认 DeepSeek；可换 ollama/Qwen）
```

**核心规则：依赖方向只能向下/向内。** `domain` 不得 import `ai`、不得 import FastAPI；
`ai` 不得直接碰数据库，只能以 schema 化函数被 `service` 调用；
UI 只能经 API 通信，绝不直连 LLM 或数据库。

## 2. 技术决策记录（ADR）

| # | 决策 | 理由 | 状态 |
|---|---|---|---|
| A1 | **本地单机形态**：本地 FastAPI 进程 + 浏览器访问，一键启动脚本 | 公式/图形交互体验最好；数据本地；无账号成本；引擎与 UI 分离便于日后公众化 | 不可变 |
| A2 | **后端 Python**：FastAPI + SQLite(SQLAlchemy) | sympy 判题是硬需求（math 预置学科口径；通用学科走学科判题器插件，见 docs/14）；numpy/scipy/pandas 通向量化/ML 内容；Python 是 LLM 生态第一语言 | 不可变 |
| A3 | **前端 TypeScript + React + Vite** | 公式/几何/状态机交互生态成熟；TS 防低级错误；AI 编码质量高 | 不可变 |
| A4 | **sympy 唯一判题器**（数值/表达式/方程/等价判断），LLM 永不判对错（math 预置学科口径；通用学科走学科判题器插件，见 docs/14） | 判题可信是学习系统的地基；AI 判题幻觉不可接受 | 不可变 |
| A5 | **LLM Provider 抽象层**：OpenAI 兼容接口；默认 DeepSeek；模型按环节配置 | 换模型=改配置；成本与能力可按环节调配；本地 ollama 可作零成本后备 | 不可变 |
| A6 | **内容库与代码分离**：`content/` 目录为结构化文本文件 | 内容可增量演进、可 git 追踪、可被流水线批量生成与审核 | 不可变 |
| A7 | **教学会话状态机**（见 05 文档）：程序编排，LLM 在槽位生成 | 这是"AI 被限定、与程序有机结合"的实现机制 | 不可变 |
| A8 | **复习用 FSRS**（开源算法；Python 侧 pip `fsrs` 或等价实现） | 比手写 SM-2 现代且效果有据；接口需封装以便日后替换 | 不可变 |
| A9 | UI 框架组件库从简（先不用重型组件库；Mantine/Chakra 候选但非必须） | 减少依赖面；个人项目快速迭代 | 可变动 |
| A10 | 数据表全部带 `user_id`（默认固定单用户 `"local"`） | 一个字段为公众化预留，几乎零成本 | 可变动 |

## 3. 建议目录结构（实现者可按此布局，允许微调但保持分层）

```
颜回（YanHui）/
├── README.md
├── docs/                    # 设计文档（本仓库的规范源头）
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口
│   │   ├── api/             # 路由（薄，只做参数校验与编排调用）
│   │   ├── service/         # 用例层：教学会话/费曼/复习/诊断
│   │   ├── domain/          # 图谱/掌握度/fsrs/画像（纯 Python，零外部依赖可测）
│   │   ├── ai/              # provider.py / calls.py(schema) / validate.py / rubric.py
│   │   ├── content/         # loader / templates / generator
│   │   ├── outline/         # Phase A（docs/14）：subject 注册 + 大纲 schema/持久化（通用学科层）
│   │   ├── db.py            # SQLAlchemy engine/session
│   │   └── models.py        # ORM
│   ├── tests/
│   └── pyproject.toml
├── content/
│   ├── stages/              # 见 04 文档：primary/middle/high/college/ai/...（数学内容库）
│   └── subjects/            # Phase A（docs/14）：学科大纲文件 <sid>/outline.yaml（含 math 派生大纲）
├── frontend/
│   ├── src/
│   │   ├── pages/           # Dashboard / Session / Review / Settings
│   │   ├── components/      # MathInput, WorkedExercise, FeynmanChat, GraphTool…
│   │   ├── api.ts           # 后端客户端
│   │   └── stores/          # 前端状态（Zustand 或等价）
│   └── package.json
├── scripts/
│   ├── dev.ps1 / dev.sh     # 一键启动前后端
│   └── gen_content.py       # 内容流水线入口（AI 初稿→校验→审核）
└── .env.example             # LLM_API_KEY, LLM_BASE_URL, 模型分级配置
```

## 4. 运行形态与成本设计

- 启动：`scripts/dev.ps1`（Windows）启动 uvicorn + vite dev（或构建后由 FastAPI 托管静态文件，二选一；MVP 阶段用 vite dev 即可）。
- LLM 分级配置（`backend/config` 或环境变量）：

| 环节 | 模型档位 | 说明 |
|---|---|---|
| 费曼评分/追问/答疑（语义重、强推理） | `heavy`（默认 DeepSeek 推理档，如 deepseek-reasoner 或可配） | 强推理、低幻觉 |
| 讲解（注入讲解稿演绎，R9 起用快档） | `light` | 快、便宜；质量回退可回滚（docs/09 R9） |
| 出题变体/分类/轻改写 | `light`（默认 deepseek-chat） | 便宜、快 |

- **动态模型策略（R12，实现见 `ai/tier.py`）**：每次 AI 调用按
  `基础档(学段 primary/middle/high→fast；college/ai→think；内容 feynman.thinking→think) →
  升级触发(smart：费曼边缘分/轮次≥2/超纲答疑 out_of_scope) → 用户覆盖` 决策 `fast|think`；
  用户全局模式 `model_mode ∈ smart|light|deep`（存画像），单次提交 `payload.think_deep` 覆盖该次。
  fast→light 模型、think→heavy 模型（provider.model_for_strategy）。
- Provider 接口统一 `chat_json(call, messages, strategy|model) -> validated dict`，内部处理 JSON 提取、
  schema 校验、失败重试（见 05 文档第 6 节）；ai_logs 记录策略档 tier。
- 运行期成本可控策略：内容讲解与题目文本尽量落库复用（同节点不重复调用重模型）；对话上下文按环节裁剪，不做无界聊天历史。

## 5. 工程质量基线

- `domain/` 必须有单元测试（图谱可达性、掌握度规则、FSRS 推进、判题等价性）。
- 所有 LLM 调用点的 schema 用 pydantic 定义并校验（AI 层失败不影响 domain 状态一致性）。
- 任何入库内容需通过 `content validate`（结构校验 + 模板可渲染 + 答案 sympy 可验算）才算合法。（math 预置学科口径；通用学科走学科判题器插件，见 docs/14）
- 数据库变更用 SQLAlchemy `create_all` + 版本字段起步（MVP 不必上 alembic，但保留升级路径）。
