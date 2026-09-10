"""R35 §12 模板题**全库体检**（工具，不是测试；pytest 不收集 —— 文件名不带 test_ 前缀）。

逐条过一遍库里所有模板题，产出"缺陷清单 + 处置建议"：
1. **闸门裁决**（`content.verify`）：内容声明域 + L1 验算（math=sympy）→ 违规 / 无法验证；
2. **学段政策**：小学学段结果非负（负数 = 违反，如 39-47、7元买8元文具）；
3. **体检提示**（**只提示、不判定**，用于逼内容显式声明，避免"猜关键词当判据"）：
   - 题面含条件性表述（其中/倍数/余数/商/按…分/还剩）却未声明 `requires`/`constraint`；
   - 题面问离散量（多少个/几只/几元/几颗…）却未声明 `domain.integer`；
   - 题面要求"两个量"（商和余数 / 和、与）而答案只有一个数值；
   - **题面泄漏**：渲染出的标准答案数字**原样出现在题干里**（如"如 x=5"恰好等于答案）。

用法（离线、只读内容库；不写任何文件）：
    .\\.venv\\Scripts\\python backend/tests/audit_template_semantics.py [--json 路径]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 离散量名词（**仅用于体检提示**：逼内容声明 domain.integer；绝不用于闸门判定）
DISCRETE_NOUNS = ("个", "只", "颗", "本", "张", "支", "件", "朵", "根", "条", "块", "份", "人", "名", "位")
CONDITION_HINTS = ("其中", "倍数", "余数", "商", "按", "还剩", "剩下", "至少", "不超过", "最多", "不少于", "平均")
TWO_QUANTITY_HINTS = ("商和余数", "和余数", "和、", "以及", "分别")


def _unknown_names(answer_expr: str, params: dict) -> list[str]:
    """answer_expr 里出现的**既不是参数也不是已支持函数**的名字（R35 §13：这类名字会被静默当 1）。"""
    from app.content.exprs import MATH_LOCALS

    allowed = set(MATH_LOCALS) | set((params or {}).keys())
    return sorted({m.group(1) for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", str(answer_expr or ""))
                   if m.group(1) not in allowed})


def _hints(prompt: str, declared_domain: dict, declared_requires: list) -> list[str]:
    out: list[str] = []
    if any(h in prompt for h in CONDITION_HINTS) and not declared_requires:
        out.append("题面含条件性表述但未声明 semantics.requires（无法验证'题面是否说了没被约束保证的话'）")
    if any(n in prompt for n in DISCRETE_NOUNS) and "多少" in prompt and not declared_domain.get("integer"):
        out.append("题面问离散量（多少…个/只/元…）但未声明 domain.integer（须显式声明）")
    if any(h in prompt for h in TWO_QUANTITY_HINTS) and not declared_domain.get("multi"):
        out.append("题面可能要求多个量（如'商和余数'），答案却只有一个数值 —— 须声明 multi 或改题面")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="R35 §12 模板题全库体检")
    ap.add_argument("--json", default="", help="把结果写到该 JSON 路径（缺省只打印）")
    ap.add_argument("--seeds", type=int, default=8)
    args = ap.parse_args()

    sys.path.insert(0, str(REPO / "backend"))
    from app.content.loader import load_library
    from app.content.templates import render_exercise
    from app.content.verify import check_template

    lib = load_library()
    rows: list[dict] = []
    for loaded in sorted(lib.nodes, key=lambda n: n.doc.id):
        doc = loaded.doc
        for ex in doc.exercises:
            if ex.kind != "template":
                continue
            tpl = ex.template
            semantics = tpl.semantics if isinstance(tpl.semantics, dict) else {}
            declared_domain = dict(semantics.get("domain") or {}) if isinstance(semantics.get("domain"), dict) else {}
            declared_requires = list(semantics.get("requires") or [])
            v = check_template(doc.id, doc, ex, seeds=args.seeds)
            leaks: list[str] = []
            for seed in range(args.seeds):
                r = render_exercise(doc.id, ex, seed)
                if r.broken:
                    continue
                ans = str(r.canonical_answer).strip()
                if ans and re.search(rf"(?<![\d.]){re.escape(ans)}(?![\d.])", str(r.prompt)):
                    leaks.append(f"seed={seed}: 答案 {ans} 原样出现在题干（题面泄漏）")
            rows.append({
                "node": doc.id, "ex": ex.id, "level": doc.level,
                "prompt": tpl.prompt, "answer_expr": tpl.answer_expr, "constraint": tpl.constraint,
                "semantics": semantics, "domain_effective": v.domain, "l1": v.l1,
                "verified": v.verified, "l1_available": v.l1_available,
                "unknown_names": _unknown_names(tpl.answer_expr, tpl.params),
                "problems": v.problems, "findings": v.findings,
                "hints": _hints(tpl.prompt, declared_domain, declared_requires),
                "leaks": sorted(set(leaks)),
                "samples": v.samples,
            })

    n_bad = sum(1 for r in rows if r["problems"])
    n_no_expect = sum(1 for r in rows if any("未声明 semantics.expect" in p for p in r["problems"]))
    n_self = sum(1 for r in rows if any("文本完全相同" in p for p in r["problems"]))
    n_verified = sum(1 for r in rows if r.get("verified") and not r["problems"])
    print(f"模板题共 {len(rows)} 条；**违规 {n_bad} 条**"
          f"（无 expect {n_no_expect} / expect 自证 {n_self} / 其它 {n_bad - n_no_expect - n_self}）；"
          f"已独立验算并通过 {n_verified} 条；其余 = 未验算或未声明（**不得读作「全库已验证」**）")
    print("=" * 100)
    for r in rows:
        flag = "[BAD] 违规" if r["problems"] else ("[WARN] 未验算" if not r.get("verified") else "[OK] 已验算")
        print(f"{flag} {r['node']}/{r['ex']}  [{r['prompt']}]")
        print(f"      answer_expr={r['answer_expr']!r} constraint={r['constraint']!r} "
              f"semantics={'有' if r['semantics'] else '无'} l1={r['l1']}")
        for p in r["problems"][:3]:
            print(f"      x {p[:170]}")
        for h in r["hints"][:3]:
            print(f"      ? {h[:150]}")
        for lk in r["leaks"][:2]:
            print(f"      ! {lk[:150]}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("明细已写入:", args.json)
    return 1 if n_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
