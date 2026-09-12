# 06 · 后端 API 草案与数据模型
> 适用范围：范围：API 现状（math 形态端点）。subject 命名空间改造见 docs/14 Phase A

> 供前后端联调与实现参考。签名可微调，但**语义与状态流转必须符合 docs/03、docs/05**。
> 所有端点默认前缀 `/api`，JSON 通信。**错误响应统一嵌套体**（2026-09-09 起，R19 块2）：
> `{"detail": {"error": {"code": ..., "message": <中文人话>}}}`；校验错误与未捕获 500 均走全局
> 处理器输出中文 message（不暴露英文堆栈）；前端对无文案/网络错误另有中文状态兜底（docs/13 §2）。

## 1. REST 端点草案

### 图谱与仪表盘
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/graph` | 全图（节点+边+状态），前端渲染图谱（C3：停用学科内容节点/边按 subject.enabled 隐藏） |
| GET | `/nodes/{node_id}` | 节点元数据 + content 摘要（不含答案） |
| GET | `/dashboard` | 今日复习队列、当前推荐节点、累计统计、断点清单（捡拾结果）；C3：推荐/统计/复习仅在启用学科节点内收敛（停用学科隐藏）；**R36 L1**：新增 `preset_subject: {id,label,enabled}\|null`——预置学科生命周期状态**直出**（前端据此显示"预置学科已停用"中文横幅，不再从 `/subjects` 反推） |

### 学科与大纲（docs/14 Phase A A1 起；math 为预置学科，通用学科=用户自建）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/subjects` | 学科列表（含大纲摘要：revision/status/units/组） |
| POST | `/subjects` | 创建自定义学科（body: label/description/subject_id?，id 须 `^[a-z][a-z0-9-]*$`） |
| GET / DELETE | `/subjects/{subject_id}` | 学科详情 / 删除自定义学科（preset 不可删） |
| GET | `/subjects/{subject_id}/outline` | 当前大纲全文（审阅；无大纲 404） |
| PUT | `/subjects/{subject_id}/outline` | 采纳/整份重生成（custom；revision+1；结构校验：唯一/自指/环/引用/**R36 P1 难度不得倒置（roadmap 源豁免）**）；**R36 D3**：服务端按各单元 `materials[].title` 反查 material_id 写入 `source_materials`（引用不存在的材料 → 中文 422）；**R37 S2/S7**：**教材章节全覆盖校验**（地图条目未映射 → 中文 422"教材覆盖不全"）、材料文本层不合格 → 中文 422 |
| POST | `/subjects/{subject_id}/outline/validate` | 校验候选大纲（不落盘，返回问题清单，UI 预览用；按 `source` 生效 P1——roadmap 源豁免） |
| PATCH | `/subjects/{subject_id}/outline/units/{unit_id}` | 单元局部改（custom 任意白名单字段；preset 仅 concept_tags 等附加字段） |
| POST | `/subjects/{subject_id}/outline/regenerate` | 大纲重生成：math=roadmap 派生 revision+1；custom=重新起草候选（不落盘，采纳 PUT 才 +1；**同样注入引用材料**） |
| POST | `/subjects/{subject_id}/outline/draft` | AI/启发式起草大纲候选（body: brief/count/group_hint；LLM_API_KEY 时走 CALL_OUTLINE_DRAFT，否则离线启发式；不落盘，供审阅后 PUT 采纳）（A4）；**R36 D1–D4**：注入该学科引用材料，要求逐单元 `materials:[{title,section}]` 溯源并服务端校验（不成立 → 驳回重生成一次 → 仍不成立则剔除并记问题）；**R37 S1/S2/S8**：默认**不设注入预算**（`MF_MATERIAL_INJECT_MAX_CHARS=0`；>0 时它是**单次调用预算**，只改"每批装多少"、**不丢章节**——R38 §3 共存口径），按 `outline.bookmap` 的**章→节地图**注入**完整正文**，书太大按 `MF_MATERIAL_BATCH_CHARS` 在章/页边界**分批**（绝不"前 N 字"）；单元由书序派生并按书序重排/重编号（`notes` 记录规范化决定）；每个章/节条目必须映射到 ≥1 个单元（未映射者先确定性回捞、再按教材目录补齐并记 `problems`）；**扫描/图片版（文本层不合格）→ 中文 422**；响应含 `source_materials`、`material_usage{count,used_chars,per_call_chars,batch_count,dropped(=恒空),truncated(=恒 false),batches,blocked}`、`coverage{total,covered,uncovered}`、`notes` |
| POST | `/subjects/{subject_id}/units/{unit_id}/content` | 懒生成单元内容（source:auto 落盘 + 库/DB 同步，幂等；仅 custom 学科；math 走 roadmap 流水线）（A4）；**R37 S3/S4/S5**：注入该单元对应教材章/节的**完整正文**；事实句与题目引文必须**逐字出自教材**，否则丢弃该题 / 整单元失败（`status="uncovered"`，中文 note，**不落盘**）；响应含 `coverage{status:完整\|部分\|未覆盖, grounded_facts, dropped_facts, dropped_exercises, sources, note}`；**R56**：图示教材模式（`all_ai`）的学科**走本模式分支**——`mode_lesson` 写讲解、`mode_exercise` 出题（标准答案与解析由模型给），落成与文字路径同一种节点文件（题目 `check.mode="ai"`，判对错由模型做），`note` 写明"全 AI 模式…没有独立的第二次核对" |
| GET | `/subjects/{subject_id}/coverage` | **R37 S6 覆盖账本**：`total/covered/uncovered`（章/节条目 ↔ 单元映射）+ `materials[{healthy,structure_kind,structure_note}]` + `entries[]` + `units[{sources,status,note,grounded_facts,dropped_exercises}]`（大纲页同源展示）；**R38 B1**：增 `by_material[]`（**按材料分组**的已覆盖节/总节 + 未覆盖清单）、`uncovered_by_material[]`、`uncovered_materials[]`（整份未纳入）、`order_basis`（顺序依据：角色/导入顺序）、`page_total/page_covered`（**章级统计、页级可下钻**）、`entries[].pages[]`；**R42 A3**：增 `not_injected[]`（**三种原因**：健康度不合格 / 未进批次 / **总注入上限**）、`inject_cap{configured,cap,used_chars,remaining,skipped_count,skipped_labels,skipped_by_material}`、逐条 `entries[].not_injected_reason/reason_zh`、`by_material[].cap_skipped*`——**因总上限未注入的章节不计入覆盖**（"没喂给模型"谈不上覆盖），每一处都能解释"它去哪了"；**R42 B1**：增 `skipped_short{count,labels,items,min_chars}`（过短条目，**不计入 uncovered 缺口**）+ `entries[].short`；**R42 B4**：`units[].basis_section/basis_quote/basis_note`（**章内该节级**依据，取不到为空——不编造）；**R54 C**：`units[]` 再增 `has_content/usable/content_reason_zh/exercise_count/taught_fact_count`（单元有没有内容、能不能学——与 `/session/*` 的内容守卫**同一实现**）；**R55 A/B**：`by_material[]` 增 `health_grade/health_summary_zh/image_count/figure_unavailable[]/figure_unavailable_count`（这份材料抽得好不好 + 哪些章/节引用了图/表、系统读不到图），`units[]` 增 `figure_unavailable`（这一节内容基本都在图里 → 没出内容，与"还没生成"区分开） |
| GET | `/subjects/{subject_id}/budget` | **R38/R42 材料注入预算视图**（学科管理卡材料区）：`batch_chars{value,source,source_zh,set}`（**单次调用预算＝滑块 A**）、`inject_max_chars{…}`（**总注入上限＝滑块 B，真硬上限**；0=不限）、`per_call_chars`、`tiers{batch,inject}`（档位）、**`promises_zh{batch_chars,inject_max_chars}`（两个滑块各自的承诺，界面直接渲染）**、`last_usage{used_chars,batch_count,per_material[],not_injected[],order_basis,summary_zh,note_zh, cap_skipped_count,cap_skipped_labels,cap_skipped_by_material,cap_note_zh}`、**`inject_cap{configured,cap,used_chars,remaining,skipped_count,skipped_chars,skipped_labels,skipped_by_material,first_batch_over_cap}`**、`context_valve{applied,context_tokens,limit_chars}`、`materials[]`；**R42 A3-⑤**：触发总上限时必显"因总上限未注入的章节数"（不许两处都没有） |
| PUT | `/subjects/{subject_id}/budget` | **R38/R42 两个滑块改值**（body `{batch_chars?, inject_max_chars?}`；单位＝字符，**0=不限**；落 `subjects.meta_json`，**不新建表**）；**立即生效**且回读一致；非法值 → **中文 422**；优先级：单次请求参数 > 学科滑块 > `.env` > 内置默认。**R42 语义分开**：滑块 A 调小＝只分更多批（**绝不丢章节**）；**滑块 B＝真硬上限**（超了真的不再注入，但每一处未注入都有中文账目 + `not_injected` 显式列出） |
| PUT | `/subjects/{subject_id}/materials/{material_id}/role` | **R38 B2 材料角色**（body `{role: main\|supplement}`）：主教材定顺序与范围、补充材料只补细节与例题；未标注 → 按**导入顺序**并在覆盖账注明 `order_basis=导入顺序`；非法角色 → 中文 422 |
| GET | `/subjects/{subject_id}/ledger` | **R39 §1 学科就地账目**（材料页/大纲页/单元页"看全部"入口）：该学科的账目（时间倒序）+ `counts`（按类别计数） |
| GET | `/subjects/{subject_id}/progress` | 学科进度视图（单元 达成/等效/开放 + 内容节点状态；A2） |
| POST | `/subjects/{subject_id}/progress/recompute` | 幂等重算概念掌握证据（= 数学历史掌握迁移入口；A2） |
| POST | `/subjects/{subject_id}/progress/reset` | 显式重置学科进度（清概念层 + 学科内容掌握；body `{mode: all}`；A2） |
| GET / PUT | `/subjects/{subject_id}/policy` | 内容来源策略（ai/import/web/mixed，默认 ai；B3） |
| POST | `/subjects/{subject_id}/materials/upload` | 本地导入文本 → 本地引用库（B3；粘贴文本入口保留）。**R55 C3（只增字段）**：body 可带 `raw_text`＝**外部工具修正前的解析器原文**；给了且与 `text` 不同 → 另存 `*.raw.txt` 备查 + 材料注明"已做抽取修正"（不填＝没有留档，行为照旧） |
| POST | `/subjects/{subject_id}/materials/upload-pdf` | **PDF/文档上传**（multipart：title? + file）→ pypdf 分页/分节文本 → 引用库（kind=pdf；≤20MB 等限制、失败中文 422；C2）；**R37 S7**：响应含 `text_health{pages,chars,healthy,checked,note}`——无文本层/极稀疏 → `healthy=false` + 中文告知"请先 OCR 或改用文本版"（**不再静默**；该材料会被起草/采纳拒绝）。**R55 A/C**：`text_health` 再增 `extract{pages,chars,unrecognized,unrecognized_ratio,broken_space_lines,broken_space_ratio,broken_space_heavy_lines,broken_space_heavy_ratio,formula_symbols,images,image_pages}`（**抽取体检四指标**，在**原始抽取文本**上算）+ `grade`（`好\|一般\|差`）+ `summary_zh`（**中文"所以会怎样"**）+ `fixed`（是否做过抽取修正）+ `raw_file`（原始抽取留档文件名，空串＝没有）；注入给模型的是**修正后**的正文（正文去私用区乱码、合并被空格拆开的字），`*.raw.txt` 另存原始抽取 |
| GET | `/subjects/{subject_id}/materials` | 引用材料列表（含 kind：local/web/pdf、源文件名、**R37 `text_health`**、**R38 `role/role_explicit/role_zh`**；B3+C2）。**R55 A/C**：`text_health` 与上传接口同口径（`extract/grade/summary_zh/fixed/raw_file`），界面据此显示「体检」徽标与"已做抽取修正" |
| POST | `/subjects/{subject_id}/materials/upload-pages` | **R56 第 3 步 · 图示教材模式（全 AI 模式）导入**：multipart `title?` + `want?` + **R57 `pages?`（PDF 页范围，如 `1-5,8`）** + `files[]`（**页面图片** PNG/JPEG/WebP/GIF，或**直接给 PDF**；一次 ≤60 页）→ 逐页交给模型读（调用点 `read_page`，走既有审计）→ 用**既有材料层**入库（`kind=pages`、`mode=all_ai`、`page_count`）；**没配能读图的模型 → 中文 422 拒绝且不落库**；**R57：给 PDF 时先按页渲染成图片**（参数见 `/mode` 的 `pdf_render_options`；渲染组件没装 → 中文 422 + 两条替代路 = 自己导出图片 / 换能收 PDF 的服务商）；**R60 任务 A**：页数上限只约束**本次要读的页数**（给了 `pages` 就按范围算，没给才按整本算；单页体量保护照旧）；读不出来的页照样入库但如实标注（正文 + 账本 `pages_unreadable`）；页面记录另存 `*.pages.json`（含 `render{source,pages,width,dpi,format,bytes_avg,ms_total,cache}`）；**页面图片不落 `content/`**（PDF 进 gitignored 缓存目录）；返回 `{id,title,page_count,unreadable,pages,elapsed_ms,render,note_zh,boundary}` |
| POST | `/subjects/{subject_id}/materials/{material_id}/read-pages` | **R57 任务 A · 按需取页范围**：body `{pages?("7-9"), want?}` —— 从缓存里重渲染那几页（PDF 材料）或取原始图片（图片材料）**再读一遍**，按页合并（同页替换、新页追加，幂等）；变更进账本（`pages_reread`，中文）。**R59**：`pages="unreadable"` ＝ **一键重读"读不出来的页"**——只挑 `readable=false` 的页；**一页都没有时直接返回 `{count:0, reread:[], model_calls:0, note_zh, reason_zh}` 且不调模型、不记账**（已可读的页永不重读 ⇒ 天然幂等）；账本 `detail` 带 `trigger`(`unreadable`/`pages`) 与 `still_unreadable`；返回另有 `unreadable`（重读后仍读不出来的页）与 `note_zh`。**R60 任务 B**：页标签认不出页号（旧格式，如「封面」）→ **跳过并列出**（不再 422）：能定位的页照读，返回 `skipped`（跳过了哪几页）+ 账本 `detail.skipped`；一页都定位不到时**不调模型**但照样记一条 `detail.kind="pages_reread_skipped"` 的中文账目（"跳过不是静默"） |
| POST | `/subjects/{subject_id}/mode/outline/draft` | **R57 任务 B-① · 本模式一键起草大纲**：body `{brief?, count?}` → 走 `mode_outline` 提示词（依据是**页/图号**）；**不调**路径②的教材锚定/可答性/引文闸门；模型没提到的页**并进最后一个单元**并在 `absorbed_pages` + 账本（`mode_outline_absorbed_pages`）里如实列出；返回 `{units, note, page_count, absorbed_pages, uncertain, uncertain_reason, ledger}`，`units` 可直接喂给 `PUT /outline` 采纳 |
| POST | `/subjects/{subject_id}/materials/{material_id}/reparse` | **R55 C4**：给已有材料重做一次"抽取修正"（给 R55 之前导入的旧材料补做用）；**幂等**——第二次 `changed=false`；**不动原始上传文件、不动已生成的内容文件**；无留档时先把当前正文存成 `*.raw.txt` 再改；响应 `{id,title,changed,text_health}`；**确有改动**时记一条中文账目（`material` 类，「材料《X》· 重新整理文字」），导入时的修正同样记账（「材料《X》· 抽取修正」，`detail.kind` ＝ `extract_fixed` / `extract_reparsed`） |
| GET | `/subjects/{subject_id}/mode` | **R56 第 3 步**：当前学科走哪条路 + 能不能开图示教材模式：`mode`（`""` / `all_ai`）、`mode_label_zh`、`vision_ready`、`vision_note_zh`（中文原因，含"该去设置里把模型名改成什么"）、`vision_model`、`entry_zh`（导入处要展示的**诚实边界**：做什么 / 三条代价 / 长处 / "不比文字教材更可靠" / "要的是图片、PDF 本身不收"）；**R57**：再回 `pdf_render_ready` / `pdf_render_note_zh`（这台机器能不能**自动把 PDF 转成页面图片**；不能时给中文原因与两条替代路）与 `pdf_render_options{width,format,quality,dpi_cap,max_bytes,max_pages}`（渲染参数可配） |
| DELETE | `/subjects/{subject_id}/materials/{material_id}` | 删除单条材料（B3） |
| POST | `/subjects/{subject_id}/materials/search` | 联网候选清单（C1 provider 抽象：默认未启用 → `{items:[], note:中文提示, backend:{configured:false}}`（UI 标注"未配置检索后端"）；配 SearXNG → 检索 →（配 LLM_API_KEY）LLM 整理候选） |
| POST | `/subjects/{subject_id}/materials/select` | 勾选候选 → 本地化引用；`items[].fetch=true` 时抓取该公开网页正文入库（text/html、大小上限；失败回落摘要；不整本下载书籍）（B3+C1） |
| POST | `/subjects/{subject_id}/enable` | 重新启用被移除（停用）学科（B4） |
| GET | `/subjects?include_removed=1` | 含停用学科列表（管理"移除可恢复"；B4/C3） |
| DELETE | `/subjects/{subject_id}?hard=true` | 学科移除：默认=停用（隐藏+清进度——**math 亦清其全部学段内容节点进度**，大纲/内容/roadmap 留盘可恢复）；`hard=true` 仅 custom 连同文件删除（math 拒 hard）（B4/R22/C3） |

### 学习会话
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/session/start` | body `{node_id}` → 创建/恢复会话，返回状态机当前步与首批内容（讲解稿演绎结果可选异步）。**R18 总序门禁**：无既有会话而新建时校验蓝图总序（docs/09 R18）；越级 → `409 invalid_state`，detail 含"请先完成：<前置条目标题>"。既有会话恢复 / 练习·费曼续走 / 复习不受门禁影响。**R54 A/C**：内容不足（还没生成 / 讲解为空 / 事实依据全丢 / 没题）→ **不建会话**、返回 `step="content_missing"`（`payload.content_missing{kind,missing,reason_zh,node_id,node_title,subject_id,unit_id,can_generate,content_status}`）；前端据此就地提示 + 一键生成，**不进空会话**（以前这种情况是 404「节点不存在」） |
| POST | `/session/step` | body `{session_id, action, payload}`；action ∈ `ask_question / next / submit_exercise / request_hint / regen_explain / reissue_after_regen / feynman_submit / feynman_answer / challenge_start / challenge_begin / challenge_submit / challenge_cancel / challenge_abandon / finish / quit`（`next` = 阶段前进：讲解→例题→练习，见 docs/09 R1）。**R27 双提交分离**：`feynman_submit` = 完整稿（首讲/整合重讲）→ 整体评分；`feynman_answer` = 补答（只答当前追问，payload `answer`）→ 轻量缺口补答评估。**R35 S3 挑战题池**：`challenge_*` 五个动作（见 §2.2），**永不出现在默认流程**、不设额度/不计轮次/不影响任何进度。**R54 A**：内容不足时任何 action（除 `quit`）都只回 `step="content_missing"`（不调模型/不判题/不评分）；未看过讲解就提交费曼 → **退回讲解**并给中文说明 `payload.rewound_zh`。**R56**：图示教材模式的题（`check.mode="ai"`）由**模型判**——提交后 payload 带 `judged_by="model"` 与 `verdict ∈ correct\|partial\|wrong\|uncertain`；`uncertain` 时**不打分、不动进度、不换题**，给 `reason_zh` 中文说明并记一条中文账（"这次没判出来"）。返回：下一步 UI 状态 + 新内容 + 状态机事件流 |
| GET | `/session/{id}` | 恢复会话全状态（**不含**挑战题：挑战题只随 `challenge_*` 动作下发） |

### 练习与判题（幂等，供前端直接调用或经由 step）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/exercises/check` | body `{exercise_id, params_seed, user_answer, session_id?}` → 该学科判题器结果（math=sympy）+ hint（不泄答案） |
| POST | `/exercises/next` | body `{node_id, exclude_ids}` → 下一道题（模板渲染或 AI 变体） |
| POST | `/exercises/unanswerable` | **R35 S7**：「这题我没法答（讲解里没有）」→ 复用 `feedback` 表加 `kind=answerability`（不建表）；**不计失败/不扣分**，进护栏统计；auto 内容走既有重生成闭环 |

### 复盘（attempts 回看；**同一张表、同一套读法**，不新建存储）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/history/feynman` | 费曼口述历史（逐字转写 + 评分卡，docs/07 §2.3） |
| GET | `/history/challenge` | **R35 S3**：挑战题复盘（`attempts.kind="challenge"`；含 `verdict=abandoned` 的明确放弃记录）。仅复盘用，**不计入任何进度** |

### 复习
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/review/queue` | 到期复习列表（含堆积警示） |
| POST | `/review/submit` | body `{node_id, rating(1-4), answers[]}` → 更新 FSRS 状态，返回下个到期日 |

### 画像与配置
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/profile` | 画像（错误类型、风格偏好） |
| PATCH | `/profile` | 用户手动调整偏好（解释深度等） |
| GET | `/config/models` | 当前模型分级配置（供设置页显示，不改密钥）。**R56**：改读**生效配置**（页面设置 > `.env` > 默认），并多回 `provider_label/api_key_masked/settings_path_zh`（**只回掩码**） |

### 内容管理（开发工具，MVP 阶段 CLI 为主）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/content/validate` | 运行全库校验并返回报告 |
| GET | `/content/drafts` / POST `/content/drafts/{id}/promote` | 审核 drafts（见 04 §6） |

### 一切显性 / 提示词 / 审计（**R39**）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ledger` | **总账（「一切显性」铁则的"一处看全部"）**：query `subject_id?/category?/limit?/offset?`；类别 ∈ `material\|generation\|model_call\|coverage\|other`（中文标签随响应给出）；时间倒序 + `counts`（类别计数）；类别非法 → `note` 中文提示（不 500）。**R54 B（只增字段）**：每条再带 `action`（可补救的记录 → `{kind:"regenerate_unit",label_zh,subject_id,unit_id}`，界面渲染成"重新生成这个单元"按钮；不可补救为 `null`）与 `resolved`（该单元后来已重新生成 → 这条旧丢弃记录已作废） |
| GET | `/ledger/cats` | 类别计数（筛选项徽标） |
| GET | `/ledger/snapshot/{subject_id}` | 某学科账目快照（就地提示的"看全部"入口） |
| POST | `/ledger` | 手动补记一条（前端动作也可入账；类别非法 → 中文 422） |
| GET | `/prompts` | **全部提示词调用点**：中文名 + 用途 + `is_default` + `updated_at` + 当前值 + 与默认的差异 `system_diff` + 必填占位符/硬约束清单；`changed` 列出已改的调用点。**R52 A2（只读新增字段，不改既有字段）**：`system_shared_with` / `user_shared_with` ＝ 与**其它**调用点"当前模板文本完全相同"的个数（0＝本调用点独有）；实测 15 个调用点只有 6 份不同 system（最大一组 10 处共用）、15 份 user 互不相同 |
| GET | `/prompts/{call_name}` | 单条（含 `raw_template` = **可编辑模板原文**（带 `{占位符}`）；`default_system` = 渲染后的可读默认值；**R42 C2**：`raw_user_template`/`default_raw_user_template`/`user_required_placeholders`/`user_required_tokens` —— **user 模板同样可编辑**） |
| PUT | `/prompts/{call_name}` | 保存（body `{system?, user?}`；**两者都可改**，未给的字段保持原样）；**改动立即生效**；缺必填占位符/硬约束、或模板花括号不合法 → **中文 422 拒绝保存**；成功 → 记入账本 |
| POST | `/prompts/{call_name}/reset` | 恢复默认（body `{field: ""\|system\|user}`）——**R42 C2**：可按字段恢复（只回退 user 不影响 system） |
| POST | `/prompts/reset-all` | 全部恢复默认（前端恢复前确认） |
| GET | `/settings` | 应用设置：`developer_mode`（**调试模式开关**）+ **R56 `model`**（模型与 Key 的当前状态，只回掩码）+ `ai_trace{dir,keep_days}` |
| PUT | `/settings` | 改开关（body `{developer_mode}`）；**审计本身默认记录**，开关只决定界面入口是否出现 |
| GET | `/settings/model` | **R56 第 0 步 · 模型与 Key 的当前状态**：`provider/provider_label/providers`、`configured`、**`api_key_masked`（只回前 3 位 + 后 4 位，永不回完整 Key）**、`api_key_source_zh`（你在这里设的 / .env 配置 / 程序默认）、`base_url/heavy/light/max_tokens_per_day`（各带 `*_source_zh`）、`memory_only`、`key_notice_zh`（"Key 存在本机、别把数据文件发给别人"）、`need_key_zh`（没配 Key 时给界面用的中文指引） |
| PUT | `/settings/model` | **保存模型设置**（只改传进来的项；`api_key=""` = 清除；**R57 增 `vision_model`** = 读图用的模型，留空＝跟随快档）；优先级＝**页面设置 > `.env` > 内置默认**；变更**进唯一账本**（中文，**不含 Key 明文**，只记后 4 位掩码）；`memory_only=true` 时 Key **只存进程内存、不落库** |
| POST | `/settings/model/test` | **「测试连接」**：发一次最小请求，中文报告成功/失败原因（Key 被拒 / 地址或模型名不对 / 限流 / 连不上 / 超时），**不含 Key** |
| GET | `/ai-traces` | **AI 对话审计列表**（query `subject_id?/call_name?/outcome?/only_failed?/limit?/offset?`）：时间倒序、**失败与丢弃置顶**；每条含 时间/调用点/档位/模型/token/耗时/重试/结局/`trace_path`+`trace_chars`+三段预览+`prompt_versions`。**R44 A**：`trace_path` 的文件名形如 `<UTC 时间戳>-<调用点>[-NN].txt`（同一秒内对同一调用点的多次记录用 `-02`/`-03`… 序号，**每次调用各自独立成文件、绝不覆盖**；目标名被占用时换名并**记入总账**（`other` 类，中文原因）。契约本身未变） |
| GET | `/ai-traces/{id}` | 单条完整对话：`full{system,user,response,parse_result,meta}`（**上=发给 AI 的完整内容，下=AI 返回的完整内容**，读全文文件；文件缺失 → `note` 如实说明 + 预览兜底）；**非流式** |
| POST | `/ai-traces/cleanup` | 按保留期清理审计全文文件（body `{keep_days?}`）；**先记账（清理了哪几条）再删除**（不静默消失）。**R48 B**：与启动/定时**同一实现**，响应与账目 `detail` 都带 `trigger`（`启动` / `定时` / `手动`），便于分辨"这次是谁清的"；其余字段与文案不变 |

## 2. `/session/step` 的响应协议（前后端契约要点）

```jsonc
{
  "step": "practice",            // 状态机当前阶段 explain|example|practice|feynman|done
  "payload": { /* 依阶段而定：讲解文本 / 例题 / 题目对象 / 费曼任务或追问 */ },
  "events": [                    // 供 UI 展示的流水（也用于测试断言）
    {"type": "exercise_correct", "node_id": "...", "consecutive_correct": 2},
    {"type": "hint_given", "count": 1},
    {"type": "feynman_passed", "score": 0.83},
    {"type": "node_mastered", "node_id": "..."}
  ],
  "session": {"id": "...", "state": "learning", "attempts_left": 3}
}
```

前端**无状态判断逻辑**：所有"下一步显示什么"由后端状态机裁决（防止前端逻辑分支漂移）。

### 2.0 费曼阶段 payload（R27 v3 混合制，docs/09 R27）

费曼阶段的 `payload` 恒带**缺口账本视图**（前端实时得分条数据源）：

```jsonc
"ledger": {
  "dimensions": [{"key": "correctness", "score": 0.88, "best": 0.88, "latest": 0.88,
                  "weight": 0.4, "evidence_quote": "…", "comment": "…", "updated_round": 1}],
  "combined": 0.69,      // 实时综合分 = Σ(w·账本维度最高分)/Σw
  "threshold": 0.7,
  "gaps": [{"key": "evidence", "description": "还差：说出任意一种观测/探测方法", "score": 0.1}]
},
"combined": 0.69, "threshold": 0.7,
"evals_done": 1, "eval_budget": 3,       // 整体稿评分：首讲 + ≤2 次终验
"answers_done": 0, "answer_budget": 2,   // 补答：≤2（须有未答缺口）
"next_action": "answer" | "submit",      // 有定向追问 → answer；否则 submit（交整合完整稿）
"followup_question": "…", "followup_gap": {"key": "evidence", "description": "…"},
"followup_quote": "…",                   // R35 S4：**逐字引用学生刚说的话**（服务端包含校验通过）
"followup_missing": "…"                  // R35 S4：这句话缺了什么（学生视角）
```

- `verdict`：`fail`（完整稿未达标，附本轮 `dimension_scores`）/ `gap`（补答结果，附
  `gap_filled`、`gap_key`、`gap_update`）/ `pass`（由 `mastered` + `feynman_passed` 事件体现）
  / `deferred`（评分服务不可用，进人工复核）/ **`reteach`（R35 S4：退回讲解补讲，见下）**。
- `dimension_scores[].evidence_valid`：服务端**包含校验**结论（引文必须逐字出自本轮提交文本，
  且归一化后 **≥6 字**——极短引文视为无效，R30 F5）；
  `false` 时该维度分数已降级（×0.5），并带 `evidence_reason`。
- **通过判定**：只有完整稿（`feynman_submit`）评分 ≥ threshold 才 pass → mastery；
  补答只涨账本与展示进度，不能单独过关（R27 §5）。
- **边缘带复评（R30 F6）**：完整稿单轮综合分落 `[threshold−0.05, threshold+0.08]`（0.7 → [0.65,0.78]）
  且本轮档位非 think → 以 think 档**复评一次**，取两次综合分较高者为本轮结果（每次提交最多 1 次额外
  heavy 调用；复评失败保留首次、不 500）。两次分与采用结论写入 `attempts.meta.recheck =
  {used, first_combined, second_combined, taken}`；响应 `strategy` / `strategy_reason` 为**实际采用**那次
  （复评被采用时 `strategy_reason="edge_recheck=think"`）。
- 事件：`feynman_followup`（定向追问，带 `target_gap`）、`feynman_reteach`（R35 S4：无可引用内容 →
  退回讲解补讲，带 `reason`）、`feynman_gap_filled` / `feynman_gap_open`、`feynman_evidence_flagged`、
  `feynman_relearn`（额度尽/3 次未过回炉）、`feynman_edge_recheck`（`{first, second, taken}`；
  复评失败时 `second=null`）、**`content_missing`（R54：内容不足以学，见下）**、
  **`need_explain`（R54：没看过讲解就想开讲 → 已退回讲解）**。
- **`step="content_missing"`（R54 A/C）**：`payload.content_missing{kind,missing,reason_zh,node_id,
  node_title,subject_id,unit_id,can_generate,content_status}` —— 响应里**没有** `lecture_md`/
  `exercise`/`task_prompt`/`rubric`（不给学习步骤、不给作答入口）；`can_generate=true` 时前端
  调既有出稿端点 `POST /subjects/{subject_id}/units/{unit_id}/content` 生成后重取会话即可。
- **`payload.rewound_zh`（R54 A）**：被前置守卫退回时的一句中文说明（只带一次），
  例如"你还没有看过这一节的讲解——先看完讲解，再讲一遍就能继续。"

### 2.0.1 追问纪律 `reteach`（R35 S4，docs/09 R35 §3 S4）

**追问必须先逐字引用学生刚说过的话**，并指出"这句话缺了什么"（`followup_quote` / `followup_missing`）；
学生**没有可引用的实质内容**（如只写"我不知道"）时**禁止硬造发散题**，返回：

```jsonc
"verdict": "reteach",
"next_action": "reteach",
"reteach": {
  "reason": "no_quotable_content | quote_not_verbatim | missing_not_stated | model_says_reteach | question_empty",
  "message_md": "📖 退回讲解补讲：…（中文说明，含「答不出不会逼你想」）",
  "lecture_md": "讲解原文（当场可回看）",
  "missing_dimensions": [{"key": "evidence", "description": "…"}]
}
```

- **不消耗额度**：`reteach` 不增 `evals_done`/`answers_done`、不动账本（敷衍回答不该吃掉评分预算）；
- **不翻转状态机**：阶段保持原样（练习已通过时"回到讲解"会**重新出题**并再次计入练习账目——
  等于用一次敷衍回答污染练习记录）；改为随响应下发讲解原文 + `next_action="reteach"`；
- socratic 主题**只有在 `socratic_basis` 逐字成立时**才作为追问语料下发（模板套话不得兜底）。

### 2.2 挑战题池（R35 S3，docs/09 R35 §3 S3）

**两个池**：核心题池（计入掌握与费曼）与**挑战题池（完全不上算）**。挑战题**永不出现在默认流程**，
由「挑战一下」按钮**用户主动触发、单独调模型生成**（`challenge_exercise` 调用点）。

```jsonc
// 五个动作（POST /session/step）：
// challenge_start    → 生成一道挑战题（payload 可带 think_deep）
// challenge_begin    → 开始作答（纯 UI 状态推进，无任何后果）
// challenge_submit   → 提交作答（payload {answer}）→ 单独判分
// challenge_cancel   → 取消本次（丢掉这题，**不写 attempts**）
// challenge_abandon  → 明确放弃（"我不会/我不感兴趣"，只记复盘）
"challenge": {
  "notice": "挑战题：需要讲解之外的知识，答不出不影响任何进度",   // UI 必须显式展示
  "phase": "idle | offered | answering | graded",
  "question": {"prompt_md": "…", "answer_hint_md": "…", "why_hard_md": "…", "difficulty": 3} | null,
  "last": {"correct": true, "score": 0.6, "feedback_md": "…", "better_md": "…"} | null,
  "asked": 1, "answered": 1,      // **仅展示计数**：不限额、不计轮次、不做任何门禁
  "degraded": false,
  "counts_nothing": true          // 契约位：前端不得据此渲染任何进度/分数影响
}
```

- 事件：`challenge_offered` / `challenge_begin` / `challenge_graded` / `challenge_cancelled` /
  `challenge_abandoned`。
- **红线（实现即验收）**：挑战题作答后 **mastery / 费曼账本（含整体稿与补答额度）/ 掌握统计
  四项均不变**，只写 `attempts.kind="challenge"`（复盘）。`/api/dashboard` 的 `today_done`
  按 `models.PROGRESS_KINDS` 白名单统计，**挑战题不计入**。
- **学科无关**：与核心题池走同一套链路（`context_block` 注入 + schema 校验 + 降级），
  无任何学科分支；挑战题**允许且要求**超出讲解（这正是它与核心题池的区别）。
- 生成与判分 = 两个独立调用点 `challenge_exercise` / `challenge_check`（均为 light 档）。

### 2.1 流式协议（R12-b，SSE 可选）

`POST /session/step?stream=1`（body 与普通 step 相同）返回 `text/event-stream`：

- `event: start` → `{"session_id", "action"}`；
- 处理期间每 ~1s 心跳：`event: ping` → `{"seconds"}`；
- 结束：`event: result` → **与普通响应完全一致的完整 JSON**（上文 §2 结构，契约不变）；
- 失败：`event: error` → `{"code", "message"}`（code 同 §4 错误码）。

约定：前端把流的 `result` 当作普通 step 响应处理；流不可用/解析失败/`error` 事件时
**自动回退普通 `POST /session/step`**；服务端同步逻辑跑在工作线程，不占事件循环，
LLM 等待前仍按 R7 先提交事务释放写锁。长文本（讲解/答疑回复/追问）由前端做打字机展示。

## 3. SQLite 表结构草案

```sql
subjects     (id TEXT PK, label TEXT, kind TEXT,       -- Phase A：kind=preset(math)|custom
              description TEXT, meta_json TEXT,        -- meta_json.source_policy（B3：ai/import/web/mixed）
              enabled INTEGER DEFAULT 1, removed_at DATETIME,  -- B4：停用标记（移除可恢复）
              created_at)   -- 大纲文档在 content/subjects/<id>/outline.yaml；材料在 <id>/materials/
