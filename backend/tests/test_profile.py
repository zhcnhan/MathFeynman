"""domain.profile 单测（docs/03 §4/§5）。"""
from __future__ import annotations

from app.domain.profile import DEPTH_MAX, DEPTH_MIN, ERROR_TYPES, Profile, style_block


def test_defaults():
    p = Profile()
    assert p.user_id == "local"
    assert p.preferred_explanation_depth == 2
    assert p.error_profile == {}
    assert p.session_counts == {"explain": 0, "feynman": 0}


def test_record_error_counts():
    p = Profile()
    p.record_error("arithmetic_slip")
    p.record_error("sign_error", 3)
    p.record_error("not_a_type")  # 非法类型归 unknown
    assert p.error_profile["arithmetic_slip"] == 1
    assert p.error_profile["sign_error"] == 3
    assert p.error_profile["unknown"] == 1


def test_error_type_enum_matches_docs():
    assert ERROR_TYPES == (
        "arithmetic_slip",
        "sign_error",
        "concept_confusion",
        "step_omission",
        "procedure_misuse",
        "notation_error",
        "unknown",
    )


def test_adjust_depth_clamped():
    p = Profile()
    for _ in range(20):
        p.adjust_depth(+1)
    assert p.preferred_explanation_depth == DEPTH_MAX
    for _ in range(30):
        p.adjust_depth(-1)
    assert p.preferred_explanation_depth == DEPTH_MIN


def test_depth_clamp_on_load():
    assert Profile(preferred_explanation_depth=99).preferred_explanation_depth == DEPTH_MAX
    assert Profile(preferred_explanation_depth=0).preferred_explanation_depth == DEPTH_MIN


def test_styling_notes_dedupe():
    p = Profile()
    p.add_styling_note("喜欢图形直观")
    p.add_styling_note("喜欢图形直观")
    assert p.styling_notes == ["喜欢图形直观"]


def test_roundtrip():
    p = Profile()
    p.record_error("concept_confusion")
    p.adjust_depth(+1)
    p.count_session("feynman")
    p2 = Profile.from_dict(p.to_dict())
    assert p2.to_dict() == p.to_dict()


def test_from_dict_ignores_unknown_keys():
    p = Profile.from_dict({"user_id": "local", "no_such_field": 1})
    assert p.user_id == "local"


def test_style_block_content():
    p = Profile()
    p.record_error("sign_error", 4)
    p.record_error("arithmetic_slip", 1)
    block = style_block(p)
    assert "解释深度档位 2" in block
    assert "sign_error×4" in block  # 高频错误提示注入（docs/05 §4）
