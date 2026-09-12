"""内容自续流水线入口（docs/04 §6、docs/10 §2.3、docs/11 子步 7）。

用法（仓库根）：
  python scripts/gen_content.py generate --level primary --topic 数与运算 [--limit N] [--to-drafts] [--source ai|stub]
  python scripts/gen_content.py topics --level primary      # 查看蓝图主题分组

- 默认 source=stub：离线确定性出稿（机制端到端验证/演示）。
- source=ai：需 .env 配置 LLM_API_KEY，经 schema 化调用点 draft_content 由真模型按 docs/04 出稿；
  自动校验与入库策略同一套（结构/无环/渲染/sympy broken=0；**docs/12 P4：全学段默认自动入库**、
  标 source: auto；`--to-drafts` 可强制草稿；服务层（selfextend）另有纠错召回熔断自动转草稿）。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))

from app.content.pipeline import PipelineError, stub_drafter, generate_topic  # noqa: E402
from app.content.roadmap import all_levels_exist, load_roadmap  # noqa: E402


def _utf8io() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _ai_drafter():
    """AI 出稿 drafter（R13：复用后端 ai/drafting，单点维护；无 key → None）。"""
    from app.ai.drafting import make_ai_drafter

    return make_ai_drafter()


def cmd_generate(args) -> int:
    drafter = stub_drafter
    if args.source == "ai":
        ai_drafter = _ai_drafter()
        if ai_drafter is None:
            print("[warn] 未配置 LLM_API_KEY → 使用离线 stub 出稿（仅机制验证）")
        else:
            drafter = ai_drafter
    try:
        results = generate_topic(
            args.level,
            args.topic,
            drafter=drafter,
            limit=args.limit,
            force_drafts=(True if args.to_drafts else None),
        )
    except (PipelineError, KeyError) as e:
        print(f"[error] {e}")
        return 1
    failed = [r for r in results if r.status == "failed"]
    print(f"generate {args.level}:{args.topic} ->")
    for r in results:
        print(f"  {r.entry_id}: {r.status}" + (f" -> {r.path}" if r.path else "") +
              (f"  ERRORS: {'; '.join(r.errors[:3])}" if r.errors else ""))
    ok = sum(1 for r in results if r.status == "ok")
    print(f"summary: ok={ok} total={len(results)} failed={len(failed)} 失败率={len(failed)/max(len(results),1):.0%}")
    if failed:
        print("失败明细（供复核/人工精核）：")
        for r in failed:
            print(f"  - {r.entry_id}: {'; '.join(r.errors[:2])}")
    return 0


def cmd_topics(args) -> int:
    if args.level not in all_levels_exist():
        print(f"蓝图 {args.level} 不存在（现有：{all_levels_exist() or '无'}）")
        return 1
    roadmap = load_roadmap(args.level)
    topics: dict[str, int] = {}
    for e in roadmap.entries:
        topics[e.topic] = topics.get(e.topic, 0) + 1
    for t, n in topics.items():
        print(f"  {t}（{n} 条）")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8io()
    parser = argparse.ArgumentParser(prog="gen_content", description="YanHui 内容自续流水线")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("generate", help="按蓝图主题组批量生成内容")
    p.add_argument("--level", default="primary")
    p.add_argument("--topic", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--to-drafts", action="store_true", help="强制写入 _drafts（默认按学段策略）")
    p.add_argument("--source", choices=["ai", "stub"], default="stub")
    p.set_defaults(func=cmd_generate)

    p2 = sub.add_parser("topics", help="列出某学段蓝图主题分组")
    p2.add_argument("--level", default="primary")
    p2.set_defaults(func=cmd_topics)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
