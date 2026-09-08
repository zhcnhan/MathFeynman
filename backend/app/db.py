"""SQLite engine/session 管理（docs/02 §5、docs/06 §3）。

- 本地单机单用户：无并发问题；仍启用 WAL。
- 迁移策略：MVP 用 create_all；结构变更时人工写 ALTER 迁移脚本放 backend/migrations/。
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from . import models
from .config import get_settings


def _make_engine(db_path: Path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")  # 热修 R7：写锁忙等 30s，防瞬时 500
        cursor.close()

    return engine


settings = get_settings()
engine = _make_engine(settings.db_path)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """建表（幂等）。启动时调用；单测可换临时库路径后重调。"""
    from . import models as m  # noqa: F401  确保所有模型注册

    models.Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """轻量上下文管理器：提交/回滚/关闭。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = ["engine", "SessionLocal", "init_db", "session_scope"]
