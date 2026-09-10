"""app.ai.gateway：AI 门面（service 唯一依赖面）。

- AiGateway（Protocol）：各调用点方法。两种实现：
  1. OpenAICompatibleGateway —— 真模型（默认 DeepSeek；ollama/Qwen 兼容），经
     ai.provider.chat_json（JSON 提取 + pydantic 校验 + 重试）产出，AiCallError 上抛；
  2. OfflineGateway —— 无 key/降级时的内容库兜底（docs/05 §6）与离线启发式（仅演示）。
- service 捕获 AiCallError 后按 docs/05 §6 降级，绝不脏状态。
"""
from __future__ import annotations

import re
from typing import Protocol

from ..content import citations
from .calls import (
    AiCallError,
    AnswerQuestionIn,
    AnswerQuestionOut,
    CALL_ANSWER_QUESTION,
    CALL_CLASSIFY_ERROR,
    CALL_EXPLAIN_NODE,
    CALL_FEYNMAN_EVALUATE,
    CALL_FEYNMAN_FOLLOWUP,
    CALL_FEYNMAN_GAP_CHECK,
    CALL_GENERATE_VARIANT,
    CALL_HINT_ON_ERROR,
    CiteBasis,
    ClassifyErrorIn,
    ClassifyErrorOut,
    ExplainIn,
    ExplainOut,
    FeynmanDimScore,
    FeynmanEvaluateIn,
    FeynmanEvaluateOut,
    FeynmanFollowupIn,
    FeynmanFollowupOut,
    GapCheckIn,
    GapCheckOut,
    HintOnErrorIn,
    HintOnErrorOut,
    VariantIn,
    VariantOut,
)
from .provider import LogSink, OpenAICompatibleProvider
from .prompts import context_block, task_json

MIN_FEYNMAN_CHARS = 20  # docs/05 §5：口述 <20 字直接判敷衍，不进评分

# ---- R27：离线启发式评分常量（仅无 key/降级兜底；真模型可用时不得抢占，docs/09 R4/R27） ----
BASE_SCORES = {"correctness": 0.30, "own_words": 0.25, "evidence": 0.10, "self_correction": 0.15}
# 提到 n 个核心概念 → 基础分（"讲了什么"）；具体讲全程度见 offline_feynman_scores 的明确分档
_BY_CONCEPTS = ((0, 0.0), (1, 0.55), (2, 0.75), (3, 0.88))
_EVIDENCE_KEYWORDS = (
    "因为", "所以", "依据", "证据", "观测", "观察", "实验", "探测", "推导", "证明", "例如", "比如",
)
_SELF_CORRECTION_KEYWORDS = (
    "我原先", "我之前", "原来以为", "纠正", "改正", "修正", "不对", "错在", "其实应该是",
)

_MODE_HINT = {
    "numeric_value": "先检查计算过程：代入、进位/借位、正负号，再核对题目要求。",
    "equation_solution": "检查三步：移项是否变号？同类项是否合并正确？系数除法是否算对？",
    "symbolic_equivalence": "检查代数变形：去括号每一项都乘到？合并同类项有没有漏项、错符号？",
    "boolean_judgment": "回到定义逐条核对：等式？含未知数？一元？一次？哪一条不满足？",
}


def _step_score(table: tuple[tuple[int, float], ...], value: int) -> float:
    """阶梯分档：返回所有满足 ``value >= 阈值`` 的档位中最高分（与表序无关）。"""
    best = 0.0
    for threshold, score in table:
        if value >= threshold and score > best:
            best = score
    return best


def _concept_hits(text: str, concepts: list[str]) -> list[str]:
    return [c for c in concepts if c and c in text]


