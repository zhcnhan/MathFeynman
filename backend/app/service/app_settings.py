"""service.app_settings：运行时应用设置（键值表；R39 §3 的「开发者 / 调试」开关）。

**注意**："一切显性"铁则不靠开关决定"要不要留证据"——审计**默认记录**；
本开关只决定界面上的「AI 对话记录」入口是否出现。
"""
from __future__ import annotations

from .. import models

DEV_MODE = "developer_mode"


def _get(db, key: str, default: str = "") -> str:
    row = db.get(models.AppSetting, key)
    return default if row is None else (row.value or default)


def set_flag(db, key: str, value) -> None:
    row = db.get(models.AppSetting, key)
    text = "1" if value else "0"
    if row is None:
        db.add(models.AppSetting(key=key, value=text))
    else:
        row.value = text
    db.commit()


def developer_mode(db) -> bool:
    return _get(db, DEV_MODE, "0") == "1"


def view(db) -> dict:
    return {"developer_mode": developer_mode(db)}


__all__ = ["DEV_MODE", "developer_mode", "set_flag", "view"]
