# 04 · 内容库（content/）：格式、模板、生产流水线
> 适用范围：范围：通用学习单元流水线雏形 + 数学内容模板（subject 化与学科化 schema 见 docs/14）

> 内容库是与代码分离的**事实性知识源**（ADR A6）。所有"讲解给学生听的事实"、
> 例题、习题模板、费曼任务的依据都来自这里。LLM 只负责"演绎"（换措辞、生成变体、答疑），
> 不负责"发明事实"。

## 1. 目录组织

```
content/
├── stages/
│   ├── primary/  topic_01_分数/
│   │   └── node_0101_分数加法.md        # 一个 .md 文件 = 一个知识点节点
│   ├── middle/   topic_02_一元方程/...
│   ├── high/     topic_xx_导数/...
│   ├── college/  topic_xx_线性代数/...
│   └── ai/       topic_xx_概率统计/...
├── _meta/
│   ├── knowledge_graph.yaml            # 也可从各文件 front-matter 推导；两者择一为准，推荐由文件推导+显式 edges
│   └── schemas/                        # 校验用 JSON Schema / pydantic 定义镜像
└── manifest.yaml                       # 索引与版本
```

推荐：**节点文件的 front-matter 即节点定义**（含 `id`, `level`, `prereqs`），
图由 `content validate` 自动装配校验（重名 id、环检测、prereq 存在性）。

## 2. 节点文件格式（.md：YAML front-matter + Markdown 正文）

> **R35 可答性字段（2026-09-10，新增；旧文件缺省即可，不阻塞加载）**：
> ```yaml
> taught_facts:                    # S1 声明式知识包：本单元**显式陈述**的事实句（text 必须逐字出自讲解正文）
>   - {id: f1, text: 恒星是由自身引力维持并自行发光的巨大球体。}
> derivable:                       # S1 允许的推理（结论 + 依据的事实 id + 明确规则）
>   - {conclusion: 太阳比地球更近, premises: [f1, f2], rule: 比较距离}
> worked_examples:                 # A3：auto 出稿必须 ≥1（示范"如何合法作答"）
>   - {prompt: 例：太阳是什么？, solution_steps: [太阳是一颗恒星。]}
> exercises:
>   - id: b1
>     basis: {fact_ids: [f1], quote: 讲解原文里逐字出现的一句依据}   # S2 出题引文纪律（推理题另附 premises+rule）
> feynman:
>   socratic_followups: [太阳和地球哪个离我们更近？]
>   socratic_basis: [{fact_ids: [f2], quote: 太阳是离地球最近的恒星。}]  # 与 followups **按下标对齐**
> ```
> 判定：`app/content/answerability.py`（引文尺子＝`app/content/citations.py`，≥6 字）。
> 缺 `taught_facts` 的旧内容**不阻塞加载**，但**不得**通过可答性校验；生成端不合规的题**丢弃**（S5）。
>
> **R35 §12–§14 语义自检闸门 + 模板级依据（2026-09-10）**：
> ```yaml
> exercises:
>   - id: ex1
>     kind: template
>     template:
>       prompt: "已知 {b} 是 {a} 的倍数，求 {a} 和 {b} 的最小公倍数。"
>       constraint: "b % a == 0"                 # 必须强制题面说出的每一个条件
>       answer_expr: "b"
>       basis: {quote: "特别地，当 b 是 a 的倍数时，最小公倍数是 b。"}  # §14：**支撑本模板的那句规则句**
>       semantics:
>         expect: "lcm(a, b)"                    # 独立算式（L1 插件据此独立验算；不得与 answer_expr 同文）
>         requires: ["b % a == 0"]               # 题面陈述的条件（必须被 constraint 保证）
>         domain: {nonneg: true, integer: true}  # 通用层领域谓词（**内容显式声明**，不猜题面关键词）
> ```
> 三层闸门（`app/content/verify.py`，**学科无关是第一原则**）：① 通用层领域谓词（所有学科）→
> ② L1 验算插件（按学科注册，`math` 是第一个实例）→ ③ 无 L1 的学科**如实标注**"无独立验算"。
> 另含题面泄漏（答案原样出现在提示/示例片段）与**引文精度告警**（`basis.quote` 不得是开场白/过渡句；
> **告警不拒绝入库**，见 NOTES §66.1）。生成端入口：`pipeline.validate_semantics()`。

