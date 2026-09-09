"""app.outline：通用学科大纲与学科注册（docs/14 Phase A · subject/outline 数据模型）。

- Subject 学科（subjects 表注册：preset=math / custom=用户自建）；
- Outline 大纲（content/subjects/<subject_id>/outline.yaml 持久；单元级条目：
  标题/目标/概念标签集/前置/难度/分组/锚点；整份重生成 revision+1）；
- Concept Layer 概念标签库（A2 起：掌握证据挂 (subject, concept)）。

数学 = 预置学科 preset：现有五学段 roadmap 为数学大纲的持久治理载体（docs/14 §5），
本包提供 schema/校验/持久化/派生，供 math outline 派生与通用学科共用。
"""
from .schemas import (  # noqa: F401
    OUTLINE_SCHEMA_VERSION,
    SUBJECT_ID_RE,
    SUBJECT_KINDS,
    OutlineDoc,
    OutlineError,
    OutlineUnit,
    validate_outline_doc,
)
from .store import (  # noqa: F401
    PRESET_MATH,
    add_outline,
    create_subject,
    delete_subject,
    get_outline,
    get_subject,
    list_subjects,
    patch_outline_unit,
    subject_dir,
    subjects_root,
)
