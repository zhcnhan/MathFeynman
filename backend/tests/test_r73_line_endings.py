"""R73 任务 ① 守卫用例：**入库（index/blob）里不许有 CRLF**。

口径（工单 §① + R72 裁定）：真正的坑是"**仓库里（index/blob）存的是 CRLF**"，不是工作树文件的字节
—— R71 那个坑就出在 index 侧：blob 存 CRLF，新 clone/新 worktree 一 checkout 就报"已修改"，
而 `git diff --ignore-cr-at-eol` 却是空的。

⚠️ **只守 `.gitattributes` 要求 LF 的文件**（`*.py` / `*.ts` / `*.tsx`，即 attr 含 `text eol=lf`）：
`docs/` 与 `content/` 按既有政策**维持 CRLF**，三个审计样本按红线**一个字不许改**，
它们**不在**守卫范围内（所以这里只认 `i/crlf` **且** attr 要求 LF 的文件）。

零副作用：只读 `git ls-files --eol`，不写文件、不改仓库状态。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def crlf_in_index(eol_output: str) -> list[str]:
    """挑出"**attr 要求 LF、但 index 侧是 CRLF**"的文件（纯字符串解析，便于阳性对照）。

    每行长这样（meta 与路径之间是 tab；meta 内部用空格对齐）::

        i/lf    w/lf    attr/text eol=lf      \\tbackend/app/__init__.py
    """
    bad: list[str] = []
    for line in eol_output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        tokens = parts[0].split()
        if not tokens:
            continue
        if tokens[0] == "i/crlf" and "text eol=lf" in " ".join(tokens[2:]):
            bad.append(parts[1].strip())
    return bad


def test_r73_a1_no_lf_required_file_is_crlf_in_the_index():
    proc = subprocess.run(["git", "ls-files", "--eol"], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, f"git ls-files --eol 跑不起来：{proc.stderr}"
    out = proc.stdout
    # 不许空转：输出里**必须真有条目**在被守卫，否则"报 0 个"什么也不能证明
    assert "attr/text eol=lf" in out, "输出里一条 attr/text eol=lf 都没有——守卫在空转"

    bad = crlf_in_index(out)
    assert bad == [], (
        "这些文件 `.gitattributes` 要求 LF，仓库里（index/blob）却存成了 CRLF ——"
        "新 clone / 新 worktree 一 checkout 就会报'已修改'：\n  " + "\n  ".join(bad))

    # **阳性对照**（同一用例内、纯字符串、零副作用）：含 i/crlf 的文本必须报得出来；
    # 同时证明"没有 LF 属性、政策上就该是 CRLF 的文件"（docs/）**不会**被误报。
    sample = ("i/lf    w/lf    attr/text eol=lf      \tbackend/app/ok.py\n"
              "i/crlf  w/crlf  attr/text eol=lf      \tbackend/app/bad.py\n"
              "i/crlf  w/crlf  attr/                 \tdocs/kept-crlf-on-purpose.md\n")
    assert crlf_in_index(sample) == ["backend/app/bad.py"], crlf_in_index(sample)
