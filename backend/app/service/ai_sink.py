"""service.ai_sink：ai_logs 落库（docs/05 §6：所有调用记录可审计；R39 §3 扩字段）。

由 api.deps 构造网关时注入；sink 是 ai 层与 DB 之间的唯一桥（ai 层自身不碰 DB）。
R39：本 sink 现在是**审计索引**的写入点——全文在 ``service.ai_trace`` 落文件，这里只存元数据。
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
                        # R39 §3 扩字段（旧库由 db._migrate_columns 幂等补列）
                        subject_id=entry.get("subject_id", "") or "",
                        unit_id=entry.get("unit_id", "") or "",
                        retries=int(entry.get("retries", 0) or 0),
                        outcome=entry.get("outcome", "adopted") or "adopted",
                        prompt_versions=entry.get("prompt_versions", "") or "",
                        trace_path=entry.get("trace_path", "") or "",
                        trace_chars=int(entry.get("trace_chars", 0) or 0),
                        system_preview=entry.get("system_preview", "") or "",
                        user_preview=entry.get("user_preview", "") or "",
                        response_preview=entry.get("response_preview", "") or "",
                        parse_result=entry.get("parse_result", "") or "",
                    )
                )
                db.commit()
        except Exception:  # 审计日志失败绝不影响业务
            pass

    return sink


__all__ = ["make_ai_log_sink"]
