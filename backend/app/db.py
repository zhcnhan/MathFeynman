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


def _migrate_legacy_db_path(db_path: Path) -> None:
    """品牌改名（MathFeynman→YanHui/颜回）后默认库名 mathfeynman.db → yanhui.db。
    新库不存在而旧库存在时，启动即搬移（一次）；被占用（旧服务仍运行）则跳过，下次启动再搬。"""
    if db_path.exists():
        return
    legacy = db_path.parent / "mathfeynman.db"
    if not legacy.exists():
        return
    try:
        for suffix in ("-wal", "-shm", ""):
            src = db_path.parent / f"mathfeynman.db{suffix}"
            dst = db_path.parent / f"yanhui.db{suffix}"
            if src.exists() and not dst.exists():
                src.rename(dst)
        print(f"[db] 已迁移旧库 mathfeynman.db → {db_path.name}")
    except PermissionError:
        print("[db] 旧库被占用，跳过迁移（下次启动再处理）")


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
_migrate_legacy_db_path(settings.db_path)
engine = _make_engine(settings.db_path)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _migrate_columns(engine) -> None:
    """旧库轻迁移：create_all 不会给已存在表加列；逐个 try-ALTER 补列（幂等）。"""
    import sqlalchemy as sa

    insp = sa.inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("feedback")}
    except sa.exc.NoSuchTableError:
        return
    missing: list[str] = []
    if "result" not in cols:
        missing.append("ALTER TABLE feedback ADD COLUMN result TEXT NOT NULL DEFAULT ''")
    if "updated_at" not in cols:
        missing.append("ALTER TABLE feedback ADD COLUMN updated_at DATETIME")
    # B4：subjects 停用标记（"移除可恢复"；旧库缺列补默认启用）
    try:
        scol = {c["name"] for c in insp.get_columns("subjects")}
        if "enabled" not in scol:
            missing.append("ALTER TABLE subjects ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 1")
        if "removed_at" not in scol:
            missing.append("ALTER TABLE subjects ADD COLUMN removed_at DATETIME")
    except sa.exc.NoSuchTableError:
        pass
    for stmt in missing:
        with engine.begin() as conn:
            conn.execute(sa.text(stmt))


def init_db() -> None:
    """建表（幂等）。启动时调用；单测可换临时库路径后重调。"""
    from . import models as m  # noqa: F401  确保所有模型注册

    models.Base.metadata.create_all(engine)
    _migrate_columns(engine)


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
