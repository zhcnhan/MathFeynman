"""domain.graph 单测：构造校验（重名/悬空/环）+ 状态机 + 推荐 + 路径（docs/03 §1）。"""
from __future__ import annotations

import pytest

from app.domain.graph import (
    AVAILABLE,
    LEARNING,
    LOCKED,
    MASTERED,
    GraphError,
    NodeDef,
    KnowledgeGraph,
)


def make_graph() -> KnowledgeGraph:
    # 链：A → B → C；并支 D → C；孤立 E
    return KnowledgeGraph(
        [
            NodeDef(id="A", title="甲", level="middle", prereqs=()),
            NodeDef(id="B", title="乙", level="middle", prereqs=("A",)),
            NodeDef(id="C", title="丙", level="middle", prereqs=("B", "D")),
            NodeDef(id="D", title="丁", level="middle", prereqs=()),
            NodeDef(id="E", title="戊", level="middle", prereqs=()),
        ]
    )


def test_duplicate_id_rejected():
    with pytest.raises(GraphError, match="重复"):
        KnowledgeGraph([NodeDef(id="a"), NodeDef(id="a")])


def test_dangling_prereq_rejected():
    with pytest.raises(GraphError, match="不存在"):
        KnowledgeGraph([NodeDef(id="a", prereqs=("ghost",))])


def test_cycle_rejected():
    with pytest.raises(GraphError, match="环"):
        KnowledgeGraph(
            [
                NodeDef(id="a", prereqs=("b",)),
                NodeDef(id="b", prereqs=("c",)),
                NodeDef(id="c", prereqs=("a",)),
            ]
        )


def test_self_cycle_rejected():
    with pytest.raises(GraphError, match="环"):
        KnowledgeGraph([NodeDef(id="a", prereqs=("a",))])


def test_two_node_cycle_rejected():
    with pytest.raises(GraphError, match="环"):
        KnowledgeGraph([NodeDef(id="a", prereqs=("b",)), NodeDef(id="b", prereqs=("a",))])


def test_illegal_level_rejected():
    with pytest.raises(GraphError):
        KnowledgeGraph([NodeDef(id="a", level="moon")])


def test_initial_states():
    g = make_graph()
    # 无任何掌握 → 无 prereq 的 A/D/E available，B/C locked
    assert g.state_of("A", mastered=set()) == AVAILABLE
    assert g.state_of("B", mastered=set()) == LOCKED
    assert g.state_of("E", mastered=set()) == AVAILABLE
    assert sorted(g.available(mastered=set())) == ["A", "D", "E"]


def test_prereq_unlock_chain():
    g = make_graph()
    mastered = {"A"}
    assert g.state_of("B", mastered=mastered) == AVAILABLE
    assert g.state_of("C", mastered=mastered) == LOCKED  # 还差 B 与 D
    mastered = {"A", "B", "D"}
    assert g.state_of("C", mastered=mastered) == AVAILABLE


def test_mastered_overrides():
    g = make_graph()
    mastered = {"B"}
    assert g.state_of("B", mastered=mastered) == MASTERED  # 自身 mastered 优先
    assert g.state_of("A", mastered=mastered) == AVAILABLE  # A 无 prereq → available


def test_learning_state():
    g = make_graph()
    assert g.state_of("A", mastered=set(), learning={"A"}) == LEARNING
    # learning 中的节点不再是 recommended available
    assert "A" not in g.available(mastered=set(), learning={"A"})


def test_recommend_shallowest():
    g = make_graph()
    # A/D/E 均 available 且同层(0)：按 id 序取 A
    assert g.recommend(mastered=set()) == "A"
    mastered = {"A", "D", "E"}
    assert g.recommend(mastered=mastered) == "B"  # C 仍缺 B


def test_recommend_none_when_all_mastered():
    g = make_graph()
    assert g.recommend(mastered={"A", "B", "C", "D", "E"}) is None


def test_topological_layers():
    g = make_graph()
    order = g.topological_order()
    assert order[0:3] == ["A", "D", "E"]  # 层 0
    assert "C" not in order[0:3]
    assert set(order) == {"A", "B", "C", "D", "E"}


def test_children_and_ancestors():
    g = make_graph()
    assert sorted(g.children_of("D")) == ["C"]
    assert set(g.ancestors("C")) == {"A", "B", "D"}
    assert g.ancestors("A") == []


def test_path_to():
    g = make_graph()
    path = g.path_to("C")
    # 路径覆盖 C 的全部祖先且按层序排布（E 非 C 祖先不入路径）
    assert path[-1] == "C"
    assert set(path) == {"A", "B", "D", "C"}
    assert "E" not in path
    # 相邻两层不能颠倒：A/D（层0）在 B（层1）之前，B 在 C 之前
    assert path.index("B") > path.index("A") and path.index("B") > path.index("D")
    assert path.index("C") > path.index("B")


def test_available_returns_topological_order():
    g = make_graph()
    mastered = {"A"}
    assert g.available(mastered=mastered) == ["D", "E", "B"]  # 层 0 的 D/E 在前


# --------------------------------------------------------------------------
# 推荐学段顺序（USER_FEEDBACK Day1 🟡：0 掌握时不得先推高中）
# 排序：学段(primary→…→ai) → 图谱层序(最浅) → 编号
# --------------------------------------------------------------------------
def _stage_graph() -> KnowledgeGraph:
    return KnowledgeGraph(
        [
            NodeDef(id="high.0201", title="一次函数", level="high", prereqs=()),
            NodeDef(id="middle.0201", title="负数", level="middle", prereqs=()),
            NodeDef(id="primary.0102", title="分数意义", level="primary", prereqs=("primary.0101",)),
            NodeDef(id="primary.0101", title="运算顺序", level="primary", prereqs=()),
        ]
    )


def test_recommend_prefers_lowest_stage():
    """0 掌握时，有 primary 可学就绝不推荐 high（USER_FEEDBACK 场景回归）。"""
    g = _stage_graph()
    # 可学根节点：high.0201 / middle.0201 / primary.0101（primary.0102 需要前置）
    assert g.recommend(mastered=set()) == "primary.0101"


def test_recommend_stage_then_layer_then_id():
    # 同一学段内：先比层序（根优先），再比编号
    g = KnowledgeGraph(
        [
            NodeDef(id="primary.0101", title="a", level="primary", prereqs=()),
            NodeDef(id="primary.0102", title="b", level="primary", prereqs=("primary.0101",)),
            NodeDef(id="primary.0199", title="z", level="primary", prereqs=()),
            NodeDef(id="high.0201", title="h", level="high", prereqs=()),
        ]
    )
    # primary 根中编号最小 = primary.0101（早于 primary.0199 且早于 high）
    assert g.recommend(mastered=set()) == "primary.0101"
    # 掌握 primary.0101 后，primary.0102 解锁且层序 1；同层根 primary.0199 层 0 → 仍先根
    mastered = {"primary.0101"}
    assert g.recommend(mastered=mastered) == "primary.0199"
    # 小学全部学完 → 若只剩 high 根则推荐它
    mastered = {"primary.0101", "primary.0102", "primary.0199"}
    assert g.recommend(mastered=mastered) == "high.0201"


def test_recommend_missing_level_goes_last():
    g = KnowledgeGraph(
        [
            NodeDef(id="no-level-node", title="n", level="", prereqs=()),
            NodeDef(id="middle.0101", title="m", level="middle", prereqs=()),
        ]
    )
    assert g.recommend(mastered=set()) == "middle.0101"
