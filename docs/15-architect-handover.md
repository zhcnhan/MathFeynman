# 15 · 架构师交接（Architect Handover）—— 本会话延续用

> 你是"架构师/费曼"角色的延续会话：负责**讨论、裁决、文档化、把关 Euler 汇报与路线**，
> 不写实现（实现归 Euler）。仓库内全部记忆外置，本文件 = 你的开机清单与当前状态。

## 1. 开机清单（新架构师按序执行）
1. 读 `README.md`（不可变决策、演进声明、文档导航）+ 各 docs 头部"适用范围"标签。
2. 读 `docs/09`（R1–R22 裁决史——你的决策依据链，务必读最新 R21/R22）与 `docs/14`（通用教练总纲，含 §8–§10 最新决策）。
3. 读 `docs/13`（Euler 交接，含行为公约：docs 唯一事实源、中文错误绝对要求、每步回归、git 提交）。
4. 读 `IMPLEMENTATION_NOTES.md`（实现运行日志，最新到 §3x）与 `USER_FEEDBACK.md`。
5. 其余 docs/01–12 按需精读（判题/状态机/AI 集成/总序/蓝图）。
6. **基线验证**：`pytest backend/tests` 期望 **291 passed + 2 skipped（离线；2 skipped=真模型冒烟，
   需 MF_ALLOW_LIVE_AI=1 + LLM_API_KEY）**（此后随新批上升）；
   `content validate` 绿；audit 5 学段全绿（27/31/81/59/60）；git 干净。
7. 与用户确认身份后，追加本文件"会话续接"记录（时间 + 基线）。

## 2. 角色纪律（你如何不“失忆地”工作）
- 一切结论落到 docs/09 新裁决（下一个 R 编号）+ 对应文档；一切进度/疑点让 Euler 落
  IMPLEMENTATION_NOTES。**文档是记忆，对话只做讨论。**
- 把关 Euler：每批回来先独立复跑（pytest/audit/validate/git），再给裁决（R 号）与放行。
- 维护规则常青：docs 唯一事实源；错误必须中文；Euler 每里程碑 git 提交；范围内改动前先改文档。

## 3. 当前状态（截至 2026-09-10 · 立心批已验收）
- 产品：通用费曼教练（docs/14）已过 Phase A（A1–A4，R19）、Phase B（B1–B5，R23）、Phase C（C1–C6，R24）；
  数学=preset（总 Outline 258 单元）；品牌 YanHui（颜回）全科教练；中文化（docs/13 §2）生效。
- 费曼语义：**v3 混合制**（R27 规格 / R28 验收 / R29 热修 / R30 边缘带复评 / **R31 验收通过**）。
- **立心批已完成并经 R32 验收**：身份级去数学中心化（提交 `92b6ff9`：产品定义 + 运行时 LLM 角色 +
  包描述 + README 立心）+ 代码内文案/注释清理（14 文件未提交工作树，零逻辑变更）+ 工作目录改名
  `MathFeynman` → `YanHui`。执行记录见 docs/09 R32 §3；流程纪律见 R32 §5。
- 基线（**R32 架构侧独立复跑**）：pytest **325 passed + 2 skipped**（327 collected，exit 0）；audit
  五学段全绿（27/31/81/59/60）；content validate 26/54；`npx tsc --noEmit` 通过；R32 工作树已提交
  （收尾提交 `4604fcf`），R33 复跑与此**逐位一致**（NOTES §52/§56）。
