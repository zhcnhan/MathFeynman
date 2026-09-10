"""R35 §12 语义自检闸门回归（**离线、确定性**）。

必交两条（架构侧验收）：
- **造错必报**：构造"题面说了条件但 constraint 没保证" / "answer_expr 与独立算式矛盾" 的坏模板 → 断言被拒；
- **换学科仍成立**：通用层（领域谓词）**对非数学学科同样生效** —— 造一个自定义学科的模板题
  （答案可能为负 / 非整数）并断言被拒（**不需要任何数学 L1 插件**）。
"""
from __future__ import annotations

import pytest

from app.content.schemas import CheckDoc, ExerciseDoc, NodeDoc, TemplateDoc
from app.content.verify import (
    TemplateVerdict,
    check_template,
    effective_domain,
    l1_for,
    register_l1,
    subject_of,
)


def _tpl(prompt: str, *, params=None, constraint=None, answer_expr="a+b", semantics=None) -> TemplateDoc:
    return TemplateDoc(
        prompt=prompt,
        params=params or {"a": {"range": [1, 9], "exclude": []}, "b": {"range": [1, 9], "exclude": []}},
        constraint=constraint, answer_expr=answer_expr, semantics=semantics or {})


def _doc(node_id: str, tpl: TemplateDoc, *, level: str = "primary", group: str = "") -> tuple[NodeDoc, ExerciseDoc]:
    ex = ExerciseDoc(id="ex1", kind="template", difficulty=1, template=tpl,
                     check=CheckDoc(mode="numeric_value"))
    doc = NodeDoc(id=node_id, title="T", level=level, topic=group or level,
                  explanation={"role": "教师讲解稿", "body": "讲解。"}, exercises=[ex],
                  feynman={"task_prompt": "t", "rubric": {"dimensions": [{"key": "k", "weight": 1.0}]}})
    return doc, ex


# ---------- 必交①：造错必报 ----------

def test_gate_rejects_answer_expr_contradicting_independent_expect():
    """答案与**独立算式**矛盾（answer_expr 与 expect 不一致）→ 拒绝入库。

    用"每个 seed 都对不上"的构造（answer_expr = expect + 1）保证确定性；
    s27 那种"只在部分参数下对不上"（LCM vs a*b）另见下一条。
    """
    tpl = _tpl("求 {a} 和 {b} 的最大公因数。", answer_expr="gcd(a, b) + 1",
               semantics={"expect": "gcd(a, b)", "domain": {"nonneg": True, "integer": True}})
    doc, ex = _doc("primary.s99", tpl)
    v = check_template("primary.s99", doc, ex, seeds=3)
    assert v.ok is False
    assert any("答案与独立验算不一致" in p for p in v.problems), v.problems


def test_gate_rejects_lcm_template_written_as_product():
    """s27 形状：题面说"b 是 a 的倍数"而 constraint 为空 + answer_expr=a*b（条件与公式双错）。"""
    tpl = _tpl("求 {a} 和 {b} 的最小公倍数，其中 {b} 是 {a} 的倍数。",
               constraint=None, answer_expr="a*b",
               semantics={"expect": "lcm(a, b)", "requires": ["b % a == 0"],
                          "domain": {"nonneg": True, "integer": True}})
    doc, ex = _doc("primary.s27", tpl)
    v = check_template("primary.s27", doc, ex, seeds=8)
    assert v.ok is False
    assert any("未被 constraint 保证" in p for p in v.problems), v.problems   # 题面在说没保证的话
    assert any("答案与独立验算不一致" in p for p in v.problems), v.problems   # LCM ≠ a*b


def test_gate_rejects_condition_not_enforced_by_constraint():
    """`requires` 是题面条件：constraint 不保证它 → 反例必报（造错必报）。"""
    tpl = _tpl("求 {a} 和 {b} 的最大公因数（其中 {b} 是 {a} 的倍数）。",
               constraint=None, answer_expr="gcd(a, b)",
               semantics={"expect": "gcd(a, b)", "requires": ["b % a == 0"], "domain": {"nonneg": True}})
    doc, ex = _doc("primary.s98", tpl)
    v = check_template("primary.s98", doc, ex, seeds=2)
    assert v.ok is False
    assert any("未被 constraint 保证" in p for p in v.problems), v.problems
    # 补上 constraint 后 → 通过（同一算式，只是条件被强制）
    tpl2 = _tpl("求 {a} 和 {b} 的最大公因数（其中 {b} 是 {a} 的倍数）。",
                constraint="b % a == 0", answer_expr="gcd(a, b)",
                semantics={"expect": "gcd(a, b)", "requires": ["b % a == 0"], "domain": {"nonneg": True}})
    doc2, ex2 = _doc("primary.s98", tpl2)
    v2 = check_template("primary.s98", doc2, ex2, seeds=2)
    assert v2.ok is True, v2.problems


def test_gate_rejects_negative_count_in_primary():
    """小学学段政策：结果为负 → 拒（39-47 / 7 元买 8 元文具 这一类）。"""
    tpl = _tpl("计算 {a}-{b}。", answer_expr="a-b")
    doc, ex = _doc("primary.s97", tpl)
    v = check_template("primary.s97", doc, ex, seeds=4)
    assert v.ok is False
    assert any("结果为负" in p for p in v.problems), v.problems


