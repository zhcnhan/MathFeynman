"""阶段 3 子步 7：内容流水线（gen_content 核心）机制测试。

用离线 stub 出稿验证：结构校验 / 每题 sympy 自检 broken=0 / 入库策略（primary→stages 标 auto、
_drafts 强制路径）/ 幂等。测试写出的文件在用例结束清理，保持内容库稳定。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.content import content_root
from app.content.pipeline import (
    generate_sequence,
    generate_topic,
    stub_drafter,
    validate_candidate,
)
from app.content.roadmap import load_roadmap


def _cleanup(paths: list[str | None]) -> None:
    for p in paths:
        if p:
            f = Path(p)
            if f.exists():
                f.unlink()


def test_stub_drafter_markup_valid_and_selfcheck_clean():
    roadmap = load_roadmap("primary")
    entry = roadmap.by_id()["primary.s21"]
    raw = stub_drafter(entry)
    # 前置 s20 已知时结构/渲染/sympy 自检通过
    errors = validate_candidate(raw, {"primary.s20"})
    assert errors == []
    # 未知前置应报错（入库护栏）
    errors2 = validate_candidate(raw, set())
    assert errors2 and any("prereq" in e for e in errors2)


def test_generate_topic_batch_and_idempotency(tmp_path: pytest.TempPathFactory):
    # 主题"统计与概率"的传递前置链较长 → 限制为前 6 条观察 batch 行为
    results = generate_topic("primary", "统计与概率", limit=6)
    assert results, "应产出条目结果"
    statuses = {r.entry_id: r.status for r in results}
    assert any(s == "ok" for s in statuses.values())
    assert "failed" not in statuses.values(), [r.errors for r in results if r.errors]
    created = [r.path for r in results if r.status == "ok"]
    try:
        for p in created:
            assert Path(p).exists()
            text = Path(p).read_text(encoding="utf-8")
            assert "source: auto" in text  # 入库标注 auto
        # 幂等：再跑一遍 → 已生成条目报 exists
        results2 = generate_topic("primary", "统计与概率", limit=6)
        again = {r.entry_id: r.status for r in results2}
        for cid in statuses:
            if statuses[cid] == "ok":
                assert again.get(cid) == "exists", cid
    finally:
        _cleanup(created)


def test_force_drafts_policy_writes_to_drafts(tmp_path):
    results = generate_topic("primary", "统计与概率", limit=1, force_drafts=True)
    ok_paths = [r.path for r in results if r.status == "ok"]
    try:
        for p in ok_paths:
            assert "_drafts" in p and "stages" not in p
    finally:
        _cleanup(ok_paths)


def test_generate_sequence_anchor_covered(tmp_path):
    """锚点覆盖条目 → covered（不重复生成，前置自动翻译到真实节点）。"""
    roadmap = load_roadmap("primary")
    # s05-s08 均有 anchors；直接跑 s05 之前需 s04 在库中——这里用 sequence 只测 covered 判定
    results = generate_sequence(roadmap, ["primary.s05"])
    covered = [r for r in results if r.status == "covered"]
    assert covered, [r.status for r in results]
    assert results[0].status in ("covered", "exists")  # anchor 已在库 → 不落盘