- **进行中/待办（最重要）**：
  a) **R33 小批（Euler 已执行完毕，2026-09-10 · 待架构侧验收）**：文档/配置一致性收尾——
     docs/02 目录树首行改为 `YanHui/` 并按实测补齐目录、docs/15 §7B 标记完成、旧名残留全仓复核；
     **库路径已归一**：库文件改名 `mathfeynman.db` → `yanhui.db`、`.env` 的 `MF_DB_PATH` 同步为
     `backend/data/yanhui.db`，迁移前后六项计数逐位一致（26/3/31/2/113/0）。
     ⚠️ 本批新发现**第二层根因**：`load_dotenv()` 默认不覆盖已有环境变量，而当前 DSH 进程环境里
     残留**进程级** `MF_DB_PATH=backend/data/mathfeynman.db` → 只改 `.env` 不生效（详见 NOTES §54；
     重启 DSH/新终端后自动消除）。执行记录见 IMPLEMENTATION_NOTES §52–§55；工单
     `.runtime/EULER_TICKET_INIT_R33.md`；
  b) **真人浏览器验收（用户动作）**：遗留会话 `s-f2decfcf.u01:a7689b7ebf` 走"首讲 → 补答 → 整合重讲"；
     真实 SearXNG 端到端、PDF 上传 UI、math 停用/重启用演示、材料可追溯重生成；
  c) 数学内容（roadmap 到段精核/内容懒生成）持续治理项照旧。
- 下一枚裁决编号：**R35 已出（可答性 · 产品级）；下一枚 R36**。

### 3.1 学习数据清空（用户指令 · 2026-09-10 由架构侧直办）

用户为**测试"生成大纲"**要求清空现有大纲/题库/进度，并**直接删掉行星科学**。执行与状态：