def offline_feynman_scores(
    transcript: str, core_concepts: list[str], rubric_dimensions: list[dict]
) -> tuple[list[dict], bool]:
    """离线启发式分维评分（R27 重构：分维不同权重 + evidence/自纠真实分档）。

    返回 (card, evidence_plausible)。card 元素 {key, score, evidence_quote, comment}
    且 ``evidence_quote`` 必为 transcript 子串（服务端包含校验与离线一致性；见 R27 §2）。
    """
    text = (transcript or "").strip()
    hits = _concept_hits(text, core_concepts)
    n = len(hits)
    target = max(1, len(core_concepts))
    length = len(text)
    has_evidence = any(k in text for k in _EVIDENCE_KEYWORDS)
    has_self_correction = any(k in text for k in _SELF_CORRECTION_KEYWORDS)
    plausible = n >= 1
    # 讲全程度（own_words 与"讲得对"代理分）：概念覆盖 × 篇幅（+依据）→ 明确档位。
    # "中档"（覆盖 ≥3 目标 + 篇幅 ≥25 + 有依据）对应"看过追问提示后自己把该讲的补齐"。
    if n >= target or (n >= 4 and length >= 40):
        cover_score = 0.95
    elif n >= 3 and length >= 40:
        cover_score = 0.85
    elif (n >= 3 and length >= 25) or (n >= 2 and length >= 30):
        cover_score = 0.75
    elif n >= 1:
        cover_score = 0.45 if has_evidence else 0.3
    else:
        cover_score = 0.05
    base = _step_score(_BY_CONCEPTS, n)
    if n >= 3 and length >= 40:
        detail = 0.75 + (0.10 if has_evidence else 0.0)
    elif (n >= 3 and length >= 25) or (n >= 2 and length >= 25):
        detail = 0.7
    else:
        detail = 0.0
    base = max(base, detail)

    quote = text[:40] + ("…" if len(text) > 40 else "")
    scores: dict[str, tuple[float, str]] = {}
    for dim in rubric_dimensions:
        key = str(dim.get("key", ""))
        base_score = BASE_SCORES.get(key, 0.3)
        if key == "own_words":
            score, why = max(base_score, cover_score), "是否用自己的话讲全（离线按核心概念覆盖分档）"
        elif key == "evidence":
            score = min(1.0, base + (0.12 if has_evidence else 0.0))
            why = "给出了依据（因为/观测/推导等）" if has_evidence else "未给出依据（缺观测/实验/推导类表述）"
        elif key == "self_correction":
            # 离线无法真的"追问"，给保底分体现"愿意接受修正"；明确的自纠表述再上调
            score = 0.7 if has_self_correction else 0.5
            why = "体现了自我修正" if has_self_correction else "已给出可被追问修正的说法"
        else:
            # correctness / example_and_edge / evidence_and_reasoning 及未知维度：
            # 一律以"核心概念覆盖"为基础分（concept 覆盖是这类维度的可判据代理）
            score, why = base, f"提到核心概念 {n}/{target}（{('、'.join(hits[:3]) or '无')}）"
        scores[key] = (round(score, 3), why)
    card = [
        {
            "key": str(dim.get("key", "")),
            "score": scores[str(dim.get("key", ""))][0],
            "evidence_quote": quote,
            "comment": scores[str(dim.get("key", ""))][1] + "（离线启发式，仅供参考）",
        }
        for dim in rubric_dimensions
    ]
    return card, plausible


def offline_gap_check(ctx: GapCheckIn) -> GapCheckOut:
    """离线缺口补答启发式：只判目标缺口维度是否补上（只更新该维度）。"""
    text = (ctx.student_answer or "").strip()
    gap = ctx.target_gap or {}
    key = str(gap.get("key", ""))
    if len(text) < 10:
        return GapCheckOut(
            gap_filled=False,
            dimension_updates=[],
            comment="补答太短，还没有具体回答追问的内容——请把你的依据/方法说清楚（≥10 字）。",
        )
    hits = _concept_hits(text, list(ctx.core_concepts or []))
    has_evidence = any(k in text for k in _EVIDENCE_KEYWORDS)
    has_self_correction = any(k in text for k in _SELF_CORRECTION_KEYWORDS)
    if key == "evidence":
        filled = has_evidence
        score = 0.9 if (has_evidence and len(hits) >= 2) else 0.82 if has_evidence else 0.0
        why = "补上了'依据/方法'缺口（给出观测、实验或推导依据）" if filled else "仍未给出可核对的依据/方法"
    elif key == "self_correction":
        filled = has_self_correction
        score = 0.85 if filled else 0.0
        why = "体现了自我修正" if filled else "仍未体现自我修正（说出原先哪里理解错了即可）"
    elif key == "own_words":
        filled = len(hits) >= 1 or len(text) >= 30
        score = 0.85 if filled else 0.0
        why = "用自己的话补充说明了" if filled else "补答没有实质内容"
    else:  # correctness 及未知维度
        filled = len(hits) >= 1
        score = 0.9 if len(hits) >= 2 else 0.85 if filled else 0.0
        why = f"补上了缺口（提到 {('、'.join(hits) or '—')}）" if filled else "补答未涉及该缺口的核心概念"
    quote = text[:40] + ("…" if len(text) > 40 else "")
    updates = (
        [{"key": key, "score": round(score, 3), "evidence_quote": quote,
          "comment": why + "（离线启发式，仅供参考）"}]
        if filled and key
        else []
    )
    return GapCheckOut(
        gap_filled=bool(filled),
        dimension_updates=updates,
        comment=why,
    )


