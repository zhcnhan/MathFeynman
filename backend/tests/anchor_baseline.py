"""R46 E：**人工内容锚点基线**（节点 id + 练习 id 集合）——生成一次入库，用例只比不改。

红线（docs/13 §2 / 工单 §6）：`content/stages/` 既有**人工**节点与练习 id **不得改动**。
R35–R45 期间一直是架构侧手工比对（`git diff <rev> -- content/`）——本模块把它变成：
一份入库的基线清单 + 一条只做比对的用例（`test_r46_e_anchor_baseline.py`）。

**口径**（与 `backend/tests/conftest.py` 一致）：只覆盖**仓库里的人工内容**（`.md`，排除
`*_auto.md`）——测试跑在内容临时副本上，而 conftest 会把 `*_auto.md` 剔除；运行期生成的
auto 内容（可再生成）不属本基线，否则每次生成都会误报。

**用法**（只在架构侧批准新增/改动人工节点后刷新基线，**用例绝不会自动改写它**）：

    .\\.venv\\Scripts\\python backend/tests/anchor_baseline.py --write   # 刷新基线（需显式跑）
    .\\.venv\\Scripts\\python backend/tests/anchor_baseline.py --check   # 只比对，打印中文差异
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MANIFEST_PATH = Path(__file__).with_name("anchor_baseline.json")
SCHEMA = "yanhui.anchor_baseline/1"
NOTE = "人工内容锚点基线（排除 *_auto.md）：节点 id → 练习 id 列表；只增不改需架构侧批准"

# 仓库根（backend/tests/anchor_baseline.py → 仓库根）
REPO_ROOT = Path(__file__).resolve().parents[2]
# 独立运行（`python backend/tests/anchor_baseline.py --write`）时也能 `import app`
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def scan_stages(root: Path) -> dict[str, list[str]]:
    """扫描内容目录 → ``{节点 id: [练习 id…]}``（人工文件；排序去重）。

    - **跳过** ``*_auto.md``（运行期生成的内容，口径见模块 docstring）；
    - 解析失败**不静默跳过**（直接抛错：内容坏了必须让人看见，而不是"少一个 id 也过"）。
    """
    from app.content.loader import load_node_file

    base = Path(root)
    if not base.exists():
        raise RuntimeError(f"内容目录不存在：{base}")
    out: dict[str, list[str]] = {}
    for path in sorted(base.rglob("*.md")):
        if path.name.endswith("_auto.md"):
            continue
        try:
            loaded = load_node_file(path)
        except Exception as e:  # 人工内容解析不了 → 报错（不静默）
            raise RuntimeError(f"人工内容文件解析失败：{path}（{e}）") from e
        out[str(loaded.id)] = sorted({str(ex.id) for ex in (loaded.doc.exercises or [])})
    return out


def build_manifest(root: Path) -> dict:
    nodes = scan_stages(root)
    return {"schema": SCHEMA, "note": NOTE, "source": "content/stages（排除 *_auto.md）",
            "node_count": len(nodes), "exercise_count": sum(len(v) for v in nodes.values()),
            "nodes": dict(sorted(nodes.items()))}


def load_manifest(path: Path | None = None) -> dict:
    p = Path(path) if path else MANIFEST_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def diff_report(manifest: dict, current: dict[str, list[str]]) -> list[str]:
    """比对基线 vs 现状 → **中文**差异行（空列表＝一致）。"""
    out: list[str] = []
    if str(manifest.get("schema") or "") != SCHEMA:
        out.append(f"- **基线清单格式不对**：期望 `{SCHEMA}`，实际 `{manifest.get('schema')}`"
                   "（清单文件被改坏/串了）")
    base = {str(k): [str(x) for x in (v or [])] for k, v in (manifest.get("nodes") or {}).items()}
    missing = sorted(set(base) - set(current))
    extra = sorted(set(current) - set(base))
    if missing:
        out.append("- **节点 id 缺失**（基线有、现状没有 → 疑似被改名/删除，违反锚点红线）："
                   + "、".join(missing))
    if extra:
        out.append("- **节点 id 新增**（现状有、基线没有 → 若确为新增，请架构侧批准后刷新基线）："
                   + "、".join(extra))
    for nid in sorted(set(base) & set(current)):
        b, c = set(base[nid]), set(current[nid])
        gone, new = sorted(b - c), sorted(c - b)
        if gone:
            out.append(f"- **练习 id 缺失**：{nid} → " + "、".join(gone))
        if new:
            out.append(f"- **练习 id 新增**：{nid} → " + "、".join(new))
    return out


def _content_stages() -> Path:
    """内容目录：优先环境变量（测试＝临时副本），否则仓库真实 `content/stages`。"""
    import os

    root = os.getenv("MF_CONTENT_ROOT") or str(REPO_ROOT / "content")
    return Path(root) / "stages"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    stages = _content_stages()
    if "--write" in args:
        man = build_manifest(stages)
        MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
        print(f"锚点基线已写入 {MANIFEST_PATH}：节点 {man['node_count']} 个，"
              f"练习 {man['exercise_count']} 道（排除 *_auto.md）")
        return 0
    man = load_manifest()
    diffs = diff_report(man, scan_stages(stages))
    if diffs:
        print("锚点清单与基线**不一致**：")
        print("\n".join(diffs))
        return 1
    print(f"锚点清单一致：节点 {man.get('node_count')} 个，练习 {man.get('exercise_count')} 道")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
