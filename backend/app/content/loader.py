"""app.content.loader：从 content/stages/ 加载节点文件并装配知识图谱（docs/04 §1-§2）。

运行库只加载 content/stages/ 下的 .md；content/_drafts/ 永不加载。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..domain.graph import KnowledgeGraph, NodeDef
from . import stages_dir
from .schemas import NodeDoc

FRONTMATTER_RE = re.compile(r"\A\ufeff?---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class ContentError(ValueError):
    """内容结构错误（解析/校验失败）。"""


@dataclass
class LoadedNode:
    doc: NodeDoc
    path: Path
    raw_text: str
    content_hash: str

    @property
    def id(self) -> str:
        return self.doc.id


@dataclass
class Library:
    """一次加载的内容库：节点文档 + 图谱。"""

    nodes: list[LoadedNode] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def graph(self) -> KnowledgeGraph:
        return KnowledgeGraph(
            [
                NodeDef(
                    id=n.doc.id,
                    title=n.doc.title,
                    level=n.doc.level,
                    topic=n.doc.topic,
                    prereqs=tuple(n.doc.prereqs),
                )
                for n in self.nodes
            ]
        )

    @property
    def by_id(self) -> dict[str, LoadedNode]:
        return {n.id: n for n in self.nodes}

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_node_text(raw_text: str) -> tuple[dict, str]:
    """YAML front-matter + Markdown 正文拆分。"""
    m = FRONTMATTER_RE.match(raw_text)
    if not m:
        raise ContentError("缺少 YAML front-matter（文件应以 --- 开始并以 --- 结束）")
    meta_yaml, body = m.group(1), raw_text[m.end() :]
    try:
        meta = yaml.safe_load(meta_yaml)
    except yaml.YAMLError as e:
        raise ContentError(f"front-matter YAML 解析失败: {e}") from e
    if not isinstance(meta, dict):
        raise ContentError("front-matter 必须是 YAML 映射")
    meta["body_md"] = body.strip()
    return meta, body


def load_node_file(path: Path) -> LoadedNode:
    raw = path.read_text(encoding="utf-8")
    meta, _ = parse_node_text(raw)
    try:
        doc = NodeDoc(**meta)
    except Exception as e:  # pydantic ValidationError 等 → 统一内容错误
        raise ContentError(f"{path.name}: {e}") from e
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return LoadedNode(doc=doc, path=path, raw_text=raw, content_hash=digest)


def load_library(root: Path | None = None) -> Library:
    """扫描 stages 全库并装配（结构错误收集进 Library.errors，不抛中断）。"""
    lib = Library()
    base = root or stages_dir()
    if not base.exists():
        lib.errors.append(f"stages 目录不存在: {base}")
        return lib
    md_files = sorted(base.rglob("*.md"))
    seen_ids: dict[str, str] = {}
    for path in md_files:
        try:
            loaded = load_node_file(path)
        except ContentError as e:
            lib.errors.append(str(e))
            continue
        if loaded.id in seen_ids:
            lib.errors.append(f"节点 id 重复: {loaded.id}（{seen_ids[loaded.id]} 与 {path}）")
            continue
        seen_ids[loaded.id] = str(path)
        lib.nodes.append(loaded)
    # 图谱装配校验（悬空 prereq/环）并入报告
    if lib.nodes:
        try:
            lib.graph
        except Exception as e:
            lib.errors.append(f"图谱装配失败: {e}")
    return lib


__all__ = ["Library", "LoadedNode", "ContentError", "load_library", "load_node_file", "parse_node_text"]
