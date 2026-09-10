"""R46 任务 E 用例：**人工内容锚点红线**防回归（架构侧要求，P1）。

背景：红线「`content/stages/` 既有节点与锚点 id 不得改动」在 R35–R45 期间**一直是架构侧手工比对**
（`git diff <rev> -- content/`）。人工比对不可能每次都做 → 本批把它变成**用例**：
对全部**人工**内容文件，断言"节点 id + 练习 id 集合"与入库基线清单一致。

- 基线清单：`backend/tests/anchor_baseline.json`（**生成一次入库**；口径＝排除 `*_auto.md`，
  与 `conftest.py` 剔除 auto 副本的做法一致）；
- **用例只比对、绝不改写清单**；
- 失败信息**中文**且**点名到 id**（缺了哪个 / 多了哪个）。
- 生成/刷新命令（需架构侧批准后才跑）：
  `.\.venv\Scripts\python backend/tests/anchor_baseline.py --write`
"""
from __future__ import annotations

import re
from pathlib import Path

import anchor_baseline as ab


def _stages_dir() -> Path:
    """测试环境的内容目录（conftest 已把 `MF_CONTENT_ROOT` 指到**临时副本**）。"""
    from app.content import content_root

    return content_root() / "stages"


def test_r46_e1_stages_node_and_exercise_ids_match_baseline():
    """**必交①**：人工内容锚点（节点 id + 练习 id）与入库基线**逐位一致**。"""
    man = ab.load_manifest()
    current = ab.scan_stages(_stages_dir())
    diffs = ab.diff_report(man, current)
    assert not diffs, (
        "人工内容锚点清单与基线不一致（红线：既有节点/练习 id 不得改动；"
        f"清单文件 {ab.MANIFEST_PATH.name}）：\n" + "\n".join(diffs))
    # 基线自身可读性锚点（防止清单被写空/写坏后"假通过"）
    assert int(man.get("node_count") or 0) == len(current) > 0, man.get("node_count")
    assert int(man.get("exercise_count") or 0) == sum(len(v) for v in current.values())


def test_r46_e2_baseline_never_auto_rewritten():
    """**必交（守护）**：基线与**真实仓库**的人工内容也一致——即清单确实取自入库人工内容，
    且**用例不会改写它**（跑完再读一次，字节不变）。"""
    before = ab.MANIFEST_PATH.read_bytes()
    real = ab.build_manifest(ab.REPO_ROOT / "content" / "stages")
    assert not ab.diff_report(ab.load_manifest(), real["nodes"]), \
        "入库基线必须与仓库真实人工内容一致（否则基线是过期/伪造的）"
    assert ab.MANIFEST_PATH.read_bytes() == before, "用例不得改写基线清单"


def test_r46_e3_comparator_catches_id_change_with_zh_message(tmp_path):
    """**必交②（造错）**：临时改一个节点 id（只改**副本**）→ 比对**必须报错**，
    且中文信息**点名该 id**（缺了原名、多了新名）；改回后恢复一致。"""
    src = _stages_dir()
    dst = tmp_path / "stages"
    # 只复制人工内容（口径一致），够造错即可
    for p in src.rglob("*.md"):
        if p.name.endswith("_auto.md"):
            continue
        q = dst / p.relative_to(src)
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(p.read_bytes())

    target = next(p for p in sorted(dst.rglob("*.md")) if "node_0101_" in p.name)
    original = target.read_text(encoding="utf-8")
    node_id = re.search(r"(?m)^id:\s*(\S+)\s*$", original).group(1)
    mutated = re.sub(r"(?m)^id:\s*\S+\s*$", f"id: {node_id}__TYPO", original, count=1)
    assert mutated != original
    try:
        target.write_text(mutated, encoding="utf-8")
        diffs = ab.diff_report(ab.load_manifest(), ab.scan_stages(dst))
        assert diffs, "改了节点 id 必须被拦住（否则红线形同虚设）"
        text = "\n".join(diffs)
        assert node_id in text, f"缺失的节点 id 必须点名：{text}"
        assert f"{node_id}__TYPO" in text, f"新增的节点 id 必须点名：{text}"
        assert "节点 id 缺失" in text and "节点 id 新增" in text, text
        assert any("\u4e00" <= ch <= "\u9fff" for ch in text)
    finally:
        target.write_text(original, encoding="utf-8")
    # 改回即恢复（证明差异确实来自那一次改动）
    assert not ab.diff_report(ab.load_manifest(), ab.scan_stages(dst))


def test_r46_e4_comparator_catches_exercise_id_change(tmp_path):
    """**必交②（造错·练习）**：临时改掉一个**练习 id** → 中文信息点名该练习 id。"""
    src = _stages_dir()
    dst = tmp_path / "stages"
    for p in src.rglob("*.md"):
        if p.name.endswith("_auto.md"):
            continue
        q = dst / p.relative_to(src)
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(p.read_bytes())

    current = ab.scan_stages(dst)
    node_id = next(n for n, exs in sorted(current.items()) if exs)
    ex_id = current[node_id][0]
    target_file = None
    for p in sorted(dst.rglob("*.md")):
        if re.search(rf"(?m)^\s*-?\s*id:\s*{re.escape(ex_id)}\s*$", p.read_text(encoding="utf-8")):
            target_file = p
            break
    assert target_file is not None, f"没找到含练习 id {ex_id} 的文件"
    original = target_file.read_text(encoding="utf-8")
    try:
        target_file.write_text(
            original.replace(f"id: {ex_id}", f"id: {ex_id}__TYPO", 1), encoding="utf-8")
        diffs = ab.diff_report(ab.load_manifest(), ab.scan_stages(dst))
        text = "\n".join(diffs)
        assert diffs and ex_id in text and f"{ex_id}__TYPO" in text, text
        assert "练习 id" in text, text
    finally:
        target_file.write_text(original, encoding="utf-8")
