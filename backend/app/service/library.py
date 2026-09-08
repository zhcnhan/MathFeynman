"""service.library：内容库 → DB 同步 + 进程内库缓存（docs/02 §5、06 §3）。

- 运行库只加载 content/stages/（docs/04 §6）。
- nodes/edges 与文件保持一致：content_hash 变化则 upsert；消失则 enabled=0；
  用户进度（user_nodes）按节点 id 保留，不随内容编辑丢失。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .. import models
from ..content.loader import Library, load_library
from ..domain.graph import KnowledgeGraph
from .progress import recompute_states

_lock = threading.Lock()
_cached: Library | None = None
_cached_graph: KnowledgeGraph | None = None


@dataclass
class SyncReport:
    ok: bool
    nodes_synced: int = 0
    edges_synced: int = 0
    disabled: int = 0
    errors: list = field(default_factory=list)


def refresh_library() -> Library:
    """重读内容目录（进程内缓存）。"""
    global _cached, _cached_graph
    lib = load_library()
    with _lock:
        _cached = lib
        _cached_graph = lib.graph if lib.nodes else KnowledgeGraph([])
    return lib


def get_library() -> Library:
    if _cached is None:
        refresh_library()
    return _cached or Library()


def get_graph() -> KnowledgeGraph:
    if _cached_graph is None:
        refresh_library()
    return _cached_graph or KnowledgeGraph([])


def sync_content(db: Session) -> SyncReport:
    """把当前库写入 nodes/edges（幂等）；随后重算全部用户状态。"""
    report = SyncReport(ok=True)
    lib = refresh_library()
    if lib.errors:
        report.ok = False
        report.errors = list(lib.errors)
        return report

    present_ids: set[str] = set()
    for loaded in lib.nodes:
        doc = loaded.doc
        present_ids.add(doc.id)
        row = db.get(models.Node, doc.id)
        if row is None:
            row = models.Node(id=doc.id)
            db.add(row)
        row.yaml_path = str(loaded.path)
        row.title = doc.title
        row.level = doc.level
        row.topic = doc.topic
        row.objectives_json = list(doc.objectives)
        row.core_concepts_json = list(doc.core_concepts)
        row.feynman_json = doc.feynman.model_dump()
        row.content_hash = loaded.content_hash
        row.enabled = True
        report.nodes_synced += 1
    db.flush()  # autoflush=False：先落节点，保证边外键可引用
    # 消失的节点禁用（保进度不删行）
    for row in db.query(models.Node).filter(models.Node.enabled.is_(True)).all():
        if row.id not in present_ids:
            row.enabled = False
            report.disabled += 1
    # 边全量重建（与文件严格一致）
    db.query(models.Edge).delete()
    for loaded in lib.nodes:
        for p in loaded.doc.prereqs:
            db.add(models.Edge(node_id=loaded.id, prereq_id=p))
            report.edges_synced += 1
    db.flush()

    # 用户进度状态与图谱一致性重算
    for user in db.query(models.User).all():
        recompute_states(db, user.id, lib.graph)
    db.flush()
    return report


def ensure_user(db: Session, user_id: str = "local") -> models.User:
    """确保用户存在（users 行带默认画像，docs/03 §4）。"""
    user = db.get(models.User, user_id)
    if user is None:
        from ..domain.profile import Profile

        user = models.User(id=user_id, profile_json=Profile(user_id=user_id).to_dict())
        db.add(user)
        db.flush()
    return user


__all__ = ["SyncReport", "sync_content", "get_library", "refresh_library", "get_graph", "ensure_user"]
