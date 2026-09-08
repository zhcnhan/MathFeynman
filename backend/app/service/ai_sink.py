"""service.ai_sink：ai_logs 落库（docs/05 §6：所有调用记录可审计）。

由 api.deps 构造网关时注入；sink 是 ai 层与 DB 之间的唯一桥（ai 层自身不碰 DB）。
"""
from __future__ import annotations

from .. import models
from ..db import SessionLocal


def make_ai_log_sink():
    """返回写入 ai_logs 表的 sink（每次调用独立短事务，日志失败不影响主流程）。"""

    def sink(entry: dict) -> None:
        try:
            with SessionLocal() as db:
                db.add(
                    models.AiLog(
                        call_name=entry.get("call_name", ""),
                        model=entry.get("model", ""),
                        tier=entry.get("tier", ""),
                        prompt_tokens=entry.get("prompt_tokens", 0),
                        completion_tokens=entry.get("completion_tokens", 0),
                        ok=bool(entry.get("ok", False)),
                        error=entry.get("error"),
                        latency_ms=entry.get("latency_ms", 0),
                    )
                )
                db.commit()
        except Exception:  # 审计日志失败绝不影响业务
            pass

    return sink


__all__ = ["make_ai_log_sink"]
