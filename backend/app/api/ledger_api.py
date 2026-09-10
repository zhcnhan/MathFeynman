"""api.ledger：**「一切显性」账本**的读取端点（docs/09 R39 §1「总账页」）。

- ``GET /ledger``       总账（可按学科/类别筛；时间倒序）
- ``GET /ledger/cats``  类别计数（筛选项徽标）
- ``GET /ledger/snapshot/{subject_id}`` 某学科的账目快照（就地提示的"看全部"入口）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..service import ledger
from .deps import get_db

router = APIRouter(tags=["ledger"])


@router.get("/ledger")
def list_ledger(subject_id: str = "", category: str = "", limit: int = 200, offset: int = 0,
                db: Session = Depends(get_db)) -> dict:
    """总账：一处看全部（铁则要求"界面必须能看见"，不许拿日志文件当交付）。"""
    if category and category not in ledger.CATEGORIES:
        return {"entries": [], "count": 0,
                "categories": [{"key": k, "label": ledger.CATEGORY_LABELS_ZH[k]}
                               for k in ledger.CATEGORIES],
                "filter": {"subject_id": subject_id, "category": category},
                "note": f"类别非法：{category}（可用：" + "、".join(ledger.CATEGORIES) + "）"}
    out = ledger.list_entries(db, subject_id=subject_id, category=category,
                              limit=limit, offset=offset)
    out["counts"] = ledger.counts_by_category(db, subject_id=subject_id)
    return out


@router.get("/ledger/cats")
def ledger_categories(subject_id: str = "", db: Session = Depends(get_db)) -> dict:
    return {"counts": ledger.counts_by_category(db, subject_id=subject_id),
            "categories": [{"key": k, "label": ledger.CATEGORY_LABELS_ZH[k]}
                           for k in ledger.CATEGORIES]}


@router.get("/ledger/snapshot/{subject_id}")
def ledger_snapshot(subject_id: str, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    out = ledger.list_entries(db, subject_id=subject_id, limit=limit)
    out["counts"] = ledger.counts_by_category(db, subject_id=subject_id)
    return out


class LedgerIn(BaseModel):
    """（可选）由前端记录"用户可见的动作"（如学科停用）——统一走同一账本入口。"""

    category: str = ledger.CAT_OTHER
    object: str = ""
    reason: str = ""
    impact: str = ""
    remedy: str = ""
    subject_id: str = ""
    unit_id: str = ""


@router.post("/ledger", status_code=201)
def append_ledger(body: LedgerIn, db: Session = Depends(get_db)) -> dict:
    """手动补记一条（前端动作也可入账；类别非法 → 中文 422）。"""
    if body.category not in ledger.CATEGORIES:
        from .subjects import _err

        raise _err(422, "validation_error",
                   f"账本类别非法：{body.category!r}（可用：" + "、".join(ledger.CATEGORIES) + "）")
    e = ledger.Entry(category=body.category, object=body.object, reason=body.reason,
                     impact=body.impact, remedy=body.remedy, subject_id=body.subject_id,
                     unit_id=body.unit_id, created_at=ledger._now_iso())
    eid = ledger.write(e)
    return {"id": eid, **e.to_dict()}
