"""R58 任务 A 用例：**渲染资源释放**（真缺陷修复）。

工单 §1.3 三条：
① 连续渲染 10 次后**不再攒下未关闭对象**（并用"R57 写法"做阳性对照，证明这把尺子有效）；
② **出错路径也关闭**（图太大那条分支）；
③ **回归**：渲染结果与 R57 **逐位一致**（尺寸/字节/dpi/sha256）。
"""
from __future__ import annotations

import gc
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.outline import pdfrender
from r58_support import alive_objects, isolate_model_and_cache, sample_pdf

@pytest.fixture(autouse=True)
def _isolate(app_client, monkeypatch, tmp_path):
    yield from isolate_model_and_cache(app_client, monkeypatch, tmp_path)


REPO = Path(__file__).resolve().parents[2]

# R57 实现（未修前）在同一固定样本上的渲染结果 —— 逐位一致锁值
R57_SHA = {
    1: ("0964b7d755256bc19ebf48cad0c4e52ed3bfbf11ba68b39b8e569f3152761311", 24087),
    2: ("2ffb38e655e507490c3b551edae34d5235073871e6021e9c482eb45c7d3a0e9e", 24229),
}


def test_r58_a1_no_open_documents_after_many_renders():
    """**A4-①**：连续渲染 10 次后，未关闭对象**一个都不多**（先做阳性对照验证尺子有效）。"""
    import pypdfium2 as pdfium

    data = sample_pdf(2)
    base = alive_objects()
    # 阳性对照：照 R57 的写法（不 close、引用留住）→ 尺子必须能测出泄漏
    keep = []
    for _ in range(3):
        doc = pdfium.PdfDocument(data)
        page = doc[0]
        bitmap = page.render(scale=1024 / page.get_size()[0])
        img = bitmap.to_pil()
        keep.extend([doc, page, bitmap, img])
    leaked = alive_objects()
    assert leaked.get("PdfDocument", 0) > base.get("PdfDocument", 0), \
        f"阳性对照没测出泄漏，说明这把尺子无效：{base} → {leaked}"
    for obj in keep:
        try:
            obj.close()
        except Exception:
            pass
    keep.clear()
    gc.collect()

    before = alive_objects()
    for _ in range(10):
        assert len(pdfrender.render_pages(data, width=1024)) == 2
    after = alive_objects()
    assert after == before, f"渲染后仍有未关闭对象：{before} → {after}"


def test_r58_a1_error_path_also_closes():
    """**A4-②**：出错路径（图太大）也把句柄关掉（R57 那条分支永远不会关 doc）。

    **R61 任务 B 更新**：那句报错改了文案（旧文案带内部变量名）——本用例只关心
    "**出错路径能走到、且是中文报错**"，故断言随之更新，意图不变。
    """
    data = sample_pdf(2)
    before = alive_objects()
    with pytest.raises(pdfrender.PdfRenderError) as e:
        pdfrender.render_pages(data, width=1024, max_bytes=1024)
    assert "出图太大" in str(e.value), str(e.value)
    assert alive_objects() == before, f"出错路径泄漏了：{before} → {alive_objects()}"
    pdfrender.render_pages(data, width=1024)          # 出错之后再渲染照样干净
    assert alive_objects() == before


def test_r58_a1_render_output_is_byte_identical_to_r57():
    """**A4-③ 回归**：同参数渲染结果与 R57 **逐位一致**。"""
    pages = pdfrender.render_pages(sample_pdf(2), width=1024)
    assert [p["page_no"] for p in pages] == [1, 2]
    for p in pages:
        want_sha, want_bytes = R57_SHA[p["page_no"]]
        assert p["bytes"] == want_bytes, f"第 {p['page_no']} 页字节数变了"
        assert hashlib.sha256(p["data"]).hexdigest() == want_sha, f"第 {p['page_no']} 页内容变了"
        assert (p["width"], p["height"], p["dpi_used"], p["format"]) == (1024, 1450, 123.9, "jpeg")


def test_r58_a1_no_open_objects_in_a_fresh_process(tmp_path):
    """**A4-①（进程级复核）**：起子进程真渲染 10 次，退出时**没有未关闭对象痕迹**。"""
    child = tmp_path / "child.py"
    log = tmp_path / "child.log"
    child.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{REPO / 'backend'}')\n"
        f"sys.path.insert(0, r'{REPO / '.runtime'}')\n"
        "from r58_leak_probe import PDF\n"
        "from app.outline import pdfrender\n"
        "for _ in range(10):\n"
        "    pdfrender.render_pages(PDF, width=1024)\n"
        "print('rendered 10x')\n",
        encoding="utf-8")
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.run([sys.executable, str(child)], stdout=f, stderr=subprocess.STDOUT,
                           cwd=str(REPO), env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           timeout=300)
    text = log.read_text(encoding="utf-8")
    assert p.returncode == 0, text
    assert "rendered 10x" in text
    for bad in ("still open", "access violation", "PdfDocument"):
        assert bad not in text, f"子进程退出时出现未关闭对象痕迹（{bad}）：\n{text}"
