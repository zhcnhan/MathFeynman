"""R37 **教材锚定审计**（工具，不是测试 —— 文件名不带 ``test_`` 前缀 → pytest 不收集、不随 CI）。

它回答一个只有人读内容时才会问的问题：**这份 AI 出稿，到底是不是从这本书里出的？**
判定口径与架构侧 R37 立项时的实测**完全一致**（同一把引文尺子 ``app.content.citations``）：

1. ``taught_facts[].text``（声明式知识包）能否在**该学科材料正文**里逐字查到；
2. 每道练习 ``basis.quote``（出题依据）同上；
3. 讲解正文的句子（按行/句切分，≥12 字）同上 —— 用来看"讲解是不是从教材演绎出来的"。

跑法（默认学科 ``s-f2decfcf``；只读盘上内容，**不调模型**）::

    .\\.venv\\Scripts\\python backend/tests/audit_material_binding.py [subject_id]
    .\\.venv\\Scripts\\python backend/tests/audit_material_binding.py --dir <stages 目录> --material <材料文件>

对照用法（R37 立项证据 / 改造后对照）::

    # 改造前归档样本
    ... audit_material_binding.py --dir D:\\DeepseekHarness\\_backups\\r37-before-20260910-195904\\stages-s-f2decfcf \
        --material D:\\DeepseekHarness\\_backups\\r37-before-20260910-195904\\subjects-s-f2decfcf\\materials\\researchgate-17551026c7.md

退出码：0 = 全部有据（或没有可判定的条目）；1 = 存在零接地条目（**这就是 R37 要堵的洞**）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.content import citations  # noqa: E402
from app.content import content_root  # noqa: E402

MIN_LECTURE_SENTENCE = 12  # 讲解句子的判定门槛（架构侧立项实测用的口径）


def _frontmatter(path: Path) -> dict:
    import yaml

    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return {}
    end = raw.find("\n---", 4)
    if end < 0:
        return {}
    return yaml.safe_load(raw[4:end]) or {}


def _material_text(material: Path | None, subject_id: str) -> tuple[str, list[str]]:
    """教材正文（多份材料拼接） + 材料标题清单（frontmatter 的正文之外部分不计入）。"""
    paths: list[Path] = []
    if material is not None:
        paths = [material]
    else:
        d = content_root() / "subjects" / subject_id / "materials"
        paths = sorted(d.glob("*.md"))
    chunks: list[str] = []
    titles: list[str] = []
    for p in paths:
        raw = p.read_text(encoding="utf-8")
        body = raw
        if raw.startswith("---\n"):
            end = raw.find("\n---", 4)
            if end > 0:
                fm = _frontmatter(p)
                titles.append(str(fm.get("title") or p.stem))
                body = raw[end + 4:]
        else:
            titles.append(p.stem)
        chunks.append(body)
    return "\n\n".join(chunks), titles


def _sentences(lecture: str) -> list[str]:
    out: list[str] = []
    for block in re.split(r"[\n。；;！!？?]", lecture or ""):
        s = block.strip().lstrip("#*-• ").strip()
        if len(citations.normalize(s)) >= MIN_LECTURE_SENTENCE:
            out.append(s)
    return out


def _has_verbatim_span(sentence: str, material_norm: str, span: int = MIN_LECTURE_SENTENCE) -> bool:
    """句子里是否含**教材逐字片段**（≥``span`` 字）。

    为什么补这条：S3 允许讲解"换措辞/举例/类比"（**不要求整句照抄**），所以"整句命中"只是下限；
    "句内含逐字片段"才反映"这句话是从教材演绎出来的"（引用式讲解会命中这一条）。
    """
    s = citations.normalize(sentence)
    if len(s) < span:
        return False
    return any(s[i:i + span] in material_norm for i in range(len(s) - span + 1))


def audit(subject_id: str, *, stages: Path | None = None, material: Path | None = None) -> dict:
    mtext, titles = _material_text(material, subject_id)
    if not citations.normalize(mtext):
        return {"subject": subject_id, "error": f"找不到教材正文（材料：{titles or '无'}）"}
    sdir = stages if stages is not None else (content_root() / "stages" / subject_id)
    files = sorted(sdir.glob("*.md")) if sdir.exists() else []
    facts_hit = facts_miss = 0
    basis_hit = basis_miss = 0
    sent_hit = sent_miss = 0
    sent_quoted = 0
    material_norm = citations.normalize(mtext)
    details: list[str] = []
    for f in files:
        doc = _frontmatter(f)
        for fact in doc.get("taught_facts") or []:
            text = str((fact or {}).get("text") or "")
            if citations.is_valid(text, mtext):
                facts_hit += 1
            else:
                facts_miss += 1
                details.append(f"  [事实句不在教材] {f.name}: {text[:60]}")
        for ex in doc.get("exercises") or []:
            quote = str(((ex or {}).get("basis") or {}).get("quote") or "")
            if not quote:
                continue
            if citations.is_valid(quote, mtext):
                basis_hit += 1
            else:
                basis_miss += 1
                details.append(f"  [题目引文不在教材] {f.name}/{ex.get('id')}: {quote[:60]}")
        lecture = str(((doc.get("explanation") or {}).get("body")) or "")
        for s in _sentences(lecture):
            if citations.is_valid(s, mtext):
                sent_hit += 1
            else:
                sent_miss += 1
            if _has_verbatim_span(s, material_norm):
                sent_quoted += 1
    return {
        "subject": subject_id, "materials": titles, "files": [f.name for f in files],
        "material_chars": len(mtext),
        "taught_facts": (facts_hit, facts_miss),
        "basis_quote": (basis_hit, basis_miss),
        "lecture_sentences": (sent_hit, sent_miss),
        "lecture_with_quote": (sent_quoted, sent_hit + sent_miss - sent_quoted),
        "zero_grounding": (facts_miss + basis_miss + sent_miss) > 0 and (facts_hit + basis_hit + sent_hit) == 0,
        "details": details,
    }


def _fmt(pair: tuple[int, int]) -> str:
    hit, miss = pair
    total = hit + miss
    pct = (100.0 * hit / total) if total else 100.0
    return f"{hit}/{total}（{pct:.0f}% 命中教材）"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="R37 教材锚定审计（工具，不随 CI）")
    ap.add_argument("subject", nargs="?", default="s-f2decfcf", help="学科 id（默认 s-f2decfcf）")
    ap.add_argument("--dir", default="", help="直接指定 stages 目录（对照归档样本时用）")
    ap.add_argument("--material", default="", help="直接指定材料文件（对照归档样本时用）")
    args = ap.parse_args(argv)
    r = audit(args.subject, stages=Path(args.dir) if args.dir else None,
              material=Path(args.material) if args.material else None)
    print(f"=== R37 教材锚定审计 · 学科 {r['subject']} ===")
    if r.get("error"):
        print("无法审计：" + r["error"])
        return 2
    print(f"教材：{'、'.join(r['materials'])}（{r['material_chars']} 字）")
    print(f"内容文件：{'、'.join(r['files']) or '（无）'}")
    print(f"taught_facts 命中教材：{_fmt(r['taught_facts'])}")
    print(f"basis.quote 命中教材：{_fmt(r['basis_quote'])}")
    print(f"讲解句子(≥{MIN_LECTURE_SENTENCE}字)整句命中教材：{_fmt(r['lecture_sentences'])}"
          "（S3 允许换措辞，整句照抄非硬要求）")
    print(f"讲解句内含教材逐字片段(≥{MIN_LECTURE_SENTENCE}字)：{_fmt(r['lecture_with_quote'])}"
          "（「讲解是从教材演绎的」这一条看这里）")
    if r["details"]:
        print("\n未接地明细（前 20 条）：")
        print("\n".join(r["details"][:20]))
    if r["zero_grounding"]:
        print("\n结论：**系统性零接地** —— 内容与教材没有字面交集（R37 要堵的洞）。")
        return 1
    print("\n结论：内容与教材有字面接地（无系统性零接地）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