# ---------------------------------------------------------------------------
# R35 S6：🤔 小思考的引文纪律（"零基础学生只读讲解就能答"才允许下发）
# ---------------------------------------------------------------------------
_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]+")


def sentence_with(body: str, needle: str, *, min_chars: int = citations.MIN_QUOTE_CHARS) -> str:
    """从讲解正文里取**包含该关键词**的整句（供引文用）；取不到返回空串。"""
    if not body or not needle:
        return ""
    for sent in _SENTENCE_SPLIT.split(body):
        s = sent.strip()
        if len(citations.normalize(s)) < min_chars:
            continue
        if citations.normalize(needle) and citations.normalize(needle) in citations.normalize(s):
            return s
    return ""


def filter_asks(out: ExplainOut, *, sources: list[str], fact_ids: set[str] | None = None) -> ExplainOut:
    """只保留**有据**的 asked_to_confirm（S6）：引文须逐字出自讲解（≥6 字，citations 同一把尺子）；
    若声明了 `taught_facts`，引用的 fact_ids 必须落在其中。无据的那条**直接丢弃**（模板套话不再兜底）。
    """
    kept: list[str] = []
    kept_basis: list[CiteBasis] = []
    declared = fact_ids or set()
    for i, ask in enumerate(out.asked_to_confirm or []):
        basis = out.asks_basis[i] if i < len(out.asks_basis) else None
        quote = str(getattr(basis, "quote", "") or "")
        if quote and not any(citations.is_valid(quote, s) for s in sources if s):
            continue  # 引文不在讲解里 → 不可答
        if not quote:
            continue  # 无引文 → 不可答
        ids = [str(x) for x in (getattr(basis, "fact_ids", None) or [])]
        if declared and any(x not in declared for x in ids):
            continue  # 引用了未声明的事实 id
        kept.append(ask)
        kept_basis.append(basis)
    return ExplainOut(lecture_md=out.lecture_md, asked_to_confirm=kept, asks_basis=kept_basis)


class AiGateway(Protocol):
    """service 只依赖此协议。所有方法要么返回校验过的输出，要么抛 AiCallError。

    strategy（R12）：fast|think|None —— 服务层经 ai/tier 决策后传入；None=按调用点默认档。
    """

    name: str

    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut: ...
    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut: ...
    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut: ...
    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut: ...
    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut: ...
    def feynman_gap_check(self, ctx: GapCheckIn, *, strategy: str | None = None) -> GapCheckOut: ...
    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut: ...
    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut: ...