- **先归档**（不可逆操作前的退路）：
  `_backups\yanhui-before-wipe-20260910-170347\`（数据库三件套 + `stages`/`subjects`/`roadmap` 全量
  42 文件 + `db_snapshot.json` 全表导出）；清空后另存新基线 `_backups\yanhui-after-wipe-20260910-170452\`。
- **行星科学**：`DELETE /subjects/s-f2decfcf?hard=true` → 204（内容文件 + 大纲 + 材料 + 注册行
  一并物理删除）。
- **数学**：`DELETE /subjects/math`（preset 仅可停用）→ 204：`enabled=0`、进度与概念证据清空，
  **大纲/roadmap 留盘可重新启用**（258 单元大纲文件仍在）。
- **进度清空**：`user_nodes`/`sessions`/`attempts`/`reviews`/`user_concepts`/`feedback`/`relearn_logs`
  归零；3 行行星科学残节点（enabled=0）删除。
- **清空后新基线**：`subjects=1(math,禁用)`、`nodes=25`（math 内容）、`edges=28`、
  `concepts=83`（注册表，非进度），其余全 0；dashboard 全 0、graph 0 节点 0 边；前端 5173 正常。
- 另清掉 `content/subjects/` 下两个历史空壳目录（`s-14e1e9d1`、`s-3f9fbc5f`）。
- **数学未彻底删**（preset 不支持 hard；且它是"从零建学科"的对照）。若要走**纯白纸**（连 25 个
  math 内容文件一并清），属另一条指令。
- **运行期 auto 内容**（走查时生成的 `node_primary_s27_auto.md` 等）当前**未入库**；
  "auto 内容是否自动纳入 git"待用户定口径（架构侧倾向：纳入，因其即内容库）。


## 4. 常见口径（前车之鉴，直接沿用）
- 错误响应体嵌套 `{detail:{error:{code,message 中文}}}`；500 不裸堆栈（docs/06/13）。
- 判题 sympy L1（math preset）；语义走费曼 rubric；通用学科评估插件分 L1/L2/L3。
- 学科生命周期=移除可恢复；内容源策略 ai|import|web|mixed；材料=候选清单+本地导入（不整本下载）。
- 蓝图/大纲 status 为转正单一真源；总序权威（R18）；概念层管"换大纲不丢进度"（Phase A）。

## 5. 环境速查
- 服务 scripts\dev.ps1（前端 5173/后端 8000）；日志 .runtime\backend.err.log。

### 5.1 工作区清理（用户指令 · 2026-09-10 由架构侧直办）
- **删除（可再生）**：各 `__pycache__`（8 个目录）、`backend\.pytest_cache`、
  `frontend\node_modules\.vite`、`frontend\dist`（vite dev 下无用）、`.runtime` 的日志与 `pids.txt`、
  `resume\`（用户个人简历 2 文件）、`content\stages` 下 5 个**空**主题目录。
- **归档而非删除**：`.runtime` 与 `_dsh-local` 的**留档类**文件（历次工单 R27/R30/R32/R33、R27/R30 证据
  xml/txt、五学段蓝图起草数据、`使用说明.md` 等 53 个 / 378.9 KB）→
  `D:\DeepseekHarness\_backups\project-scratch-archive-20260910-162747\`。
  `_dsh-local` 仅保留**在用的启动器**（`start-dsh.cmd`/`.ps1`、`stop-dsh.cmd`/`.ps1`、`使用说明.md`）。
- **明确保留**：`backend\yanhui_backend.egg-info\`（用户指定保留，editable 安装元数据）；
  `content\subjects\s-14e1e9d1|s-3f9fbc5f`（空，属"学科移除可恢复"的生命周期痕迹，非垃圾）。
- **清理后复核**：`content validate` **ok 26/54**；audit 五学段 **27/31/81/59/60** 且错误项全 0；
  用户数据 **26/3/31/2/113** 不变；服务 8000/5173 均 200。
- 体积效果：frontend 93.6 → 67.8 MB，backend 3.5 → 1.2 MB。**运行必需项（`.venv` 146 MB、
  `frontend\node_modules` 68 MB）与备份区均未动。**

### 5.2 启动/停止脚本加固（2026-09-10 由架构侧直办）

发现并修复 3 个真问题（`_dsh-local\` 为 git 忽略区，改动仅本机生效，故在此留档）：

1. **`scripts\stop.ps1` 只杀 `pids.txt` 登记 PID，不杀子进程树** → 前端 `cmd → npm → node(vite)` 的
   真正服务进程会变成**孤儿**继续占 5173（实测复现）。**已改为递归杀整棵子进程树（由深到浅）
   + 按命令行兜底清理 `uvicorn app.main` / `frontend\node_modules...vite`**。
   实测：停止后 8000/5173 **无监听、孤儿 0 个**（注意：刚停时的"仍在响应"是 TIME_WAIT 假象，
   等几秒再判定）。
2. **`_dsh-local\start-dsh.ps1` 按"npx 缓存目录时间戳"挑版本**（`Sort-Object Stamp -Descending`）
   → 时间戳极易被复制/解压改变，一个"看起来更新"的旧缓存会压过真正更新的版本（这正是 0.1.2 事故
   能复发的机制）。**已改为读各缓存 `package.json` 的 `version`、转成补零排序键按版本号取最新**
   （多份缓存时打印全部候选）。实测：`Using cached DSH v0.1.5-rc.1` ✅。
3. **`_dsh-local\stop-dsh.ps1` 只杀端口监听者、不杀其子进程树**（DSH 的 subprocess runner 会被留下），
   且 `Get-NetTCPConnection` 失败时无兜底。**已改为：端口监听者→整棵树，netstat 与
   "命令行匹配 `bin.js web`" 双兜底。**

**附带纪律（再次踩到）**：`.ps1` 含中文时**必须有 UTF-8 BOM**，否则 Windows PowerShell 5.1 按 ANSI
解码 → 中文注释变乱码 → **整脚本语法错误**（本轮 `stop.ps1`/`stop-dsh.ps1` 都因此一度解析失败，
补 BOM 后 4 个脚本解析错误数全为 0）。纯 ASCII 的脚本（如 `start-dsh.ps1`）无此问题。

**4. `start-dsh.ps1` 端口占用诊断（可读性加固）**：原先只要 3080 有任何 HTTP 响应就断言
"already serving DSH"，不说**是谁占的**。现改为：
- `Get-PortOwnerInfo`：`Get-NetTCPConnection` → `netstat -ano` 双路取监听者 PID + 名称 + 命令行；
- `Test-DshServing`：探 `/api/health`（DSH 返回 JSON；401 亦视为 DSH），
  经此区分"真是 DSH"与"别的程序占了 3080"；
- 真 DSH → 照旧只开浏览器并打印占用者；**非 DSH → 中文报错、打印占用者与 `taskkill /PID … /T /F`
  的解决办法、exit 1**；
- 顺带把 `-Port` 变成**真参数**（原先硬编码 3080，提示里却让人用 `-Port`，属自相矛盾）。
实测：3080（现役 DSH）→ 识别 `PID 2864 node.exe`；用普通 `http.server` 占 3999 →
`Test-PortBusy=True`、`Test-DshServing=False`、占用者 `python.exe` 正确列出。
- .env：LLM_API_KEY / MF_AUTO_EXTEND / LLM_MAX_TOKENS_PER_DAY；git 三端镜像 git-mirror（GitHub↔Gitee，
  仓库 zhcnhan/颜回（YanHui） 与 gengzisama/颜回（YanHui））。
- **备份政策（用户 2026-09-10 定，长期有效）**：
  1. **落盘位置**：一律 `D:\DeepseekHarness\_backups\`（**不再放桌面**）。
  2. **只备份"新版"**：备份源必须是**当前正在运行的 DSH 版本**（此刻 = `0.1.5-rc.1`，
     npx 缓存键 `b86ed90107c62dab`）所写的真实数据。**旧版（0.1.2）产生的缓存/救援副本一律不留档**——
     它们的格式与现行不兼容，留着只会造成"拿旧格式覆盖新数据"的二次事故。
  3. **命名带版本**：`dsh-full-<版本>-<yyyyMMdd-HHmmss>`（便于一眼分辨是哪一版的数据）。
  4. **标准动作**：**先复制 → 逐文件核对（计数 + 大小/哈希）→ 通过后才删原份**；顺序不可反。
  5. **不写脚本**：备份用现成工具（robocopy 等）逐步执行，**产出可复制的命令，不落 `.ps1` 文件**
     （教训：改名脚本 `rename-to-yanhui.ps1` 是本次会话数据丢失的肇事者之一）。
- 现存备份（唯一一份）：`dsh-full-backup-20260910-153523`（52886 文件 / 723 MB，内含 0.1.5-rc.1）。
- 旧版痕迹已全清（2026-09-10）：`0.1.2` npx 缓存（222.5 MB）已删；回收站已清空（302 项 / 约 4.45 GB，
  含肇事脚本 `rename-to-yanhui.ps1` 与旧显示名的 `MathFeynman验收清单.html`）。
- 用户是"架构师↔Euler"之间的唯一中继：你给指令文本，用户粘贴；Euler 汇报由用户带回。

## 6. 精神基调（用户立 · 2026-09-10 · 架构师须内化，非代码改动）

> 用户明确：这是**精神/取向**的调整，**不是改现有代码**。以下为裁决与文档清理时的判断基准。

1. **这是通用教练程序，不是数学工具。** math 只是一个 preset 学科；任何学科都走同一闭环——
   概念 → 讲解 → **用自己的话讲出来** → 被追问 → 拓展。命名、导航、文案、默认假设都不得以数学为中心。
2. **费曼学习法的核心终究是"学习"本身。** 讲给别人听、教别人、用自己的话复述，是**统合自己脑中知识点**
   的方式——它是学习方法，不是考核手段。分数、门槛、轮次预算只是**辅助信号**，不是目的；
   系统的意义是让人真的学会、讲得出，而不是把人卡在线上。
3. **"颜回"之意 = 举一反三、闻一知十。** 学到的东西要有机关联与拓展：自己的例子、边界、类比、
   迁移到别处。追问应**引发思考**（用户实测已认可"问得能引发思考"），而不是考背诵；
   对"拓展与迁移"应给正反馈，而非只用 rubric 扣分。

**由此形成的裁决取向**（今后 R 号裁决默认遵循）：
- 评价看三件事：**讲得出、讲得对、讲得开**；机制上尽量减少"审判感"；
- 遇到"严格 vs 体验"的取舍，优先让学习者愿意继续讲（除非伤及内容正确性）；
- 通用性优先：任何新机制都要问一句"换个学科还成立吗"。

## 7. 待办 · 立心后的目录与文档清理（**在 Euler R30 回执并由架构侧裁决之后执行**）

**用户指令**：下一轮工单回执回来后，调整清理所有文件与文档，做好上述思想调整；**不改现有代码逻辑**；
最好把工作目录名也改掉。

**A. 清理范围（用户 2026-09-10 定：文档为主 + 代码内文案/注释可改，逻辑不动）**
> **执行状态：已完成并经 R32 验收**（2026-09-10）。主体提交 `92b6ff9`；代码内文案/注释清理为
> 未提交工作树 14 文件（逐条复核零逻辑变更）。残留面（数学专属措辞/组件命名）列后续清理批。
1. 通读 README + docs/01–15，清除 math-only 时代残留表述与"数学默认"措辞，统一到通用教练口径；✅
1b. **代码内文案/注释**（前后端界面文案、提示语、docstring/注释里"数学中心"残留）可同步改写，
    但**不得改动任何逻辑、schema、常量语义**——判断标准：改后行为与测试结果完全不变；✅（部分）
2. 导航与标题去数学中心化（如 README 导航、docs/01 产品定位、docs/07 UI 文案）；✅
3. 历史裁决（R1–R30）**保持原样不改写**（它们是决策链证据），仅在必要处补"后续被 Rxx 取代"标注；✅
4. 记录本次立心于本文件 §6 与 README 演进声明。✅

**B. 工作目录改名（用户定名：`D:\DeepseekHarness\MathFeynman` → `D:\DeepseekHarness\YanHui`）**
> **执行状态：已完成**（2026-09-10），执行记录与核查见 docs/09 R32 §3；下列清单保留为**改名手册**。
执行前必须勘察的风险清单（改名会动到运行环境，务必按序）：
- ① 全仓 grep 绝对路径 `MathFeynman`（排除 `.venv`/`node_modules`/`.git`）→ 列出需同步的脚本/配置；
- ② `.venv` 内含绝对路径（`pyvenv.cfg`、`Scripts\*.exe` shebang）→ 极可能需**删除重建 venv**；
  **⚠️ 实测教训：重建后必须补 `pip install -e "backend[dev]"`，否则 pytest 缺失、基线不可复跑。**
- ③ 本机脚本（`scripts\dev.ps1`、`.runtime\pids.txt`、`_dsh-local\start-dsh.ps1`、快捷方式）；
- ④ **当前 DSH 会话与后台任务的 cwd 就是该目录** → 必须停服、并在会话外执行改名；
  改名后需重开会话/重新指定工作目录；
- ⑤ git 远端与镜像不受影响（`.git` 随目录搬移；确认 git-mirror 配置无绝对路径）；
- ⑥ 前端 `node_modules` 通常可随目录搬移，但需清 `vite` 缓存。**DB 是相对路径，但 `.env` 的
  `MF_DB_PATH` 会覆盖代码默认名**——改名时务必同步该值，否则旧库名残留、迁移静默不触发（见 R32 §3）。
  **✅ R33 任务 B 已执行完毕（2026-09-10）**：库文件已改名 `yanhui.db`、`.env` 已同步、六项计数无变化。
  **补充教训（勘察清单遗漏项）**：**进程环境变量也会覆盖 `.env`**（`load_dotenv()` 默认不 override）
  ——改名时若旧值还留在进程环境里，改 `.env` 仍不生效；排查见 NOTES §54。
- 验证：改名后跑 `pytest backend/tests`、`npm run build`、`scripts\dev.ps1` 冒烟 + 打开页面。

**C. 产出**：立心 + 清理与改名执行记录已正式化为 **docs/09 R32**（原拟编 R31，因 R31 已被 R30
验收裁决占用而顺延）；实现细节仍交 Euler 执行（R33 工单见 `.runtime/EULER_TICKET_R32.md`）。

## 8. 会话续接记录（架构师侧）

### #1 · 2026-09-10 · 颜回（YanHui 新任架构师 · 首棒）
- **用户身份确认**：项目主人（唯一中继：架构师 ⇄ Euler）。
- **基线复核（独立复跑，不采信汇报）**：pytest **325 passed + 2 skipped / 327 collected，exit 0**；
  content validate **26/54**；roadmap audit 五学段全绿（27/31/81/59/60）；`npx tsc --noEmit` exit 0。
  与 docs/13 §4 及 R31 记录逐位一致。
- **环境修复**：`.venv` 改名后重建漏装 dev 依赖 → `pytest` 缺失；已补 `pip install -e "backend[dev]"`
  （pytest 9.1.1 / pytest-cov 7.1.0）。受限沙箱内 `npm run build` 因 esbuild 子进程 EPERM 失败
  （环境限制，非代码问题），已记入 docs/13 §4。
- **本会话架构侧交付**：docs/09 **R32**（立心验收 + 清理/改名执行记录 + 流程纪律）；
  docs/13 §3/§4、docs/15 §3/§7 状态同步；`.runtime/EULER_TICKET_R32.md`（R33 派工）。
- **会话基础设施事故留档**：DSH 0.1.2→0.1.5 升级 + 工作目录改名 + 旧版误启动叠加，导致**旧会话
  chat 正文丢失**（项目文件零损失，仅过程流水）。已做预防：`.dsh` 全量备份（robocopy 权威比对
  Files 52886 / Mismatch 0 / FAILED 0）+ 旧版 0.1.2 缓存**双改名屏蔽**（目录名与 `bin.js` 双改，
  阻断启动器"探 `bin.js` 存在性"的发现路径），并以启动器自身算法验证唯一解析到 0.1.5。
  纪律见 R32 §5：**改工作目录名 / 切 DSH 版本 / 升级 DSH 三件事禁止同一时间窗叠加，且先备份 `.dsh`。**

### #2 · 2026-09-10 20:52 起 · 颜回（续接 · 第三棒）
- **交接来源**：用户直接投喂《架构师交接-下一个我》（无附带指令）→ 按 §0/§2 自主开工。
- **基线复核（架构侧独立复跑，不采信汇报）**，检定点 `50bdde7`（= R40 验收提交）：
  | 项 | 期望 | 实测 | 判 |
  |---|---|---|---|
  | `pytest backend/tests` | 404 passed + 2 skipped / 406 | **404 passed + 2 skipped / 406 collected，0 failed / 0 error，exit 0** | ✅ 逐位一致 |
  | `content validate` | ok 26/55 | **ok=True nodes=26 exercises=55**，exit 0 | ✅ |
  | roadmap audit 五学段 | 27/31/81/59/60 | **27/31/81/59/60，ok=True；cycles / prereq_missing / anchors_missing 全 0** | ✅ |
  | `npx tsc --noEmit` | exit 0 | **exit 0** | ✅ |
  | `guardrails.semantics_stats()` | {30,0,30,0,['math']} | **{templates:30, violations:0, verified:30, unverified:0, l1_subjects:['math']}** | ✅ |
  | git | 干净（除用户新学科未入库） | **仅 `?? content/stages/s-f2decfcf/`、`?? content/subjects/s-f2decfcf/`** | ✅ |
- **现场判定：Euler 正在并行开工 R39（未提交，进行中）**。20:52 首次 `git status` 时工作树**只有**
  两个 `??`（未入库的用户新学科）；20:59 复看时已出现 **R39 的实现文件**：
  `service/ledger.py`(257 行, 20:55)、`service/ai_trace.py`(337 行, 20:59)、`service/prompt_store.py`
  (181 行, 20:58)、`ai/prompt_templates.py`(594 行, 20:58)，改动 `models.py`(+71)/`db.py`(+21)/
  `ai/prompts.py`/`ai/provider.py`(+172)/`service/ai_sink.py`。**文件 mtime 20:55–20:59 与我复跑基线
  同一分钟** → 属**边写边测**的进行中状态，**不是可验收的完成态**。
- ⚠️ **本任自己的假阳性（必须记住）**：我曾据 20:52 那份 `git status` 快照断言"R38/R39 代码层尚未开工"，
  并已写进本节——**是错的**。根因：**把一次时间点快照当成稳态结论，且未在断言前二次确认**。
  与交接 §5"验收时先怀疑自己的检查口径"同源。**教训：对"某功能不存在"的断言，必须现场复跑
  `glob`/`grep` + 看 mtime，并假定并行协作者随时在改盘。**
- ~~**R38 状态**：`MF_MATERIAL_BATCH_CHARS`/`MF_MATERIAL_INJECT_MAX_CHARS` 仍只在 `config.py`（env 级），
  `subjects.meta_json` 与前端**尚无可控滑块**（A1/A5 未见落地）→ **R38 未开工或刚起步，待 Euler 回报**。~~
  → **已被推翻**：`f8f7ac9` 落地了两个滑块 + 多材料合并，并**顺带闭合 R40 §2-1**（见下方结项）。
- ~~**R40 遗留一条（重点追踪项）仍未实现**：`outline/generate.py:631` 离线路径**仍出稿**~~ →
  **已修正**：`f8f7ac9` 已改为**拒绝出稿**（我实测 422 + 中文 + 记账）。
- **【本节上文的"R38 未开工 / R39 进行中"是当时快照，已作废】**：该判断在写入后数分钟内即被事实推翻。
  最终状态见下方"#2 结项"。
- **本次未改动任何实现代码**（架构侧只做验证与文档）；交付：本节 + 基线留档 `.runtime/r41_baseline.xml`。

#### #2 结项 · R38 + R39 已验收（同一棒内完成）

- **提交**：`f8f7ac9`（R38）+ `8439fd8`（R39）。**裁决：双双通过** → **docs/09 R41**（含 §3 疑点裁决、
  §4 纪律事故留档、§5 观察项、§6 R40 五条遗留复核、§7 下一批建议）。
- **我的独立复跑**：pytest **441 + 2 / 443，exit 0**；content **26/55**；audit **27/31/81/59/60 错误项 0**；
  `tsc` exit 0；`semantics_stats` 逐位一致；`git diff 50bdde7 8439fd8 -- content/` **为空**（锚点红线守住）。
- **我另写的两个独立验证脚本（不复用 Euler 用例）**：`.runtime/verify_r41.py`（R38 · **18/18**）、
  `.runtime/verify_r41_r39.py`（R39 · **24/24**）。关键实证：滑块 A 60000→300 批次 1→4 且内容逐字不变；
  离线+有教材真拒绝出稿；删必填占位符中文 422 且不落库；改提示词后审计全文里确实是新版；
  12 万字 prompt 接口给全文而列表只给预览；上游回显的密钥在落盘文件中已遮蔽。
- **纪律事故（本任自己犯的，已复原，留档）**：在**并行活动的仓库**上做 `git stash` + `checkout --detach`
  + `checkout -f`，**丢了自己的工作树改动**（docs/15 本轮记录）→ 从 stash 悬空提交 `4ae98628` 已恢复，
  并全量复跑确认仓库完好。**新增红线：禁止在 Euler 正在工作的活动工作树里做 stash/checkout/reset**；
  数不同提交的设备数请用 `git show <rev>:<file>` 或 `git worktree add` 到隔离目录。
- **同时记下本任第二次假阳性**：据一份时间点 `git status` 快照断言"R38/R39 未开工"，
  数分钟后被推翻。**对"不存在"的断言，断言前必须现场复跑 `glob`/`grep` + 看 mtime。**
- **下一批 = R42**（建议见 docs/09 R41 §7）：滑块 B 真硬上限 + R40 遗留的"过短条目/难度显性"两项高危。

