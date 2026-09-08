"""domain.profile：用户画像（docs/03 §4）。纯数据模型 + 计数规则，零依赖。

- 字段对齐 docs/03 §4 的 profile JSON。
- 持久化（users.profile_json / /profile 端点）由 service 层负责；
  本模块只定义结构与变更操作（record_error/adjust_depth/add_styling_note 等）。
- 错误类型枚举 = docs/03 §5 七类 + unknown。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ERROR_TYPES = (
    "arithmetic_slip",   # 思路对，计算笔误
    "sign_error",        # 正负号系统性错误
    "concept_confusion", # 概念理解错位
    "step_omission",     # 跳过必要步骤
    "procedure_misuse",  # 方法用错
    "notation_error",    # 表达式/记号书写不合法
    "unknown",           # 无法归类（人工可订正）
)

DEPTH_MIN, DEPTH_MAX = 1, 5  # 解释深度档位（1 直觉类比 → 5 严格推导）

# 全局模型模式（docs/09 R12）：smart=规则全开；light=关触发但保 college/ai think；deep=全部 think
MODEL_MODES = ("smart", "light", "deep")
DEFAULT_MODEL_MODE = "smart"


@dataclass
class Profile:
    user_id: str = "local"
    preferred_explanation_depth: int = 2
    preferred_examples: list[str] = field(
        default_factory=lambda: ["生活类比", "几何直观", "纯代数"]
    )
    error_profile: dict[str, int] = field(default_factory=dict)
    styling_notes: list[str] = field(default_factory=list)
    session_counts: dict[str, int] = field(default_factory=lambda: {"explain": 0, "feynman": 0})
    model_mode: str = DEFAULT_MODEL_MODE  # R12：smart|light|deep

    def __post_init__(self) -> None:
        self.user_id = self.user_id or "local"
        depth = self.preferred_explanation_depth
        if depth is None:
            depth = 2
        self.preferred_explanation_depth = max(DEPTH_MIN, min(DEPTH_MAX, int(depth)))
        self.error_profile = {k: int(v) for k, v in (self.error_profile or {}).items()}
        if self.model_mode not in MODEL_MODES:
            self.model_mode = DEFAULT_MODEL_MODE

    # ---- 变更操作（service 调用，写回存储前） ----
    def record_error(self, error_type: str, delta: int = 1) -> None:
        """错误类型计数（docs/03 §4 error_profile）。"""
        if error_type not in ERROR_TYPES:
            error_type = "unknown"
        self.error_profile[error_type] = self.error_profile.get(error_type, 0) + delta

    def adjust_depth(self, delta: int) -> None:
        """解释深度 ±1（用户反馈/系统推断后调整）。"""
        self.preferred_explanation_depth = max(
            DEPTH_MIN, min(DEPTH_MAX, self.preferred_explanation_depth + delta)
        )

    def add_styling_note(self, note: str) -> None:
        """AI 从费曼交互提取的风格观察（须人工确认后入列；此处仅追加记录）。"""
        if note and note not in self.styling_notes:
            self.styling_notes.append(note)

    def count_session(self, kind: str) -> None:
        self.session_counts[kind] = self.session_counts.get(kind, 0) + 1

    # ---- 序列化 ----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Profile":
        return cls(**{k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__})


# 教学风格块：把画像渲染成 AI 注入模板的"风格提示"（docs/05 §4 供 M3 使用）
def style_block(profile: Profile) -> str:
    depth = profile.preferred_explanation_depth
    depth_desc = "直觉类比优先" if depth <= 2 else ("平衡" if depth == 3 else "严格推导优先")
    recent = ", ".join(
        f"{et}×{n}" for et, n in sorted(profile.error_profile.items(), key=lambda kv: -kv[1])[:3]
    )
    lines = [
        f"[风格] 解释深度档位 {depth}（{depth_desc}）；偏好例子：{'/'.join(profile.preferred_examples)}。",
    ]
    if recent:
        lines.append(f"      该生近期高频错误：{recent}，讲解与练习请针对性提示。")
    return "\n".join(lines)


__all__ = [
    "Profile",
    "style_block",
    "ERROR_TYPES",
    "DEPTH_MIN",
    "DEPTH_MAX",
    "MODEL_MODES",
    "DEFAULT_MODEL_MODE",
]
