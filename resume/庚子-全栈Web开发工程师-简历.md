# 庚子 · 全栈 Web 开发工程师

> [电话] · [邮箱] · [所在城市] ｜ GitHub: https://github.com/zhcnhan
> 求职意向：全栈 / Web 开发工程师（Python + React 技术栈）

---

## 个人简介

- 3~5 年全栈开发经验，习惯从 0 到 1 独立交付完整产品：需求分析 → 架构设计 → 前后端实现 → 部署运维 → 迭代优化，全程文档驱动、测试护航。
- 后端以 Python 生态为主（FastAPI / SQLAlchemy / Pydantic），前端以 React + TypeScript 为主（Vite / Zustand / KaTeX / Three.js），熟悉 Docker、Nginx/OpenResty、systemd、CI 等工程化与部署手段。
- 对 AI 应用工程化有深度实践：LLM 受控集成（Schema 化调用、输出先校验再落库、模型分级路由）、防幻觉内容护栏、知识图谱 + 间隔重复（FSRS）等，擅长设计"确定性系统为主、AI 为辅"的可靠架构。
- 重视工程质量：以设计文档 / ADR 约束实现、以自动测试守护回归；熟练使用 AI 编码工具在受控预算内推进大型项目。

## 技能清单

| 方向 | 技能 |
|---|---|
| 后端 | Python 3.10+ · FastAPI · SQLAlchemy 2 · SQLite · Pydantic 2 · REST API 设计 · sympy · pytest |
| 前端 | TypeScript · React 18 · Vite · Zustand · React Router · KaTeX · Three.js · Tailwind CSS · PWA |
| AI / LLM | OpenAI 兼容接口接入（DeepSeek 等）· 输出 JSON Schema 约束 · 模型分级路由 · 提示词工程 · 防幻觉 / 质量护栏 |
| 工程 / 运维 | Git · GitHub Actions CI · Docker / docker-compose · Nginx / OpenResty · systemd · Linux 部署 · CLI 工具 · macOS 应用封装 |

## 项目经验

### 1. MathFeynman —— AI 数学导师（费曼教学法自适应学习系统）｜ 独立设计开发 · 持续迭代中

GitHub: https://github.com/zhcnhan/MathFeynman ｜ Python 3.11 / FastAPI / SQLAlchemy 2 / SQLite / sympy / FSRS / React 18 / TypeScript / Vite / KaTeX

本地单机"智能导师系统"(ITS)：以知识图谱组织从小到大的数学内容，教学流程由程序状态机编排，LLM 只在受控槽位生成讲解与评估，帮助用户捡拾知识断点、顺序学习并进阶到 AI / 量化所需的数学。

- **架构设计**：以 13 份设计文档 + ADR（产品愿景 / 总体架构 / 领域模型 / 内容格式 / AI 集成规范 / API / UI / MVP 验收 / 课程蓝图总纲等）驱动实现；代码按 `domain / ai / service / api / content` 严格分层，确定性核心不依赖 LLM 与 UI。
- **确定性核心（domain）**：知识图谱（DAG）组织小学 → 初中 → 高中 → 大学 → AI 分学段内容与自动内容流水线；sympy 实现数值 / 表达式题自动判题，坚持"凡是可确定性验证的，绝不让 LLM 判断对错"；接入 FSRS-6 官方算法族实现复习调度；掌握度模型 + 用户画像驱动个性化学习。
- **AI 受控集成（ai + service）**：所有 LLM 调用点定义输入 / 输出 JSON Schema，输出先校验再落库、失败按规范重试或降级；模型按环节分级路由——重推理环节用强模型、轻环节用低成本模型（默认 DeepSeek，base_url / 模型可配置，兼容本地 Ollama）。
- **防幻觉质量护栏**：讲解注入课程上下文并受概念白名单约束，禁止越级引入未学概念；guardrails 服务以 sympy 校验 + 掌握度 / 费曼通过作内容旁证 + 纠错反馈召回与主题熔断，支撑"运行期零人工审核"的自续内容闭环。
- **产品闭环**：讲解 → 例题 → 练习（自动判题）→ 费曼口述（按 Rubric 评分并追问）→ 达标 → 进入 FSRS 复习队列；闯关式课程蓝图 + 懒生成内容生产；前端提供工作台 / 分步引导 / 图形工具三种交互模式与 KaTeX 公式渲染。
- **工程实践**：pytest 自动化测试与里程碑验收清单同步推进（数百条测试持续回归）；通过 AI 编码代理（DeepSeek）在受限预算内分阶段交付，并沉淀 Agent 交接协议与行为公约，支撑长周期项目的可持续推进。

### 2. Toolbox —— 个人开发者工具 Monorepo ｜ 独立开发 · MIT 开源

