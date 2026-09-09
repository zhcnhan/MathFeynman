"""Phase B · B1：学科化单元内容出稿质量（docs/14 §10 试点：行星科学，离线 heuristic 可测）。

断言：
- 启发式出稿每单元 ≥3 道、≥2 种题型、题面无重复（消除"三题相同/全自评"）；
- 单批多单元内容互不重复（题面池）且全部可入库 + 加载 + 自检（NodeDoc 解析）；
- 科学类学科（行星科学）rubric 命中科学模板（evidence 维度）；
- AI（配 key）路径存在（CALL_UNIT_CONTENT schema），无 key 自动走启发式（离线不崩）。
"""
from __future__ import annotations

import uuid

import pytest

from app.content.loader import load_library
from app.content.schemas import NodeDoc

PLANET_TAGS = [
    "行星", "类地行星", "气态巨行星", "轨道", "自转与公转", "卫星", "太阳系", "小行星带",
    "彗星", "地外行星", "引力", "天文单位",
]


def _planet_outline_units(sid: str, count: int = 10):
    units = []
    for i in range(1, count + 1):
        tags = [PLANET_TAGS[i - 1], PLANET_TAGS[i % len(PLANET_TAGS)]]
        if tags[0] == tags[1]:
            tags = tags[:1] + ["概念" + str(i)]
        units.append({
            "id": f"{sid}.u{i:02d}",
            "title": f"行星科学 · 第 {i} 讲",
            "group": "行星科学主线",
            "objectives": [f"掌握 {tags[0]} 的核心要点并能举例说明",
                           f"能解释 {tags[1]} 与相邻概念的关系"],
            "concept_tags": tags,
        })
    return units


def _fetch_doc(node_id: str) -> NodeDoc:
    lib = load_library()
    loaded = lib.by_id.get(node_id)
    assert loaded is not None, f"内容未入库: {node_id}"
    return loaded.doc


class TestUnitContentQuality:
    def test_planet_science_outline_units_all_generate_multitype(self, app_client):
        sid = f"planet{uuid.uuid4().hex[:6]}"
        r = app_client.post("/api/subjects", json={"label": "行星科学", "subject_id": sid})
        assert r.status_code == 201
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": _planet_outline_units(sid), "status": "active",
                                 "source": "manual"})
        assert r.status_code == 200 and r.json()["revision"] == 1
        node_ids: list[str] = []
        try:
            for i in range(1, 11):
                uid = f"{sid}.u{i:02d}"
                rr = app_client.post(f"/api/subjects/{sid}/units/{uid}/content")
                assert rr.status_code == 200, rr.text
                body = rr.json()
                assert body["status"] in ("created", "exists"), body
                if body["status"] == "created":
                    node_ids.append(uid)
            # 内容全部落库可加载
            assert len(node_ids) >= 10
            seen_prompts: set[str] = set()
            all_prompt_pool: list[str] = []
            for uid in node_ids:
                doc = _fetch_doc(uid)
                modes = [e.check.mode for e in doc.exercises]
                assert len(doc.exercises) >= 3, uid
                assert len({m for m in modes if m}) >= 2, (uid, modes)  # ≥2 题型
                for e in doc.exercises:
                    key = re_norm(e.prompt)
                    assert key not in seen_prompts, f"题面重复（{uid}）: {e.prompt}"
                    seen_prompts.add(key)
                    all_prompt_pool.append(e.prompt)
                assert doc.feynman.rubric.dimensions  # rubric 存在
            # 科学 rubric：planet 学科命中科学模板（evidence 维度）
            science = {d.key for d in _fetch_doc(node_ids[0]).feynman.rubric.dimensions}
            assert "evidence" in science, science
        finally:
            app_client.delete(f"/api/subjects/{sid}")

    def test_heuristic_exercises_unit_level(self):
        """启发式出题（无 DB 路径）：题量/题型/去重底线。"""
        from app.outline.schemas import OutlineUnit
        from app.outline.generate import heuristic_exercises, validate_generic_content

        u = OutlineUnit(id="x.u01", title="行星轨道", group="g", objectives=["说明轨道形状",
                        "比较圆轨道与椭圆轨道"], concept_tags=["轨道", "椭圆"])
        exs = heuristic_exercises(u, sibling_tags=["黑洞", "恒星", "引力波", "暗物质"])
        assert 3 <= len(exs) <= 5
        assert len({e.check.mode for e in exs}) >= 2

    def test_ai_call_spec_registered(self):
        """B1：真模型学科化出稿入口存在（CALL_UNIT_CONTENT schema；无 key 自动降级启发式）。"""
        from app.ai.calls import CALL_UNIT_CONTENT
        from app.outline.generate import generate_unit_content  # noqa: F401

        assert CALL_UNIT_CONTENT.name == "unit_content_draft"
        assert CALL_UNIT_CONTENT.output_schema is not None


