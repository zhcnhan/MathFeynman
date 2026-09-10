"""content.citations：**引文纪律**（"引用必须逐字出自给定原文"）的单一实现。

为什么单独成模块：这条尺子有多个使用方，必须只有一份实现——
- 费曼评分卡 `evidence_quote`（R27/R30 F5：``service/feynman_ledger`` 委托本模块）；
- 大纲单元的**材料溯源**（R36 D2：``outline/materials`` 校验 `materials[].section`）；
- 出题/追问的 **basis 引文**（R35 S2，待实现：同一把尺子，不再重写包含校验）。

规则（与 R30 F5 既定口径一致，勿改语义）：
1. **归一化**：剔除空白与常见中英标点/引号/省略号（LLM 排版差异不该判无效）；
2. **最短长度门槛**：归一化后 < ``MIN_QUOTE_CHARS``（默认 6）字 → 无效
   ——极短引文（单字/词）能平凡通过"子串包含"，等于没有依据；
3. **子串包含**：归一化后的引文必须是归一化原文的子串。

面向用户的失败原因一律中文，且**区分**"过短"与"不在原文中"（便于学生/作者知道怎么补）。
"""
from __future__ import annotations

# 归一化时剔除的字符：空白 + 常见中英标点/引号/顿号 + 省略号（截断标记，非文本内容）
STRIP_CHARS = frozenset(
    " \t\r\n\u3000"
    "，。、；：？！“”‘’「」『』（）()《》〈〉【】[]{}\"'`~!@#$%^&*_-+=|\\/<>,.;:?"
    "\u2026\u22ef.．…"
)

# 引文最短门槛（归一化后字数）：与 R30 F5 的 evidence 口径同值（=feynman_ledger.MIN_EVIDENCE_CHARS）
MIN_QUOTE_CHARS = 6

# 无效原因文案（对外可见 → 中文；两个分支的措辞是既有测试锁定的口径）
SHORT_TEMPLATE = "引文过短（归一化后 {n} 字 < {min} 字），不足以作为依据（服务端已降级）"
MISSING_TEMPLATE = "引文不在{where}中（服务端包含校验未通过，已降级）"


def normalize(text: str) -> str:
    """归一化文本用于包含校验：剔除空白与标点（保留字母/数字/汉字）。"""
    return "".join(ch for ch in (text or "") if ch not in STRIP_CHARS)


def is_valid(quote: str, source: str, *, min_chars: int = MIN_QUOTE_CHARS) -> bool:
    """引文是否逐字出自原文（归一化子串包含 + 最短长度门槛）。"""
    q = normalize(quote)
    if len(q) < min_chars:
        return False
    return q in normalize(source)


def invalid_reason(quote: str, source: str, *, where: str = "给定原文",
                  min_chars: int = MIN_QUOTE_CHARS) -> str:
    """引文无效的中文原因（区分"过短"与"不在原文中"）。"""
    q = normalize(quote)
    if len(q) < min_chars:
        return SHORT_TEMPLATE.format(n=len(q), min=min_chars)
    return MISSING_TEMPLATE.format(where=where)


def check(quote: str, source: str, *, where: str = "给定原文",
          min_chars: int = MIN_QUOTE_CHARS) -> tuple[bool, str]:
    """一次拿到 (是否有效, 无效原因)；有效时原因为空串（调用方少写一个分支）。"""
    if is_valid(quote, source, min_chars=min_chars):
        return True, ""
    return False, invalid_reason(quote, source, where=where, min_chars=min_chars)


__all__ = [
    "STRIP_CHARS",
    "MIN_QUOTE_CHARS",
    "normalize",
    "is_valid",
    "invalid_reason",
    "check",
]
