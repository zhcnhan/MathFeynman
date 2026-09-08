"""app.api.graph：图谱端点（docs/06 §1）。内容由启动时 sync（service.library）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..service import progress
from ..service.library import get_graph, get_library
from .deps import get_db

router = APIRouter(tags=["graph"])

USER = "local"


@router.get("/graph")
def get_graph_api(db: Session = Depends(get_db)) -> dict:
    """全图（节点+边+用户状态），前端渲染图谱。"""
    graph = get_graph()
    states = progress.state_map(db, USER, graph)
    return {
        "nodes": [
            {
                "id": nid,
                "title": graph.get(nid).title,
                "level": graph.get(nid).level,
                "topic": graph.get(nid).topic,
                "state": states.get(nid, "locked"),
            }
            for nid in graph.node_ids
        ],
        "edges": [
            {"node": node_id, "prereq": prereq}
            for node_id in graph.node_ids
            for prereq in graph.prereqs_of(node_id)
        ],
    }


@router.get("/nodes/{node_id}")
def get_node(node_id: str, db: Session = Depends(get_db)) -> dict:
    """节点元数据 + content 摘要（不含答案，docs/06 §1）。"""
    lib = get_library()
    loaded = lib.by_id.get(node_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"节点不存在: {node_id}"}})
    doc = loaded.doc
    return {
        "id": doc.id,
        "title": doc.title,
        "level": doc.level,
        "topic": doc.topic,
        "prereqs": doc.prereqs,
        "objectives": doc.objectives,
        "core_concepts": doc.core_concepts,
        "explanation": {"role": doc.explanation.role, "body": doc.explanation.body},
        "worked_examples": [{"prompt": w.prompt, "solution_steps": w.solution_steps} for w in doc.worked_examples],
        "exercises": [
            {
                "id": e.id,
                "kind": e.kind,
                "difficulty": e.difficulty,
                "mode": e.check.mode,
                "interactive": e.interactive,
                "prompt": e.prompt,  # 不含答案字段
            }
            for e in doc.exercises
        ],
        "feynman": {
            "task_prompt": doc.feynman.task_prompt,
            "rubric": [d.model_dump() for d in doc.feynman.rubric.dimensions],
            "pass_threshold": doc.feynman.rubric.pass_threshold,
        },
    }