GitHub: https://github.com/zhcnhan/toolbox ｜ Python 3.10+ / FastAPI / React 18 / Vite / Tailwind CSS / Framer Motion / Three.js / Docker / GitHub Actions

Monorepo 内含多个自包含、可独立部署的子项目，包含两个完整的前后端分离 Web 应用：

- **Batch Background Remover（批量抠图 Web 服务）**：FastAPI 后端 + React 前端。设计**插件式抠图引擎架构**，8 种引擎统一接口、自由切换：本地 rembg / SAM 1 ViT-L / 图标抠图，云端 Gemini Mask / Kimi（多边形坐标）/ remove.bg / 擦个图 / 自定义，新增引擎只需新增一个 `*_engine.py`；自研 Gemini Mask 方案——多模态视觉定位 + 本地按原图分辨率切割，支持掩膜 PNG 与多边形坐标两种输出，显著降低 Token 成本。支持批量拖拽处理与一键打包、HTTP 代理（含 Basic 认证）与连通性一键测试；前端玻璃拟态深色主题 + Framer Motion + PWA；提供 Docker / nginx / systemd 一键部署、macOS 桌面启动器与 .app 封装、GitHub Actions CI。
- **Format Converter（万能格式转换 Web 服务）**：文档（PDF / DOCX / MD / HTML / EPUB / RTF）、图片（JPG / PNG / WEBP / SVG…）、音频、视频、数据（JSON / YAML / CSV / TOML…）5 大类 30+ 格式互转；后端 FastAPI RESTful + python-docx / weasyprint / PyPDF2 / ffmpeg / Pillow 等引擎，前端 React 18 + Three.js 3D 互动角色（多模型切换、拖拽 / 点击 / 睡觉 / 心情系统）、玻璃拟态 UI；Swagger / ReDoc 自动文档；Docker Compose 或 OpenResty + systemd 部署。
- **git-mirror（CLI）**：任意两个 Git remote 之间双向全量同步（全分支 + 标签），自动凭据管理与多仓库规则，可 crontab 定时执行。
- **solar-system（玩具）**：单 HTML 零依赖 3D 太阳系模拟器（八大行星 + 冥王星 + 小行星带 + 土星环），可拖拽视角、点击查看行星信息。

### 3. Rental Registry —— 出租房登记信息管理系统 ｜ 独立开发

GitHub: https://github.com/zhcnhan/rental-registry ｜ 原生 HTML / CSS / JavaScript（零依赖、无构建、离线可用）

面向真实使用场景的工具型产品（为房东 / 中介登记出租房而做）：

- **信息管理**：房源地址、押金 / 租金、租户姓名、联系方式、身份证、起止日期等字段化录入；多条记录增删与切换；一键空置标记（表格红色高亮 + 水印醒目）。
- **自动生成规范表格**：单条登记表 + 横向汇总表，长文本自动换行格式不乱；内置经典蓝 / 清新绿 / 暖橙 / 典雅紫 / 商务灰 5 套配色模板。
- **文档导出**：基于 docx.js（本地化）生成真正可编辑的 .docx，手机 / 电脑均可打开；PDF 走浏览器原生打印引擎，分页精准不截断；老人阅读模式（大字号、高对比度）适配手机。
- **隐私与持久化**：数据存浏览器 localStorage；租客数据通过 .gitignore 排除、绝不进入仓库；支持 JSON 备份导出 / 导入。

## 工作经历

> 占位示例 —— 请用真实经历替换本段（若以开源项目为主要展示，可直接删除本段）。

[公司名称] — 全栈开发工程师 ｜ [城市] ｜ [起止时间]

- [一句话说明业务背景与你的职责范围]
- [负责的核心系统 / 模块，使用的技术栈]
- [代表性业绩（尽量量化，如接口 QPS、页面性能、业务指标提升）]

## 教育背景

[学校名称] · [专业] · [学历] · [起止时间]

## 其他

- GitHub: https://github.com/zhcnhan —— 个人作品集中展示于 toolbox（MIT，多应用 Monorepo）与 MathFeynman，另维护面向真实场景的 rental-registry。
- 保持稳定的开源提交节奏；技术兴趣横跨 Web 全栈、图形 / 3D、AI 应用工程化，习惯把想法做成"小而美、能落地"的工具。
- 可用中英文技术文档交流，具备独立阅读英文技术资料与开源代码的能力。

---

> 说明：本简历基于 GitHub 公开仓库内容生成（toolbox / MathFeynman / rental-registry）；所有 `[ ]` 占位内容（联系方式、工作经历、教育背景等）均来自站外信息，请投递前替换为真实内容。文中未虚构公司经历、学历或量化业绩。
