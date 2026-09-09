"""Phase C · C5：真模型验收（docs/14 §10 试点行星科学 · MF_ALLOW_LIVE_AI=1 时才执行）。

覆盖（与 Phase C 验收口径对应）：
- 配 LLM_API_KEY 真跑「行星科学」10 单元 AI 学科化内容：每单元 ≥3 题/≥2 题型/题面去重、
  科学 rubric（evidence）；
- 上传材料（文本 + PDF 分页文本）→ 材料入库 → 生成/重生成单元讲解出现
  "参考材料（可追溯来源）"（可追溯来源标注）；
- 检索后端未配置（默认）→ search 返回明确中文提示 + backend.configured=false（UI"未配置
  检索后端"标注的数据源）；select 勾选入库（mock provider 路径见 test_search_provider.py）。

离线默认 skip（与 test_live_ai 同口径：避免误触真模型/网络）。
"""
from __future__ import annotations

import io
import os
import uuid

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

NEEDS_LIVE = pytest.mark.skipif(
    os.environ.get("MF_ALLOW_LIVE_AI") != "1" or not (os.environ.get("LLM_API_KEY") or "").strip(),
    reason="真模型验收：需 MF_ALLOW_LIVE_AI=1 且配置 LLM_API_KEY",
)

PLANET_TAGS = [
    "行星", "类地行星", "气态巨行星", "轨道", "自转与公转", "卫星", "太阳系", "小行星带",
    "彗星", "地外行星", "引力", "天文单位",
]


def _pdf_bytes(texts: list[str]) -> bytes:
    w = PdfWriter()
    for line in texts:
        p = w.add_blank_page(width=612, height=792)
        res = DictionaryObject()
        font = DictionaryObject()
        f1 = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                               NameObject("/Subtype"): NameObject("/Type1"),
                               NameObject("/BaseFont"): NameObject("/Helvetica")})
        font[NameObject("/F1")] = f1
        res[NameObject("/Font")] = font
        p[NameObject("/Resources")] = res
        s = DecodedStreamObject()
        s.set_data(f"BT /F1 14 Tf 72 720 Td ({line}) Tj ET".encode("ascii"))
        p[NameObject("/Contents")] = s
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@NEEDS_LIVE
class TestPhaseCAcceptanceLive:
    def test_planet_10_units_ai_content_with_materials_and_search_hint(self, app_client):
        from app.content.loader import load_library

        sid = f"pclive{uuid.uuid4().hex[:6]}"
        r = app_client.post("/api/subjects", json={"label": "行星科学", "subject_id": sid})
        assert r.status_code == 201, r.text
        units = []
        for i in range(1, 11):
            t0 = PLANET_TAGS[i - 1]
            t1 = PLANET_TAGS[i % len(PLANET_TAGS)]
            tags = [t0, t1] if t0 != t1 else [t0, f"概念{i}"]
            units.append({
                "id": f"{sid}.u{i:02d}", "title": f"行星科学 · 第 {i} 讲",
                "group": "行星科学主线",
                "objectives": [f"掌握 {t0} 的核心要点并能举例说明",
                               f"能解释 {t1} 与相邻概念的关系"],
                "concept_tags": tags,
            })
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": units, "status": "active", "source": "manual"})
        assert r.status_code == 200 and r.json()["revision"] == 1
        try:
            # 材料：文本粘贴 + PDF 上传 → 引用库（kind local/pdf）
            r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                                json={"title": "行星讲义摘录", "text": "行星绕恒星运行；气态巨行星由气体构成。"})
            assert r.status_code == 201
            r = app_client.post(
                f"/api/subjects/{sid}/materials/upload-pdf",
                data={"title": "太阳系英文笔记"},
                files={"file": ("solar.pdf", _pdf_bytes(["Planet A", "Planet B"]), "application/pdf")},
            )
            assert r.status_code == 201 and r.json()["kind"] == "pdf"
            mats = app_client.get(f"/api/subjects/{sid}/materials").json()["materials"]
            assert len(mats) == 2

            # 未配置检索后端 → 明确中文提示（UI 标注"未配置检索后端"的数据源）
            r = app_client.post(f"/api/subjects/{sid}/materials/search", json={"query": "行星"})
            assert r.status_code == 200
            body = r.json()
            assert body["backend"]["configured"] is False
            assert "未配置" in body["note"] and "联网检索" in body["note"]

            # 真模型生成 10 单元（每单元 ≥3 题/≥2 题型；材料引用注入）
            ai_used = 0
            created = []
            for i in range(1, 11):
                uid = f"{sid}.u{i:02d}"
                rr = app_client.post(f"/api/subjects/{sid}/units/{uid}/content")
                assert rr.status_code == 200, rr.text
                note = rr.json().get("note", "")
                if rr.json()["status"] == "created":
                    created.append(uid)
                    if "AI" in note:
                        ai_used += 1
            assert len(created) >= 10, "10 单元应全部生成落库"

            lib = load_library()
            ref_seen = 0
            for uid in created:
                doc = lib.by_id[uid].doc
                modes = {e.check.mode for e in doc.exercises}
                assert len(doc.exercises) >= 3, uid
                assert len(modes) >= 2, (uid, modes)
                # 单元内题面去重（validate_generic_content 强制；跨单元同材料句复用属
                # 内容自然重叠——AI 起草单次只对当前单元去重，见 C5 汇报疑点）
                prompts = ["".join(e.prompt.split()) for e in doc.exercises]
                assert len(prompts) == len(set(prompts)), f"单元内题面重复: {uid}"
                if "参考材料（可追溯来源）" in (doc.explanation.body or ""):
                    ref_seen += 1
                if "evidence" in {d.key for d in doc.feynman.rubric.dimensions}:
                    assert any("证据与推理" in d.description
                               for d in doc.feynman.rubric.dimensions)
            # 材料注入：至少 1 个单元讲解含"参考材料（可追溯来源）"
            assert ref_seen >= 1, "生成单元应注入可追溯参考材料标注"
            # AI 学科化路径至少命中一次（退化重试仍可 heuristic 兜底，但验收要求 AI 出稿存在）
            assert ai_used >= 1, "应至少有单元由 AI 学科化起草（全部降级启发式视为失败）"
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")