users        (id TEXT PK, profile_json TEXT, created_at)            -- MVP 恒为 'local'
nodes        (id TEXT PK, yaml_path TEXT, title, level, topic,
              objectives_json, core_concepts_json, feynman_json,
              content_hash, enabled INTEGER)
edges        (node_id TEXT, prereq_id TEXT, PK(node_id, prereq_id))
             -- 内容库加载时由 `content validate` 写库，确保与文件一致（content_hash 校验）
user_nodes   (user_id, node_id, state TEXT,           -- locked/available/learning/mastered/reviewing
              consecutive_correct INT, attempts_total INT,
              last_error_type TEXT, mastered_at, PK(user_id,node_id))
sessions     (id TEXT PK, user_id, node_id, state TEXT,  -- 状态机当前步
              flow_json TEXT,           -- 会话内累积数据（练习计数、费曼轮次等）
              created_at, updated_at)
attempts     (id INTEGER PK, session_id, node_id, kind TEXT,   -- exercise|feynman|challenge
              exercise_id, params_json, user_input TEXT,
              verdict TEXT,             -- correct|wrong|score|pass|fail|deferred|gap_filled|gap_open|abandoned
              error_type TEXT NULL, meta_json, created_at)
              -- R35 S3：kind="challenge" = 挑战题（**只进复盘**）；进度统计一律按
              -- `models.PROGRESS_KINDS`（exercise|feynman）白名单过滤，挑战题不计入今日完成等任何统计