def test_gate_rejects_fractional_discrete_quantity_when_declared():
    """声明 domain.integer 后，"半个苹果"必报（含约束缺失的题面条件）。"""
    tpl = _tpl("把 {a} 个苹果按 {b}:{c} 分给两人，第一人分得多少个？",
               params={"a": {"range": [10, 20], "exclude": []}, "b": {"range": [1, 3], "exclude": []},
                       "c": {"range": [1, 3], "exclude": []}},
               constraint=None, answer_expr="a*b/(b+c)",
               semantics={"expect": "a*b/(b+c)", "requires": ["a % (b + c) == 0"],
                          "domain": {"nonneg": True, "integer": True}})
    doc, ex = _doc("primary.s96", tpl)
    v = check_template("primary.s96", doc, ex, seeds=4)
    assert v.ok is False
    assert any("非整数" in p or "未被 constraint 保证" in p for p in v.problems), v.problems


# ---------- 必交②：换学科仍成立（通用层不吃数学 L1） ----------

def test_generic_layer_applies_to_non_math_subject():
    """**非数学学科**同样过通用层：自定义学科模板题"金额为负/个数非整"→ 被拒。

    该学科**没有注册 L1 验算器** → 只走通用层谓词（这正是"学科无关"的证明）。
    """
    sid = "s-testsubj"
    assert l1_for(sid) is None, "测试前提：自定义学科没有 L1 插件"
    # ① 金额可能为负 → 声明 nonneg 后必报
    tpl = _tpl("库存原有 {a} 箱，出库 {b} 箱，还剩多少箱？", answer_expr="a-b",
               semantics={"domain": {"nonneg": True}})
    doc, ex = _doc(f"{sid}.u01", tpl, level="第一章")
    v = check_template(f"{sid}.u01", doc, ex, seeds=8)
    assert v.ok is False and any("结果为负" in p for p in v.problems), v.problems
    assert v.l1 is None                      # 无 L1 验算器：只有通用层在起作用
    # ② 个数非整 → 声明 integer 后必报
    tpl2 = _tpl("把 {a} 个零件平均装进 {b} 个盒子，每盒装多少个？", answer_expr="a/b",
                semantics={"domain": {"nonneg": True, "integer": True}})
    doc2, ex2 = _doc(f"{sid}.u02", tpl2, level="第一章")
    v2 = check_template(f"{sid}.u02", doc2, ex2, seeds=8)
    assert v2.ok is False and any("非整数" in p for p in v2.problems), v2.problems


def test_generic_layer_no_declaration_is_finding_not_silent_pass():
    """未声明谓词 → **如实标 finding**（不是静默通过），且不猜题面关键词。"""
    tpl = _tpl("计算 {a} 加 {b} 等于多少元？", answer_expr="a+b")
    doc, ex = _doc("s-testsubj.u03", tpl, level="第一章")
    v = check_template("s-testsubj.u03", doc, ex, seeds=2)
    assert v.ok is True                       # 无谓词 → 不判违规（不猜）
    assert v.findings and any("未声明 semantics" in f for f in v.findings)


def test_primary_policy_adds_nonneg_but_not_integer():
    """学段政策只加 nonneg：分数加法（非整数）**不得**被误杀（实测踩过的假阳性）。"""
    from app.content.schemas import TemplateDoc as T

    tpl = T(prompt="同分母加法：{a}/{d} + {b}/{d} = ？（用 a/b 形式输入，如 3/5）",
            params={"d": {"range": [3, 10], "exclude": []}, "a": {"range": [1, 4], "exclude": []},
                    "b": {"range": [1, 4], "exclude": []}},
            constraint="a + b < d", answer_expr="(a + b) / d")
    doc, ex = _doc("primary.s95", tpl)
    dom, declared = effective_domain(doc, tpl)
    assert dom.get("nonneg") is True and "integer" not in dom and declared is False
    v = check_template("primary.s95", doc, ex, seeds=4)
    assert v.ok is True, v.problems


# ---------- 插件/命名空间 ----------

def test_subject_namespace_and_registry():
    assert subject_of("primary.s27") == "math"          # 学段命名空间 → math preset
    assert subject_of("s-abc.u01") == "s-abc"           # 自定义学科
    assert l1_for("math").name == "math-sympy"          # 注册表解析（无 if subject== 分支）

    class _Noop:
        name = "noop"

        def verify(self, **kw):  # pragma: no cover - 注册/解析即可
            return [], []

    register_l1("s-noop", _Noop())
    assert l1_for("s-noop").name == "noop"
    assert l1_for("s-unknown") is None


def test_pipeline_gate_entry_rejects_bad_template_md():
    """生成端入口（pipeline.validate_semantics）对坏模板返回错误 → 拒绝入库。"""
    from app.content import pipeline as pl

    md = (
        "---\n"
        "id: primary.s94\n"
        "title: 测试\n"
        "level: primary\n"
        "topic: 测试\n"
        "prereqs: []\n"
        "explanation:\n  role: 教师讲解稿\n  body: 讲解。\n"
        "exercises:\n"
        "  - id: ex1\n"
        "    kind: template\n"
        "    template:\n"
        "      prompt: \"求 {a} 和 {b} 的最小公倍数，其中 {b} 是 {a} 的倍数。\"\n"
        "      params:\n        a: {range: [2, 9]}\n        b: {range: [2, 9]}\n"
        "      answer_expr: \"a*b\"\n"
        "      semantics:\n"
        "        expect: \"lcm(a, b)\"\n"
        "        requires: [\"b % a == 0\"]\n"
        "    check:\n      mode: numeric_value\n"
        "feynman:\n  task_prompt: t\n  rubric:\n    dimensions:\n      - {key: k, weight: 1.0}\n"
        "---\n\n讲解。\n"
    )
    errs = pl.validate_semantics(md)
    assert errs, "坏模板必须被生成端闸门拒绝"
    assert any("独立验算不一致" in e or "未被 constraint 保证" in e for e in errs), errs
