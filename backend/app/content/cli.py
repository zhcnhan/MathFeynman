"""app.content.cli：`content validate` / `content render <node_id> <seed>`（docs/04 §7）。

validate 深校验：文件结构(front-matter) → 图装配(重名/悬空/环) → 每个模板/固定题
确定性取样自检（sympy 可解析、约束成立、答案可验算）→ feynman rubric 结构。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import stages_dir
from .loader import load_library
from .templates import render_exercise

SELFCHECK_SEEDS = 8  # 每个模板题抽验的 seed 数


@dataclass
class ValidateReport:
    ok: bool
    nodes_loaded: int = 0
    exercises_checked: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    detail: str = ""


def _check_exercise(node_id: str, ex, errors: list[str], warnings: list[str]) -> None:
    """单题多 seed 自检：任一 seed 自检失败 → 该题 broken，报错。"""
    broken: list[str] = []
    for seed in range(SELFCHECK_SEEDS):
        rendered = render_exercise(node_id, ex, seed)
        if rendered.broken:
            broken.append(rendered.detail)
    if broken:
        errors.append(f"{node_id} / 练习 {ex.id}: 模板自检失败（broken）→ {broken[0]}")
    if not ex.interactive:
        warnings.append(f"{node_id} / 练习 {ex.id}: 未声明 interactive 模式")


def validate_library() -> ValidateReport:
    """全库结构/环/模板/验算检查（docs/04 §7、02 §5）。"""
    lib = load_library()
    report = ValidateReport(ok=lib.ok, nodes_loaded=len(lib.nodes), errors=list(lib.errors))
    dim_keys: list[str] = []
    for loaded in lib.nodes:
        doc = loaded.doc
        # feynman rubric 结构
        total_weight = sum(d.weight for d in doc.feynman.rubric.dimensions)
        if abs(total_weight - 1.0) > 1e-6:
            report.warnings.append(f"{doc.id}: rubric 权重和={total_weight:.3f}（≠1，将按归一化权重合成）")
        keys = [d.key for d in doc.feynman.rubric.dimensions]
        if len(set(keys)) != len(keys):
            report.errors.append(f"{doc.id}: rubric 维度 key 重复 {keys}")
        dim_keys.extend(keys)
        if not doc.feynman.socratic_followups:
            report.warnings.append(f"{doc.id}: 未配置 socratic_followups 追问主题")
        for ex in doc.exercises:
            report.exercises_checked += 1
            _check_exercise(doc.id, ex, report.errors, report.warnings)
    if not lib.nodes:
        report.detail = f"stages 目录 {stages_dir()} 存在；当前 0 个节点。"
    else:
        report.detail = f"校验 {len(lib.nodes)} 个节点、{report.exercises_checked} 道练习（每题抽验 {SELFCHECK_SEEDS} seed）。"
    report.ok = not report.errors
    return report


def render_demo(node_id: str, seed: int) -> str:
    """渲染示例题供人工抽检（docs/04 §7）。"""
    lib = load_library()
    loaded = lib.by_id.get(node_id)
    if loaded is None:
        raise KeyError(f"节点不存在: {node_id}（共 {len(lib.nodes)} 个）")
    lines = [f"# {loaded.doc.id} {loaded.doc.title}", ""]
    for ex in loaded.doc.exercises:
        r = render_exercise(node_id, ex, seed)
        lines.append(f"## 练习 {r.exercise_id}（mode={r.mode} difficulty={r.difficulty}）")
        lines.append(r.prompt)
        lines.append(f"--- 判题依据: {r.judge_payload()}")
        lines.append(f"--- canonical_answer: {r.canonical_answer}（仅人工抽检可见，不落前端）")
        if r.broken:
            lines.append(f"--- !! broken: {r.detail}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # Windows 终端编码加固：统一 UTF-8 输出
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - 非 TTY/不支持时忽略
        pass
    parser = argparse.ArgumentParser(prog="content", description="YanHui 内容库工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="全库结构/环/模板/验算检查")
    p_val.set_defaults(func=lambda a: _run_validate())

    p_render = sub.add_parser("render", help="渲染示例题供人工抽检")
    p_render.add_argument("node_id")
    p_render.add_argument("seed", type=int)
    p_render.set_defaults(func=lambda a: _run_render(a.node_id, a.seed))

    args = parser.parse_args(argv)
    return args.func(args)


def _run_validate() -> int:
    report = validate_library()
    print(
        f"content validate: ok={report.ok} nodes={report.nodes_loaded} "
        f"exercises={report.exercises_checked}"
    )
    for e in report.errors:
        print(f"  [error]   {e}")
    for w in report.warnings:
        print(f"  [warning] {w}")
    if report.detail:
        print(f"  note: {report.detail}")
    _semantics_report()
    return 0 if report.ok else 1


def _semantics_report() -> None:
    """R35 §12 语义自检闸门的**体检输出**（不阻断 validate：违规按 [semantics] 列出，便于全库体检）。"""
    from .loader import load_library
    from .verify import check_node

    lib = load_library()
    for loaded in lib.nodes:
        for v in check_node(loaded.doc, seeds=4):
            for p in v.problems:
                print(f"  [semantics] {v.node_id}/{v.ex_id}: {p}")
            for f in v.findings:
                print(f"  [semantics?] {v.node_id}/{v.ex_id}: {f}")


def _run_render(node_id: str, seed: int) -> int:
    try:
        print(render_demo(node_id, seed))
        return 0
    except KeyError as e:
        print(f"[error] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