class OfflineGateway:
    """确定性离线兜底实现（无 key 默认；真模型失败时 service 回落至此路径）。"""

    name = "offline"
    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut:
        del strategy  # 离线实现忽略档位（决策层在 service 记账）
        header = "（离线模式：以下为官方讲解稿原文）\n\n"
        lecture = ctx.explanation_body.strip() or "（本节点暂无讲解稿）"
        asks: list[str] = []
        asks_basis: list[CiteBasis] = []
        if ctx.core_concepts:
            concept = str(ctx.core_concepts[0])
            quote = sentence_with(ctx.explanation_body, concept)
            if quote:  # R35 S6：没有讲解依据就不出这条（离线模式也不得凭空发问）
                asks.append(f"请确认：你能用自己的话说出「{concept}」是什么吗？")
                asks_basis.append(CiteBasis(fact_ids=[], quote=quote))
        return ExplainOut(lecture_md=header + lecture, asked_to_confirm=asks, asks_basis=asks_basis)

    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut:
        del strategy
        return AnswerQuestionOut(
            reply_md=(
                "（离线模式）我暂时无法针对你的具体问题自由作答。"
                "建议先重读本课讲解稿原文，再完成练习；如果仍卡住，请把卡住的那句话原样发给我，"
                "我会记录下来，联网后由老师为你详细解答。"
            ),
            needs_more_info=False,
            out_of_scope=False,
        )

    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut:
        del strategy
        return HintOnErrorOut(hint_md=_MODE_HINT.get(ctx.mode, "再读一遍题目，检查每一步推导是否都有依据。"))

    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut:
        raise AiCallError("generate_practice_variant", "MVP 不启用 AI 变体出题（docs/08 §1）")

    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut:
        del strategy
        text = ctx.transcript.strip()
        if len(text) < MIN_FEYNMAN_CHARS:
            raise AiCallError("feynman_evaluate", f"口述过短（{len(text)}<{MIN_FEYNMAN_CHARS}字），按敷衍处理")
        card, plausible = offline_feynman_scores(text, list(ctx.core_concepts), list(ctx.rubric_dimensions))
        dims = [FeynmanDimScore(**c) for c in card]
        return FeynmanEvaluateOut(
            dimension_scores=dims,
            overall_note="离线启发式评分（未接 LLM），仅供参考；evidence_quote 均为本轮文本子串。",
            misconceptions_found=[],
            recommend_action="pass" if plausible else "followup",
            confidence=0.3,  # 离线自评置信度（低=启发式；不参与通过判定）
        )

    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut:
        del strategy
        # R27：优先按"最弱缺口"定向追问（一次一个），不再自由发问
        gap = (ctx.unmet_gaps or [None])[0]
        if gap:
            key, desc = str(gap.get("key", "")), str(gap.get("description", "")).strip()
            if desc:
                return FeynmanFollowupOut(
                    question_md=f"请针对这一点补讲：**{desc}**（维度：{key}）。用你自己的话讲清依据即可。"
                )
        if ctx.socratic_followups:
            return FeynmanFollowupOut(question_md=ctx.socratic_followups[0])
        return FeynmanFollowupOut(
            question_md="请用更具体的例子再讲一遍：这个概念解决什么问题？关键一步的依据是什么？"
        )

    def feynman_gap_check(self, ctx: GapCheckIn, *, strategy: str | None = None) -> GapCheckOut:
        del strategy
        return offline_gap_check(ctx)

    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut:
        return ClassifyErrorOut(error_type="unknown")