reviews      (user_id, node_id, state_json,            -- FSRS 状态
              due_at, last_rating, lapse_count, PK(user_id,node_id))
ai_logs      (id INTEGER PK, call_name, model, tier, prompt_tokens, completion_tokens,
              ok INTEGER, error TEXT, latency_ms, created_at,
              -- R39 §3：审计扩字段（旧库由 db._migrate_columns 幂等补列）
              subject_id, unit_id, retries INTEGER, outcome TEXT,   -- adopted|degraded|dropped|failed
              prompt_versions TEXT,                                 -- "哪次生成用的哪版提示词"
              trace_path TEXT, trace_chars INTEGER,                  -- 全文落 .runtime/ai_trace/
              system_preview TEXT, user_preview TEXT,
              response_preview TEXT, parse_result TEXT)
relearn_logs (user_id, node_id, reason TEXT, created_at)   -- mastered→learning 降级留痕
-- R39（新数据建表正当）：
content_ledger(id INTEGER PK, subject_id, unit_id, category TEXT,   -- material|generation|model_call|coverage|other
              object TEXT, reason TEXT,      -- 对象 / **中文原因**
              impact TEXT, remedy TEXT,      -- 影响面 / 可否补救
              detail_json TEXT, created_at)  -- 「一切显性」铁则的唯一落库点（service/ledger.py）