def re_norm(s: str) -> str:
    import re

    return re.sub(r"\s+", "", s)


class TestOfflineHeuristicNotBroken:
    def test_generate_without_key_falls_back_heuristic(self, app_client):
        """无 LLM_KEY 环境：内容生成走启发式并成功（离线可测，不依赖真模型）。"""
        sid = f"py{uuid.uuid4().hex[:6]}"
        app_client.post("/api/subjects", json={"label": "Python 入门", "subject_id": sid})
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": [{
                               "id": f"{sid}.a1", "title": "变量", "group": "g",
                               "objectives": ["理解变量赋值"], "concept_tags": ["变量", "赋值"]},
                           ], "status": "active", "source": "manual"})
        assert r.status_code == 200
        try:
            rr = app_client.post(f"/api/subjects/{sid}/units/{sid}.a1/content")
            assert rr.status_code == 200, rr.text
            assert rr.json()["status"] == "created"
        finally:
            app_client.delete(f"/api/subjects/{sid}")


class TestHeuristicChoiceShuffle:
    """Phase C C4（R23 B1#1）：heuristic 单选选项确定性乱序 + answer_index 同步。

    - 同单元/同大纲结构两次出稿 → 选项序与答案下标完全一致（确定性种子，内容幂等）；
    - 每个 single_choice 的 options[answer_index] == 该题正确项（一致性）；
    - 多单元抽样下正确项不恒为第 1 项（消除"永远选第一项"做题套路）。
    """

    TAGS = [
        "行星", "类地行星", "气态巨行星", "轨道", "自转与公转", "卫星", "太阳系", "小行星带",
        "彗星", "地外行星", "引力", "天文单位",
    ]

    def _sample_units(self):
        from app.outline.schemas import OutlineUnit

        units = []
        for i in range(1, 13):
            t0 = self.TAGS[i - 1]
            t1 = self.TAGS[i % len(self.TAGS)]
            tags = [t0, t1] if t0 != t1 else [t0, f"概念{i}"]
            units.append(OutlineUnit(
                id=f"c4.u{i:02d}", title=f"行星科学 · 第 {i} 讲", group="主线",
                objectives=[f"掌握 {t0} 的核心要点并能举例说明",
                            f"能解释 {t1} 与相邻概念的关系"],
                concept_tags=tags,
            ))
        return units

    def _run_once(self):
        from app.outline.generate import heuristic_exercises

        out: dict[str, list[tuple]] = {}
        for unit in self._sample_units():
            t0 = unit.concept_tags[0]
            siblings = [x for x in self.TAGS if x != t0][:6]
            exs = heuristic_exercises(unit, sibling_tags=siblings)
            for e in exs:
                if e.check.mode != "single_choice":
                    continue
                if e.id == "choose-tag":
                    assert e.options[e.answer_index] == t0, (unit.id, e.options, e.answer_index)
                elif e.id.startswith("choose-obj-"):
                    i = int(e.id.rsplit("-", 1)[1])
                    assert e.options[e.answer_index] == unit.objectives[i], \
                        (unit.id, e.options, e.answer_index)
                out.setdefault(unit.id, []).append(
                    (e.id, e.answer_index, tuple(e.options))
                )
        return out

    def test_deterministic_consistent_and_not_always_first(self):
        first = self._run_once()
        second = self._run_once()
        assert first == second  # 确定性：同输入两次出稿完全一致
        idxs = [ai for unit in first.values() for (_id, ai, _opts) in unit]
        assert len(idxs) >= 10
        assert any(i != 0 for i in idxs), f"正确项应随种子分布（不应恒第 1 项）: {idxs}"