```yaml
---
id: middle.0102
title: 一元一次方程的求解
level: middle
topic: 代数·方程
prereqs: [middle.0101]          # 依赖节点 id
kind: normal                    # 可选：normal|boss —— 首领关卡（阶段 2：综合+费曼综述，docs/10 §2.1）
objectives:                     # 学习目标（费曼任务与练习的出题依据）
  - 能识别一元一次方程
  - 能通过移项、合并同类项求解并验根
core_concepts: [等式性质, 移项, 合并同类项]   # 讲解白名单基础（见 05 §4）
explanation:
  role: 教师讲解稿                # 人工撰写或流水线初稿，必须人工审核
  body: |
    （Markdown，含 $$...$$ LaTeX 公式。讲解本节点概念时 LLM 只能在此稿基础上演绎，
     不得引入 core_concepts 与 prereqs 之外的新概念。）
worked_examples:
  - prompt: "解方程：3x + 5 = 20"
    solution_steps:
      - "两边减 5：3x = 15"
      - "两边除以 3：x = 5"
    verification: "sympy: solve(Eq(3*x+5,20),x) == [5]"   # 可选，例题验算
exercises:
  - id: ex1
    kind: template                  # 参数化模板（默认）；或 fixed
    difficulty: 1                   # 1 基础 / 2 熟练 / 3 挑战
    template:
      prompt: "解方程：{a}x + {b} = {c}"
      params:                       # 随机取值范围/约束
        a: {range: [1, 9], exclude: [0]}
        b: {range: [-20, 20]}
        c: {range: [-20, 20]}
        # 生成时需满足可整除等约束时，写 python 表达式式约束：
        constraint: "(c - b) % a == 0"
      answer_expr: "x = (c - b) / a"      # sympy 可解析的答案表达式（参数代入后）
      check:
        mode: equation_solution            # 判题模式，见 §3
        tolerance: null
    interactive: [workbench]              # 适用交互模式，见 07 文档：workbench|guided|graph
  - id: ex2
    kind: fixed
    prompt: "判断 2x+1=2(x+1)-1 是否为恒等式，说明理由"
    difficulty: 2
    check: {mode: symbolic_equivalence, tolerance: null}
    interactive: [workbench, guided]
feynman:
  task_prompt: "用自己的话向老师解释：什么是一元一次方程的解？为什么移项要变号？并举一个反例说明错在哪。"
  rubric:                          # 费曼评分标准（AI 评分依据，见 05 §5）
    dimensions:
      - key: correctness           # 概念表述是否正确
        weight: 0.4
      - key: own_words             # 是否用自己的话而非背诵
        weight: 0.2
      - key: example_and_edge      # 是否给出例子/反例
        weight: 0.2
      - key: self_correction       # 被追问后能否自纠
        weight: 0.2
    pass_threshold: 0.7
    thinking: false                # 可选（R12）：本节点费曼/讲解固定用深度档（think）
  socratic_followups:              # 追问主题（AI 据此生成追问，允许生成变体）
    - "如果方程两边乘以 0 会怎样？为什么这不是合法的变换？"
    - "解方程和恒等变形有什么区别？"
---
（正文：本节点全文讲解、常见误区、例题详解——人工撰写或经审核的 AI 初稿）
```

## 3. 判题模式（check.mode）枚举

| mode | 含义 | sympy 实现要点 |
|---|---|---|
| `equation_solution` | 解方程，答案可为解集 | `solve(Eq(lhs,rhs), sym)` 与用户解集比对（无序、容差） |
| `symbolic_equivalence` | 表达式等价 | `simplify(a - b) == 0` 或 `equals()` |
| `numeric_value` | 数值结果 | 代入后 `abs(a-b) < tol` |
| `boolean_judgment` | 判断对错+理由 | 对错为真值；**理由由 rubric 评估而非全权判对** |
| `single_choice` | 选择题（Phase B B1/B2） | 固定题 options+answer_index(0 起)；作答接受编号/字母/选项文本，服务端判定 |
| `fill_text` | 填空题（Phase B B1/B2） | 固定题 expected+aliases（同义答法）；归一化（去空白/句末标点+小写）比对 |
| `ordering` | 排序/比较 | 数值比较（扩展预留） |
| `manual_review` | 无法自动判（如作图） | 走费曼式人工/AI rubric 复核队列 |

判题结果统一返回：`{correct: bool, feedback_hint: str|null, expected: str|null, detail: str}`。
`feedback_hint` 只在答错时给"哪一步可疑"的提示，不让 AI 直接报答案；答对给正向+变式邀请。

## 4. 模板渲染与出题变体

- `content/templates.py`：解析 `template.prompt`/`answer_expr`，在 `params` 约束下**确定性随机**取样
  （seed 可复现，便于测试与复现 bug）。
- 生成后**必须**先做三件事：① sympy 能解析答案表达式；② 约束成立；③ 代入答案后判题器返回 correct。
  失败则重取样（上限 N 次），全部失败 → 该模板标记 `broken` 并告警，**不允许入库**。
- LLM 变体（进阶功能，P1）：`gen_content.py` 可让 LLM 参照模板风格生成新模板草稿，但
  新模板同样须通过自动验算 + 人工审核 gate 才能入库（见 §6）。

## 5. 费曼任务与评分依据

- 每节点必须配置 `feynman`（task_prompt + rubric + socratic_followups）。
- rubric 维度在文档级声明（如上），AI 评分时逐维给分并输出理由与引用的学生原话片段
  （引文要求见 05 §5，防止瞎打分）。

## 6. 内容生产流水线（自我拓展机制）

```
[gen_content.py]
  输入：目标节点规格（level/topic/objectives/prereqs）
  → 1) LLM 按本文件 schema 生成 .md 初稿（含模板题与费曼任务）
  → 2) 自动校验：front-matter 完整 / 图无环 / 模板可渲染 / 每题 sympy 验算通过 / rubric 结构合法
  → 3) 失败项回灌给 LLM 修复（上限 2 轮）
  → 4) 输出到 content/_drafts/<id>.md   【未审核区，不参与运行】
  人工（用户）审核 drafts → 移入 content/stages/…  →  manifest 更新
```

- 运行库只加载 `content/stages/` 下文件；`_drafts/` 永不加载。
- 任何入库节点都要有 ≥1 条真实的人工审核记录（git 提交历史即记录）。
- **起步内容**（MVP）：由用户诊断后确定起点，首批覆盖 10–20 个真实中学节点，
  建议从"分数四则运算/负数/一元一次方程"这类断点高发区开始；这些首批节点建议**人工精写**（质量锚点），
  后续广度靠流水线。

## 7. 内容校验命令

- `python -m content validate`：全库结构/环/模板/验算检查，CI 化（开发期每次改动跑）。
- `python -m content render <node_id> <seed>`：渲染示例题供人工抽检。