# --------------------------------------------------------------------------
# OpenAI 兼容网关（真模型）
# --------------------------------------------------------------------------
class OpenAICompatibleGateway:
    """经 provider.chat_json 调真模型；每个调用点 = schema 化（docs/05 §3/§6）。"""

    name = "openai-compatible"

    def __init__(self, provider: OpenAICompatibleProvider):
        self._p = provider

    # ---- prompt 装配通用 ----
    def _system(self, ctx, extra_bans: list[str] | None = None) -> str:
        return context_block(
            level=ctx.level if hasattr(ctx, "level") else "",
            explanation_body=getattr(ctx, "explanation_body", ""),
            worked_examples=getattr(ctx, "worked_examples", []) or [],
            whitelist=list(getattr(ctx, "whitelist", []) or []),
            core_concepts=list(getattr(ctx, "core_concepts", []) or []),
            style=getattr(ctx, "profile_style_block", ""),
            extra_bans=extra_bans,
        )

    # ---- 调用点 1：讲解 ----
    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut:
        system = self._system(ctx)
        facts = list(getattr(ctx, "taught_facts", []) or [])
        fact_hint = ""
        if facts:
            fact_hint = ("本单元已声明事实（可引用其 id）："
                         + "；".join(f"{f.get('id')}={str(f.get('text'))[:40]}" for f in facts[:8]))
        user = task_json(
            task="基于讲解稿为本节点写一份适合该生（考虑风格块）的演绎讲解（lecture_md，Markdown+LaTeX）。"
            "给出 1-3 个'引导确认/提问'出口（asked_to_confirm），**每条都必须能被一个只读过本讲解的"
            "零基础学生答出来**（复述讲解里写过的话，或由 ≥2 条讲解事实经明确规则推出）；"
            "并为每条给出 asks_basis（与 asked_to_confirm **按下标对齐**）："
            '{"fact_ids":["上面事实 id（若有）"],"quote":"讲解原文里逐字出现的一句依据"}；'
            "引文必须 ≥6 字且**逐字**取自讲解（不得改写）；**没有依据就不要出这条**（宁缺勿造）；"
            "禁止模板套话（如「它与你学过的内容有什么联系」「这个概念还适用于什么情况」——"
            "指代不明/学生无从判断的一律不要）。" + (" " + fact_hint if fact_hint else ""),
            node_title=ctx.node_title,
        )
        out = self._p.chat_json(CALL_EXPLAIN_NODE, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return filter_asks(ExplainOut(**out.parsed),
                           sources=[out.parsed.get("lecture_md") or "", ctx.explanation_body or ""],
                           fact_ids={str(f.get("id")) for f in facts})

    # ---- 调用点 2：答疑 ----
    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut:
        system = self._system(ctx)
        user = task_json(
            task="回答学生问题；若问题超出白名单/当前范围，回复应说明并置 out_of_scope=true。",
            question=ctx.student_question,
        )
        out = self._p.chat_json(CALL_ANSWER_QUESTION, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return AnswerQuestionOut(**out.parsed)

    # ---- 调用点 4：错题提示（禁令：禁止输出完整解答） ----
    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut:
        system = context_block(
            level="",
            explanation_body="",
            worked_examples=[],
            whitelist=[],
            core_concepts=[],
            extra_bans=[
                "这是提示生成：**绝对禁止给出完整解答或最终答案表达式**，只给方向性提示（哪一步可疑、检查什么）。",
            ],
        )
        user = task_json(
            task="给一条方向性提示（hint_md），帮助学生发现自己的错误。",
            prompt=ctx.prompt,
            mode=ctx.mode,
            student_answer=ctx.user_answer,
            judge_detail=ctx.judge_detail,
        )
        out = self._p.chat_json(CALL_HINT_ON_ERROR, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return HintOnErrorOut(**out.parsed)

    # ---- 调用点 6：费曼评分（逐字 evidence） ----
    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut:
        system = context_block(
            level="",
            explanation_body="",
            worked_examples=[],
            whitelist=list(getattr(ctx, "core_concepts", []) or []),
            core_concepts=list(getattr(ctx, "core_concepts", []) or []),
            extra_bans=[
                "评分必须可审计：每个维度必须给出 **evidence_quote —— 逐字引用学生原话片段**，禁止无据评分；"
                "misconceptions_found 也须附 evidence。",
            ],
        )
        user = task_json(
            task="按 rubric 逐维打分（score 0..1），给评语与逐字证据；给出 recommend_action；"
            "可附带评分置信度 confidence(0..1)（可选）。",
            task_prompt=ctx.task_prompt,
            rubric_dimensions=ctx.rubric_dimensions,
            transcript=ctx.transcript,
            previous_round=ctx.previous_round,
            previously_acknowledged=ctx.previously_acknowledged,
        )
        out = self._p.chat_json(CALL_FEYNMAN_EVALUATE, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return FeynmanEvaluateOut(**out.parsed)

    # ---- 调用点 7：Socratic 追问（R27：定向未达标缺口） ----
    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut:
        system = context_block(
            level="",
            explanation_body="",
            worked_examples=[],
            whitelist=[],
            core_concepts=[],
            extra_bans=[
                "追问必须**定向到 unmet_gaps 里最弱的那一个缺口**（一次只问一个问题、只问这一点），"
                "不要泛泛自由发问，也不要给出答案。",
            ],
        )
        user = task_json(
            task="生成一条定向追问（question_md，可用 Markdown/LaTeX）：直接要求学生补讲 unmet_gaps"
            "第一项的缺口（description），若不想照抄可换成同义问法，但**不得换到别的知识点**。",
            unmet_gaps=ctx.unmet_gaps,
            socratic_topics=ctx.socratic_followups,
            previous_scores=ctx.previous_scores,
            student_transcript=ctx.student_transcript,
        )
        out = self._p.chat_json(CALL_FEYNMAN_FOLLOWUP, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return FeynmanFollowupOut(**out.parsed)

    # ---- 调用点 13（R27）：缺口补答评估（轻量，只更新缺口维度） ----
    def feynman_gap_check(self, ctx: GapCheckIn, *, strategy: str | None = None) -> GapCheckOut:
        system = context_block(
            level="",
            explanation_body="",
            worked_examples=[],
            whitelist=list(getattr(ctx, "core_concepts", []) or []),
            core_concepts=list(getattr(ctx, "core_concepts", []) or []),
            extra_bans=[
                "这是**缺口补答评估**（不是整体重评）：只判断 target_gap.key 这一个维度是否补上，"
                "dimension_updates **只允许包含该维度一条**；"
                "evidence_quote 必须**逐字引用 student_answer**（服务端做包含校验，杜撰即降级）；"
                "若补答没有真正回答该缺口，gap_filled=false 且 dimension_updates 为空数组。",
            ],
        )
        user = task_json(
            task="判定 gap_filled（该缺口是否补上）并给出该维度的新分；可用 comment 用学生能懂的话"
            "说明还差什么。",
            task_prompt=ctx.task_prompt,
            rubric_dimensions=ctx.rubric_dimensions,
            followup_question=ctx.followup_question,
            target_gap=ctx.target_gap,
            student_answer=ctx.student_answer,
        )
        out = self._p.chat_json(CALL_FEYNMAN_GAP_CHECK, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return GapCheckOut(**out.parsed)

    # ---- 调用点 8：错误分类 ----
    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut:
        system = (
            "[角色] 你是学习系统的错因分类器。\n"
            "[输出纪律] 只输出 JSON：{\"error_type\": \"<枚举>\"}。\n"
            f"枚举：arithmetic_slip | sign_error | concept_confusion | step_omission | "
            f"procedure_misuse | notation_error | unknown（无法归类时用 unknown）。"
        )
        user = task_json(task="分类学生的错答类型", prompt=ctx.prompt, correct_solution=ctx.correct_solution, student_answer=ctx.user_answer)
        out = self._p.chat_json(CALL_CLASSIFY_ERROR, [{"role": "system", "content": system}, {"role": "user", "content": user}])
        return ClassifyErrorOut(**out.parsed)

    # ---- 调用点 3：变体（MVP 不启用，docs/08 §1） ----
    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut:
        raise AiCallError("generate_practice_variant", "MVP 不启用 AI 变体出题（docs/08 §1）")


# --------------------------------------------------------------------------
# 工厂
# --------------------------------------------------------------------------
def gateway_factory(
    *,
    api_key: str = "",
    base_url: str = "",
    heavy_model: str = "",
    light_model: str = "",
    log_sink: LogSink | None = None,
    transport=None,
) -> AiGateway:
    """有 key → OpenAI 兼容真网关；无 key → OfflineGateway（离线兜底）。"""
    if api_key:
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            model_heavy=heavy_model,
            model_light=light_model,
            log_sink=log_sink,
            transport=transport,
        )
        return OpenAICompatibleGateway(provider)
    return OfflineGateway()


__all__ = [
    "AiGateway",
    "OfflineGateway",
    "OpenAICompatibleGateway",
    "gateway_factory",
    "MIN_FEYNMAN_CHARS",
    "offline_feynman_scores",
    "offline_gap_check",
]