prompt_overrides(call_name TEXT PK, system_text TEXT, user_text TEXT, updated_at)
              -- R39 §2「所有提示词可在程序内修改」；空串 = 该字段用默认（删行 = 恢复默认）
              -- 不塞 subjects.meta_json（那是学科元数据）
app_settings (key TEXT PK, value TEXT, updated_at)
              -- R39 §3 运行时设置（developer_mode 调试开关；审计本身**默认记录**，与开关无关）
-- Phase A 概念层（A2 已落地，docs/14 §1/§2.2）：
concepts     (subject_id, concept_id, label, aliases_json, created_at,
              PK(subject_id, concept_id))          -- 概念标签注册表（归一化 concept_id）
user_concepts(user_id, subject_id, concept_id,      -- 掌握证据挂 (subject, concept)
              evidence_json,  -- 提供证据的内容节点 id 列表（派生，非人工）
              mastered_at, updated_at, PK(user_id, subject_id, concept_id))
```

- **subject 命名空间迁移方案（Phase A A1 已落地，docs/14 §1/§5）**：学科注册 = 新增 `subjects` 表
  （math 为 kind=preset 预置学科，启动幂等注册；custom 由 API 创建）；大纲文档按
  `content/subjects/<subject_id>/outline.yaml` 持久（schema v1，整份重生成 revision+1 原子替换）；
  **现有关键表（nodes/edges/user_nodes/sessions/attempts/reviews）不加 subject 列**——既有 content 节点
  隐含归属 math（level 语义保留，零 ALTER 兼容现库），subject 归属由大纲 ↔ 内容 id 映射反查
  （自定义学科内容节点 id 强制 `<subject>.` 前缀，全局唯一）。概念层与 (subject, concept) 掌握证据
  为新增独立表（A2）。
- 迁移策略：MVP 用 SQLAlchemy `create_all`（新表自动创建）；表结构变化时人工写 `ALTER` 迁移脚本放 `backend/migrations/`（不上 alembic，但结构保持文档同步）。
- 并发：本地单机单用户，无并发问题；但仍建议 SQLite `WAL` 模式。

## 4. 错误码（约定）

| code | 含义 |
|---|---|
| `not_found` / `invalid_state` | 会话已结束或状态非法（前端应刷新会话）；`/session/start` 的 `invalid_state` = **越级进入未解锁节点（R18 总序门禁）**，detail 含前置提示 |
| `ai_unavailable` | LLM 降级已发生（响应中带 `degraded: true`） |
| `exercise_broken` | 模板不可渲染（应触发 content 告警，不计入用户失败） |
| `validation_error` | 入参格式错 |
