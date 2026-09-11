"""ai.prompt_templates：**所有**发往模型的提示词模板的单一注册表（docs/09 R39 §2）。

铁则配套：**所有**调用点（现有全部 + 未来新增）**一处不漏**地可在程序内修改并可恢复默认。
本模块只负责"模板是什么、占位符有哪些、哪些硬约束不许删"——落库/接口在
``service.prompt_store``，改造点在各调用点（``ai/gateway.py``、``outline/draft.py``、
``outline/generate.py``）。

模板语法与纪律：
- ``{placeholder}`` = 程序注入的占位符（``str.format`` 风格）；模板里要写**字面花括号**
  （如 JSON 示例）必须写成 ``{{`` / ``}}``——保存时校验会拦下裸 ``{`` 并给中文说明；
- **必须保留的占位符/硬约束**（如"输出必须符合给定 JSON 字段"）按字段分别声明：
  ``system`` 与 ``user`` 各有自己的 ``required_*``；缺一个 → **中文报错并拒绝保存**
  （否则改坏提示词会让功能**静默失效**，正是铁则要防的）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class PromptError(ValueError):
    """提示词模板错误（缺占位符 / 缺硬约束 / 渲染失败）→ 调用方转中文 422 或记账。"""


@dataclass(frozen=True)
class PromptSpec:
    """一个可编辑提示词模板（调用点 = ``ai.calls.CALLS`` 的键）。"""

    call_name: str
    label: str                 # 中文名（界面左列）
    purpose: str               # 用途一句话
    system: str                # system 模板
    user: str = ""             # user 模板（空 = 该调用点没有 user 模板）
    # 硬约束：占位符缺失 → 拒存（中文 422）——system / user 分别声明
    system_required_placeholders: tuple[str, ...] = ()
    user_required_placeholders: tuple[str, ...] = ()
    # 硬约束：字面 token 缺失 → 拒存（如 JSON 字段名/纪律关键词）
    system_required_tokens: tuple[str, ...] = ()
    user_required_tokens: tuple[str, ...] = ()
    notes: str = ""            # 界面提示（该模板的注意事项）

    @property
    def placeholders(self) -> list[str]:
        got: list[str] = []
        for src in (self.system, self.user):
            for m in _PLACEHOLDER.finditer(src or ""):
                if m.group(1) not in got:
                    got.append(m.group(1))
        return got


# ---------------------------------------------------------------------------
# 公共片段
# ---------------------------------------------------------------------------
JSON_DISCIPLINE = "[输出纪律] 只输出 JSON，字段严格符合给定 schema。"

# ContextBlock 的公共取值占位符（所有基于 context_block 的调用点共用）
CB_PLACEHOLDERS = ("level", "explanation_body", "worked_examples", "whitelist", "bans", "style")

_MATERIAL_DISCIPLINE = (
    "**必须读教材（R37 S2/S3，教材＝权威真源）**：下面是用户为该学科导入的**教材章节正文**。"
    "你起草的大纲就是**这本书的目录**：单元顺序＝书的顺序，单元内容＝该章节讲的东西；"
    "**不得引入教材之外的知识点**（教材没写的，不要写进目标/标签）。"
    "每个单元必须标注 `materials` 溯源：title **只能**取下方给出的材料标题；"
    "section **必须逐字复制**下方章节地图里的**条目标签**（方括号 `[...]` 里的文字，如 "
    "\"[第3章 太阳加热与能量传输]\"）——这是服务端覆盖校验的钥匙，改一个字都会被判未映射；"
    "无依据就留空数组 []——宁缺勿造，编造的溯源会被服务端驳回。"
    "**合并**：相邻的小节/附录可以合并进一个单元，但 `materials` 必须把**被合并条目的标签全部列出**；"
    "**拆分**：一个章太大时可以拆成多个单元，每个单元都标注同一个章标签，"
    "并在 `objectives` 里写清「拆自该章的哪部分」。"
)

_UNIT_MATERIAL_DISCIPLINE = "\n**本单元对应的教材段落**：必须逐字引用其中的句子作为事实与依据。"

# ---------------- 14 个调用点的模板（与 ai/calls.py 的 CALLS 一一对应） ----------------
S_EXPLAIN = (
    "[角色] 你是本学习系统的学科导师（任何学科同一套要求），面向{level}学生。\n"
    "[教学内容真源] 以下是本节点官方讲解稿，只能在此基础上演绎，不得改动事实：\n"
    "{explanation_body}\n"
    "[例题原文]\n"
    "{worked_examples}\n"
    "[概念白名单] 允许涉及的概念：{whitelist}。\n"
    "[禁令] {bans}\n"
    "[风格] {style}\n"
    "[公式输出纪律] 涉及数学公式时必须满足："
    "① 显示公式用 $$...$$ 且**单独成行**（公式所在行除 $$ 外不得有其它文字）；"
    "② 行内公式用 $...$ 且**不得跨行**（单个 $...$ 内禁止包含换行符，公式不要折行书写）；"
    "③ 所有 $ 定界符必须成对闭合，禁止孤立/杂散的 $ 或 $$；"
    "④ 讲解文本不得夹带孤立 $$（前后无成对内容即视为孤立，必须删除）。\n" + JSON_DISCIPLINE
    + "讲解正文除 LaTeX 公式外的行内代码/符号用反引号包裹。"
)

U_EXPLAIN = (
    "输出 JSON：\n"
    '{{"lecture_md":"…","asked_to_confirm":["…"],'
    '"asks_basis":[{{"fact_ids":["f1"],"quote":"讲解原文里逐字出现的一句依据"}}]}}\n'
    "任务：基于讲解稿为本节点写一份适合该生（考虑风格块）的演绎讲解（lecture_md，Markdown+LaTeX）。"
    "给出 1-3 个'引导确认/提问'出口（asked_to_confirm），**每条都必须能被一个只读过本讲解的"
    "零基础学生答出来**（复述讲解里写过的话，或由 ≥2 条讲解事实经明确规则推出）；"
    "并为每条给出 asks_basis（与 asked_to_confirm **按下标对齐**）："
    '{{"fact_ids":["上面事实 id（若有）"],"quote":"讲解原文里逐字出现的一句依据"}}；'
    "引文必须 ≥6 字且**逐字**取自讲解（不得改写）；**没有依据就不要出这条**（宁缺勿造）；"
    "禁止模板套话（如「它与你学过的内容有什么联系」「这个概念还适用于什么情况」——"
    "指代不明/学生无从判断的一律不要）。{fact_hint}\n"
    "节点：{node_title}"
)

U_ANSWER = (
    "输出 JSON：\n"
    '{{"reply_md":"…","needs_more_info":false,"out_of_scope":false}}\n'
    "任务：回答学生问题；若问题超出白名单/当前范围，回复应说明并置 out_of_scope=true。\n"
    "学生问题：{question}"
)

U_HINT = (
    "输出 JSON：\n"
    '{{"hint_md":"…"}}\n'
    "任务：给一条方向性提示（hint_md），帮助学生发现自己的错误。\n"
    "题面：{prompt}\n模式：{mode}\n学生作答：{student_answer}\n判题细节：{judge_detail}"
)

U_FEYNMAN_EVAL = (
    "输出 JSON：\n"
    '{{"dimension_scores":[{{"key":"…","score":0.5,"evidence_quote":"学生原话逐字片段",'
    '"comment":"…"}}],"overall_note":"…",'
    '"misconceptions_found":[{{"concept":"…","evidence":"…"}}],'
    '"recommend_action":"pass|followup|relearn","confidence":0.8}}\n'
    "任务：按 rubric 逐维打分（score 0..1），给评语与逐字证据；给出 recommend_action；"
    "可附带评分置信度 confidence(0..1)（可选）。\n"
    "费曼任务：{task_prompt}\n"
    "评分维度（rubric）：{rubric_dimensions}\n"
    "上一轮评分摘要：{previous_round}\n"
    "账本已认可内容：{previously_acknowledged}\n"
    "学生本次口述：\n{transcript}"
)

U_FEYNMAN_FOLLOWUP = (
    "输出 JSON：\n"
    '{{"question_md":"…","student_quote":"学生原话逐字片段","missing":"这句话缺了什么",'
    '"reteach":false}}\n'
    "任务：生成一条定向追问（question_md，可用 Markdown/LaTeX）：先**逐字引用**学生说过的那句话"
    "（student_quote），指出这句话缺了什么（missing），再要求学生就这一点补讲；"
    "不得换到别的知识点；学生无可引用内容时置 reteach=true。\n"
    "未达标缺口：{unmet_gaps}\n"
    "候选主题：{socratic_topics}\n"
    "上轮评分：{previous_scores}\n"
    "学生口述：\n{student_transcript}"
)

U_GAP_CHECK = (
    "输出 JSON：\n"
    '{{"gap_filled":true,"dimension_updates":[{{"key":"…","score":0.7,'
    '"evidence_quote":"学生原话逐字片段","comment":"…"}}],"comment":"…"}}\n'
    "任务：判定 gap_filled（该缺口是否补上）并给出该维度的新分；可用 comment 用学生能懂的话"
    "说明还差什么。\n"
    "费曼任务：{task_prompt}\n"
    "评分维度：{rubric_dimensions}\n"
    "追问：{followup_question}\n"
    "目标缺口：{target_gap}\n"
    "学生补答：{student_answer}"
)

S_CLASSIFY = (
    "[角色] 你是学习系统的错因分类器。\n"
    '[输出纪律] 只输出 JSON：{{"error_type": "<枚举>"}}。\n'
    "枚举：arithmetic_slip | sign_error | concept_confusion | step_omission | "
    "procedure_misuse | notation_error | unknown（无法归类时用 unknown）。"
)

U_CLASSIFY = (
    "输出 JSON：\n"
    '{{"error_type":"unknown"}}\n'
    "任务：分类学生的错答类型。\n"
    "题面：{prompt}\n正确答案：{correct_solution}\n学生作答：{student_answer}"
)

U_CHALLENGE = (
    "输出 JSON：\n"
    '{{"prompt_md":"…","answer_hint_md":"…","why_hard_md":"…","difficulty":3}}\n'
    "任务：为这个节点出一道**挑战题**（prompt_md）：需要讲解之外的知识，答不出也不影响学习进度。"
    "给出 answer_hint_md（作答形式提示）与 why_hard_md（为什么它超出讲解，学生视角，不要泄答案本身）。\n"
    "节点：{node_title}\n核心概念：{core_concepts}\n已生成次数：{asked_before}"
)

U_CHALLENGE_CHECK = (
    "输出 JSON：\n"
    '{{"correct":false,"score":0.0,"feedback_md":"…","better_md":"…"}}\n'
    "任务：判定这道挑战题的作答（correct/score 0..1），给出 feedback_md 与 better_md。\n"
    "题目：{prompt_md}\n学生作答：{student_answer}\n节点：{node_title}"
)

U_OUTLINE_DRAFT = (
    "输出 JSON：\n"
    '{{"units":[{{"title":"…","objectives":["…"],"concept_tags":["…"],"group":"…",'
    '"prereqs":["u01"],"difficulty":2,"requires_thinking":false,'
    '"materials":[{{"title":"材料标题","section":"章节名或逐字引文"}}]}}]}}\n'
    "学科名：{label}（id={subject_id}）\n"
    "用户学这门课的目标/背景：{brief}\n"
    "分组方向：{group_hint}\n"
    "{chapter_map_block}"
    "{entries_block}"
    "{batch_note}"
    "{material_block}"
    "{errors_block}"
    "请起草本学科的大纲单元。"
)

U_UNIT_CONTENT = (
    "输出 JSON：\n"
    '{{"lecture":"Markdown 讲解（含 1 个直观例子）",'
    '"taught_facts":[{{"id":"f1","text":"讲解里逐字出现过的一句话"}}],'
    '"derivable":[{{"conclusion":"可由已述事实推出的结论","premises":["f1","f2"],'
    '"rule":"所用规则"}}],'
    '"worked_examples":[{{"prompt":"例题题干","solution_steps":["步骤1","步骤2"]}}],'
    '"asks":[{{"ask":"引导确认/小思考（学生应能自己回答）",'
    '"basis":{{"fact_ids":["f1"],"quote":"讲解原文引文"}}}}],'
    '"feynman_task":"费曼口述任务（一段话）",'
    '"exercises":[{{"kind":"boolean|choice|fill","prompt":"…",'
    '"answer_bool":true（boolean 用）,"options":[…],"answer_index":0（choice 用,0 起）,'
    '"expected":"…","aliases":[…]（fill 用）,'
    '"basis":{{"fact_ids":["f1"],"quote":"讲解原文里逐字出现的一句依据"}}}}]}}\n'
    "学科：{subject_id}\n单元：{unit_title}\n学习目标：{objectives}\n"
    "概念标签：{concept_tags}\n引用材料摘要：\n{mats}\n"
    "{material_block}"
    "{errors_block}"
    "请起草本单元学习内容。"
)

U_SEARCH_CANDIDATES = (
    "输出 JSON：\n"
    '{{"items":[{{"title":"…","url":"…","source":"…","summary":"…","reason":"…"}}]}}\n'
    "任务：从检索原始结果中挑选与学习者目标相关的候选资料，"
    "url **必须**取自原始结果（不得杜撰）。\n"
    "查询：{query}\n学科：{subject_label}\n学科简介：{subject_brief}\n"
    "检索原始结果：{results}"
)


def _outline_system() -> str:
    """大纲起草的 system 默认值（与 R37 S2/S8 原实现逐字一致 + 教材纪律占位符）。"""
    return (
        "你是课程大纲设计专家。请为学习者起草一门新学科的**知识点单元级**大纲。"
        '输出 JSON：{{"units":[{{...}}]}}，unit 字段：title(单元标题), objectives(1-3 条学习目标), '
        "concept_tags(2-4 个简洁规范的**概念标签**——命名稳定、可跨大纲复用，禁长句), "
        'group(分组名，先到先得), prereqs(引用更早单元的编号如 "u01"；根单元留空；只能引用更早单元), '
        "difficulty(1-3), requires_thinking(是否需要深度思考模型，布尔), "
        'materials(该单元依据的引用材料，形如 [{{"title":"材料标题","section":"章节名或逐字引文"}}]；'
        "无依据则给空数组 [])。"
        "要求：单元粒度到「单个知识点可独立学习」；单元间依赖严谨、无环。"
        "**由易到难（R36 P1/P3）**：单元顺序必须构成一条由易到难的学习路径——"
        "先修单元的 difficulty **不得高于**后继单元；group 用于表达「章/阶段」层次，组内同样先易后难。"
        "**零基础起点（R36 P2）**：第一个单元（prereqs 为空）必须能被**完全零基础**者学会，"
        "不得假定任何前置概念或课外常识（零基础假设：没教过的一律认为学习者不会）。"
        "**难度只能靠已教事实累积（R36 P4）**：后续单元可以更难，但加难只能建立在**前面单元已经讲过**的"
        "内容上，不得默认学习者已知道尚未讲过的概念。{material_discipline}"
    )


def _unit_content_system() -> str:
    """单元内容起草的 system 默认值（与 R37 S3/S4 原实现逐字一致 + 教材纪律占位符）。"""
    return (
        "你是学科内容作者。为一门课的知识点单元写学习内容：输出 JSON："
        '{{"lecture":"Markdown 讲解（含 1 个直观例子）",'
        '"taught_facts":[{{"id":"f1","text":"讲解里逐字出现过的一句话"}}],'
        '"derivable":[{{"conclusion":"可由已述事实推出的结论","premises":["f1","f2"],'
        '"rule":"所用规则"}}],'
        '"worked_examples":[{{"prompt":"例题题干","solution_steps":["步骤1","步骤2"]}}],'
        '"asks":[{{"ask":"引导确认/小思考（学生应能自己回答）",'
        '"basis":{{"fact_ids":["f1"],"quote":"讲解原文引文"}}}}],'
        '"feynman_task":"费曼口述任务（一段话）",'
        '"exercises":[{{"kind":"boolean|choice|fill","prompt":"…",'
        '"answer_bool":true（boolean 用）,"options":[…],"answer_index":0（choice 用,0 起）,'
        '"expected":"…","aliases":[…]（fill 用）,'
        '"basis":{{"fact_ids":["f1"],"quote":"讲解原文里逐字出现的一句依据"}}}}]}}\n'
        "**可答性硬要求（R35，违反即被服务端丢弃）**：\n"
        "1) 零基础假设：学习者**只读过本单元讲解**，没教过的一律当不会（不许假设常识/课外知识）；\n"
        "2) `taught_facts[].text` 必须是**讲解里逐字出现过**的句子（≥6 字，不得改写）；\n"
        "3) 每道题/每条 asks 必须带 `basis`：`fact_ids` 只能引用上面声明的事实 id，"
        "`quote` 必须**逐字出自讲解**（≥6 字）；\n"
        "4) **只能问讲解讲过的东西**：可以复述已述事实，或由 ≥2 条已述事实经 `derivable` 里的规则推出；"
        "**不许问个体比较/排序/课外事实**（例：讲了「整类体积大」就不能问「哪一个最大」）；\n"
        "5) 讲解写了整类的性质时，**不要**出需要个体之间比较的题；\n"
        "6) `worked_examples` **至少 1 个**（示范如何合法作答）；`asks` 1–3 条，"
        "指代必须明确（禁止「这个概念/它」这类无指向的说法）；\n"
        "7) `exercises` 3–5 道且**至少含 2 种题型**、题面互不相同；判断陈述明确可判；讲解简洁准确。\n"
        "**教材锚定硬要求（R37，违反即被服务端丢弃/整单元失败）**：\n"
        "8) 有教材段落时，你的讲解必须是**该段教材的完整演绎**——逐个要点讲到（不得省略要点），"
        "可以换措辞、举例、类比、衔接，但**不得引入教材没有陈述的事实/数字/结论**；\n"
        "9) `taught_facts[].text` **必须逐字摘录自教材段落原文**（服务端会用引文尺子在教材原文里查；"
        "抄写时不要改写、不要补字、不要合并两句）；\n"
        "10) 每道题/每条 asks 的 `basis.quote` 也必须**逐字出自教材段落原文**"
        "（而不是只出自你自己的讲解）；教材里找不到依据的题，服务端会**丢弃该题**；\n"
        "11) 教材段落没讲到的内容**一律不写、不问**——宁可少讲，不得编造。"
        "{material_discipline}"
    )


def _cb(**kw) -> dict:
    """``PromptSpec`` 的 ContextBlock 公共硬约束（system 与 user 共用占位符集合）。"""
    ph = CB_PLACEHOLDERS
    return {
        "system_required_placeholders": ph,
        **kw,
    }


def _specs() -> dict[str, PromptSpec]:
    out: list[PromptSpec] = [
        PromptSpec(
            "explain_node", "讲解演绎",
            "把教材里的讲解改写成适合这个学生的讲法，再给 1-3 个有依据的确认问题。",
            S_EXPLAIN, U_EXPLAIN,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("fact_hint", "node_title"),
            user_required_tokens=("lecture_md", "asked_to_confirm", "asks_basis", "输出 JSON"),
            notes="花括号由程序填内容；改这里会影响讲什么、问什么。",
        ),
        PromptSpec(
            "answer_question", "答疑",
            "回答学生关于当前知识点的问题；超出范围就直说。",
            S_EXPLAIN, U_ANSWER,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("question",),
            user_required_tokens=("reply_md", "out_of_scope", "输出 JSON"),
        ),
        PromptSpec(
            "hint_on_error", "错题提示",
            "答错以后只给一点方向，不给完整答案。",
            S_EXPLAIN, U_HINT,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("prompt", "mode", "student_answer", "judge_detail"),
            user_required_tokens=("hint_md", "输出 JSON"),
            notes="里面写了「绝对不许给完整解答」，建议保留。",
        ),
        PromptSpec(
            "feynman_evaluate", "费曼评分",
            "按几个方面打分，每一方面都要引用学生的原话作证据。",
            S_EXPLAIN, U_FEYNMAN_EVAL,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("task_prompt", "rubric_dimensions", "transcript",
                                        "previous_round", "previously_acknowledged"),
            user_required_tokens=("dimension_scores", "evidence_quote", "recommend_action",
                                  "输出 JSON"),
        ),
        PromptSpec(
            "feynman_followup", "费曼定向追问",
            "针对最薄弱的一点追问一句，要引用学生的原话。",
            S_EXPLAIN, U_FEYNMAN_FOLLOWUP,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("unmet_gaps", "socratic_topics", "previous_scores",
                                        "student_transcript"),
            user_required_tokens=("question_md", "student_quote", "missing", "reteach", "输出 JSON"),
        ),
        PromptSpec(
            "feynman_gap_check", "缺口补答评估",
            "只看刚才那一点补上没有，只更新那一项的分数。",
            S_EXPLAIN, U_GAP_CHECK,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("task_prompt", "rubric_dimensions", "followup_question",
                                        "target_gap", "student_answer"),
            user_required_tokens=("gap_filled", "dimension_updates", "输出 JSON"),
        ),
        PromptSpec(
            "classify_error", "错因分类",
            "把答错的原因归到一个类别里（不判对错）。",
            S_CLASSIFY, U_CLASSIFY,
            system_required_tokens=("error_type", "arithmetic_slip", "unknown", "输出 JSON"),
            user_required_placeholders=("prompt", "correct_solution", "student_answer"),
            user_required_tokens=("error_type", "输出 JSON"),
        ),
        PromptSpec(
            "generate_practice_variant", "练习题变体（未启用）",
            "暂时用不上，模板先留着，将来要用再打开。",
            S_EXPLAIN,
            '输出 JSON：\n{{"param_values":{{}},"prompt_md":"…"}}\n节点：{node_id}',
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("node_id",),
            user_required_tokens=("prompt_md", "输出 JSON"),
        ),
        PromptSpec(
            "explain_solution_step", "解题步骤讲解",
            "解释解题的某一步。",
            S_EXPLAIN, '输出 JSON：\n{{"step_explanation_md":"…"}}\n步骤：{step_text}',
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("step_text",),
            user_required_tokens=("step_explanation_md", "输出 JSON"),
        ),
        PromptSpec(
            "challenge_exercise", "挑战题生成",
            "另外出一道更难的挑战题（不计入掌握，也不进默认流程）。",
            S_EXPLAIN, U_CHALLENGE,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("node_title", "core_concepts", "asked_before"),
            user_required_tokens=("prompt_md", "why_hard_md", "输出 JSON"),
        ),
        PromptSpec(
            "challenge_check", "挑战题判分",
            "只判挑战题答得对不对，结果只进复盘。",
            S_EXPLAIN, U_CHALLENGE_CHECK,
            system_required_placeholders=CB_PLACEHOLDERS,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("prompt_md", "student_answer", "node_title"),
            user_required_tokens=("correct", "score", "feedback_md", "输出 JSON"),
        ),
        PromptSpec(
            "draft_content", "内容草稿",
            "按给定的规格起草一节内容的草稿。",
            "[角色] 你是学科内容作者。\n" + JSON_DISCIPLINE,
            '输出 JSON：\n{{"draft_md":"…"}}\n规格：{spec}',
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("spec",),
            user_required_tokens=("draft_md", "输出 JSON"),
        ),
        PromptSpec(
            "outline_draft", "大纲起草",
            "先读教材，再按书的目录排出学科大纲（每个单元都注明来自书的哪一节）。",
            _outline_system(), U_OUTLINE_DRAFT,
            system_required_placeholders=("material_discipline",),
            system_required_tokens=("units", "title", "objectives", "concept_tags", "group",
                                    "prereqs", "difficulty", "materials", "输出 JSON"),
            user_required_placeholders=("label", "subject_id", "brief", "group_hint",
                                        "chapter_map_block", "entries_block", "batch_note",
                                        "material_block", "errors_block"),
            user_required_tokens=("units", "title", "materials", "输出 JSON"),
            notes="里面写了「一切以教材为准」的要求，建议保留。"
                  "（{material_discipline} 是程序按本次有没有教材自动填进去的一段）",
        ),
        PromptSpec(
            "unit_content_draft", "单元内容起草",
            "按教材段落起草这一单元的讲解、要点、例题、小思考和练习题。",
            _unit_content_system(), U_UNIT_CONTENT,
            system_required_placeholders=("material_discipline",),
            system_required_tokens=("lecture", "taught_facts", "derivable", "worked_examples",
                                    "asks", "feynman_task", "exercises", "basis", "输出 JSON"),
            user_required_placeholders=("subject_id", "unit_title", "objectives", "concept_tags",
                                        "mats", "material_block", "errors_block"),
            user_required_tokens=("lecture", "taught_facts", "exercises", "输出 JSON"),
            notes="里面写了「讲得清、答得上」和「必须依据教材」的要求；删掉会让整个单元作废。",
        ),
        PromptSpec(
            "search_candidates", "联网候选整理",
            "从搜索结果里挑出相关的几条（网址必须来自原始结果）。",
            "[角色] 你是资料检索助手。\n" + JSON_DISCIPLINE,
            U_SEARCH_CANDIDATES,
            system_required_tokens=("输出 JSON",),
            user_required_placeholders=("query", "subject_label", "subject_brief", "results"),
            user_required_tokens=("items", "url", "summary", "输出 JSON"),
        ),
    ]
    return {s.call_name: s for s in out}


PROMPTS: dict[str, PromptSpec] = _specs()


# ---------------------------------------------------------------------------
# 占位符的"界面预览"默认取值（仅用于把模板渲染成人可读的当前值/默认值文本；
# 真实生成时由各调用点用真实数据渲染——两处用的是**同一个** render()）
# ---------------------------------------------------------------------------
UI_PLACEHOLDER_DEFAULTS: dict[str, str] = {
    "level": "当前学段",
    "explanation_body": "（此处注入本节点官方讲解稿）",
    "worked_examples": "- （此处注入例题原文）",
    "whitelist": "（此处注入概念白名单）",
    "bans": "（此处注入禁令清单）",
    "style": "解释清晰、循序渐进，面向初学者。",
    "fact_hint": "本单元已声明事实（可引用其 id）：f1=…",
    "node_title": "（节点标题）",
    "node_id": "（节点 id）",
    "question": "（学生问题）",
    "prompt": "（题面）",
    "mode": "（练习模式）",
    "student_answer": "（学生作答）",
    "judge_detail": "（判题细节）",
    "correct_solution": "（正确答案）",
    "task_prompt": "（费曼任务）",
    "rubric_dimensions": "[]",
    "transcript": "（学生本次口述）",
    "previous_round": "null",
    "previously_acknowledged": "[]",
    "unmet_gaps": "[]",
    "socratic_topics": "[]",
    "previous_scores": "[]",
    "student_transcript": "（学生口述）",
    "followup_question": "（追问）",
    "target_gap": "{}",
    "step_text": "（解题步骤原文）",
    "core_concepts": "（核心概念）",
    "asked_before": "0",
    "prompt_md": "（题目）",
    "subject_id": "（学科 id）",
    "label": "（学科名）",
    "brief": "（用户目标/背景）",
    "group_hint": "（分组方向）",
    "chapter_map_block": "（此处注入教材章节地图）",
    "entries_block": "（此处注入本批必须覆盖的条目标签）",
    "batch_note": "",
    "material_block": "（此处注入教材段落完整正文）",
    "errors_block": "",
    "unit_title": "（单元标题）",
    "objectives": "（学习目标）",
    "concept_tags": "（概念标签）",
    "mats": "（引用材料摘要）",
    "material_discipline": _MATERIAL_DISCIPLINE,
    "query": "（检索关键词）",
    "subject_label": "（学科名）",
    "subject_brief": "（学科简介）",
    "results": "[]",
    "spec": "{}",
}


def default_vars(spec: PromptSpec) -> dict[str, str]:
    """该模板全体占位符的界面预览默认取值（缺省 → 空串，禁止渲染崩溃）。"""
    return {ph: UI_PLACEHOLDER_DEFAULTS.get(ph, "") for ph in spec.placeholders}


def is_material_disciplined(text: str) -> bool:
    """该模板是否带教材纪律占位符（决定 system 渲染时是否注入教材硬要求）。"""
    return "{material_discipline}" in (text or "")


# ---------------------------------------------------------------------------
# 渲染 / 校验 / 差异
# ---------------------------------------------------------------------------
def render(text: str, **vars: object) -> str:
    """渲染模板。缺占位符 → ``PromptError``（中文），**绝不静默留 {}**。"""
    try:
        return str(text or "").format(**vars)
    except KeyError as e:
        missing = e.args[0] if e.args else ""
        hint = ("模板里的字面花括号（如 JSON 示例）必须写成**双花括号**：{ 写成 {{ ，} 写成 }}。"
                if not re.fullmatch(r"[a-z_][a-z0-9_]*", str(missing)) else
                "该占位符由程序注入；请恢复默认或补回占位符。")
        raise PromptError(
            f"提示词渲染失败：缺少占位符 {{{missing}}} 的取值（{hint}）") from e
    except (IndexError, ValueError) as e:
        raise PromptError(
            f"提示词模板花括号不合法：{e}。模板里的字面花括号（如 JSON 示例）"
            "必须写成**双花括号**：{ 写成 {{ ，} 写成 }}。") from e


def validate_text(call_name: str, text: str, *, field: str = "system") -> list[str]:
    """校验一段模板：返回**中文问题清单**（空 = 通过）。"""
    spec = PROMPTS.get(call_name)
    if spec is None:
        # 未来新增调用点：注册表未收录 —— 铁则要求"一处不漏"，拒存并说明
        return [f"未知调用点「{call_name}」：提示词注册表未收录，无法校验（请先注册后再改）"]
    if field == "user" and not spec.user:
        return ["该调用点没有 user 模板可改（只有 system 模板）"]
    if field == "system" and not spec.system:
        return ["该调用点没有 system 模板可改"]
    if not (text or "").strip():
        return [f"提示词不能为空（{spec.label}）"]
    required_ph = (spec.user_required_placeholders if field == "user"
                   else spec.system_required_placeholders)
    required_tok = (spec.user_required_tokens if field == "user"
                    else spec.system_required_tokens)
    problems: list[str] = []
    for ph in required_ph:
        if "{" + ph + "}" not in text:
            problems.append(f"缺少必须保留的占位符 {{{ph}}}（它由程序注入，删掉会让该功能收不到数据）")
    for tok in required_tok:
        if tok not in text:
            problems.append(f"缺少必须保留的硬约束「{tok}」（删掉会让输出校验静默失效）")
    # 模板语法：必须先能渲染（缺占位符取值/裸花括号 → 拒存，否则生成时才会炸）
    try:
        render(text, **{ph: "" for ph in spec.placeholders})
    except PromptError as e:
        problems.append(str(e))
    return problems


def diff_lines(default: str, current: str) -> list[dict]:
    """与默认的差异（改了哪几行）：``[{kind, line, text}]``，kind ∈ hunk/add/del。"""
    import difflib

    a = (default or "").splitlines()
    b = (current or "").splitlines()
    out: list[dict] = []
    for line in difflib.unified_diff(a, b, lineterm="", n=0):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            out.append({"kind": "hunk", "line": line, "text": ""})
            continue
        if line.startswith("-"):
            out.append({"kind": "del", "line": line, "text": line[1:]})
        elif line.startswith("+"):
            out.append({"kind": "add", "line": line, "text": line[1:]})
    return out


__all__ = [
    "PromptSpec", "PROMPTS", "PromptError", "render", "validate_text", "diff_lines",
    "default_vars", "is_material_disciplined", "UI_PLACEHOLDER_DEFAULTS", "CB_PLACEHOLDERS",
    "_MATERIAL_DISCIPLINE", "_UNIT_MATERIAL_DISCIPLINE",
]
