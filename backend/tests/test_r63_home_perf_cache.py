"""R63 用例：把"**一次请求只解析一遍全库**"钉成回归（离线、临时内容目录，可进 CI）。

背景（架构侧 R62 实测确诊）：主页慢不是前端瀑布，是**后端每个请求把同一个内容库重复解析 10 遍**——
`service/selfextend.py::_lib_ids()` 当时直接 `load_library()`（无缓存），被 `next_pending_topics()` /
`mastered_ratio()` 在学段循环里放大，`/api/dashboard`、`/api/campaign` 各约 1.5 秒。

三条用例：
- **A-①**：一次 `/api/dashboard` 里，**每个内容文件最多被读/解析 1 次**（改前是 10 次量级）；
- **A-②（阳性对照）**：把 `_lib_ids` **还原成旧写法** → 同一个文件被读多次 ⇒ 证明这把尺子量得到
  （照 R58 那次"阳性对照"的做法：先用坏代码证明尺子有效，再断言好代码为零/达标）；
- **A-③**：任务 ② 的蓝图缓存——命中缓存、文件一变立刻读到新的、**新增/删除** `content/roadmap/*.yaml`
  也能立刻反映（目录枚举纳入指纹），并提供清缓存入口。

量法：`pathlib.Path.read_text` 计数器——`content/loader.load_node_file()` 与
`content/roadmap.load_roadmap()` 都是"读文件 + 解析"，按**文件路径**归口最精确，也不受
"`yaml.safe_load` 收到的是字符串、拿不到文件名"的限制。
"""
from __future__ import annotations

import pathlib

import pytest

# ============================================================ 计数器（按文件路径归口）

def _count_reads(monkeypatch) -> dict[str, int]:
    """给 `Path.read_text` 装计数器：{绝对路径: 读了几次}。"""
    reads: dict[str, int] = {}
    real = pathlib.Path.read_text

    def counting(self: pathlib.Path, *a, **kw):  # type: ignore[no-untyped-def]
        key = str(self)
        reads[key] = reads.get(key, 0) + 1
        return real(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", counting)
    return reads


def _content_reads(reads: dict[str, int], suffix: str) -> dict[str, int]:
    from app.content import content_root

    root = str(content_root())
    return {k: v for k, v in reads.items() if k.startswith(root) and k.endswith(suffix)}


# ============================================================ A-① 一次请求只解析一遍

def test_r63_a1_one_dashboard_request_reads_each_content_file_at_most_once(app_client, monkeypatch):
    """**A-①**：一次 `/api/dashboard` 里，没有任何内容文件被读第二遍。

    除了端点本身，还要打**学段循环**那条直连路径（`auto_check()` 就是按学段依次调
    `next_pending_topics()`／`mastered_ratio()`）——它是"10 遍全库"的放大器，
    也是**与数据库状态无关**的那一半断言（数学被停用时端点可能根本不走这条线）。
    """
    import app.service.selfextend as se
    from app.content import content_root, stages_dir

    md_files = [p for p in stages_dir().rglob("*.md")]
    yml_files = [p for p in (content_root() / "roadmap").glob("*.yaml")]
    assert len(md_files) >= 5, f"临时内容目录里内容文件太少（{len(md_files)}），这条用例会失去意义"
    assert yml_files, "临时内容目录里没有蓝图文件"
    levels = se.roadmap_levels()
    assert levels, "临时内容目录里没有可用学段"

    # 先打一次，让进程内缓存就绪（等价于"程序启动后第一屏"的正常状态）
    assert app_client.get("/api/subjects").status_code == 200

    reads = _count_reads(monkeypatch)
    r = app_client.get("/api/dashboard")
    assert r.status_code == 200, r.text
    # 学段循环（放大器）：把所有学段各走一遍 —— 修复前这里就是 5~10 遍全库
    for lv in levels:
        se.next_pending_topics(lv)

    md = _content_reads(reads, ".md")
    yml = _content_reads(reads, ".yaml")
    repeated_md = {k: v for k, v in md.items() if v > 1}
    repeated_yml = {k: v for k, v in yml.items() if v > 1}
    assert not repeated_md, (
        f"一次 /api/dashboard + 学段循环里这些内容文件被读了多次（全库重复解析）：{repeated_md}")
    assert not repeated_yml, f"一次 /api/dashboard 里这些蓝图/大纲文件被读了多次：{repeated_yml}"


def test_r63_a1b_campaign_and_selfextend_status_are_also_single_pass(app_client, monkeypatch):
    """**A-①（补）**：另外两个重灾接口（`/api/campaign`、`/api/selfextend/status`）同样一遍。"""
    app_client.get("/api/subjects")
    for path in ("/api/campaign", "/api/selfextend/status"):
        reads = _count_reads(monkeypatch)
        assert app_client.get(path).status_code == 200, path
        repeated = {k: v for k, v in _content_reads(reads, ".md").items() if v > 1}
        assert not repeated, f"{path} 里这些内容文件被读了多次：{repeated}"


# ============================================================ A-② 阳性对照

def test_r63_a2_positive_control_old_lib_ids_is_measurably_worse(app_client, monkeypatch):
    """**A-②（阳性对照）**：还原旧写法（`_lib_ids` 直接 `load_library()`）→ 尺子必须量到重复读。

    两段都在**同一条直连路径**上（学段循环），所以不看数据库/学科状态，结果稳定：
    - 现在的实现：跑 5 个学段，每个内容文件最多读 1 次；
    - 旧写法：同样 5 个学段，同一个文件被读 5 次（＝架构侧实测的"10 遍全库"同源）。
    这条**故意用坏实现**：它证明 A-① 不是"恒真断言"。
    """
    import app.service.selfextend as se
    from app.content.loader import load_library

    levels = se.roadmap_levels()
    assert levels, "临时内容目录里没有可用学段"

    # ---- 阶段 1：现在的实现（走缓存） ----
    for lv in levels:
        se.next_pending_topics(lv)                     # 预热
    reads_now = _count_reads(monkeypatch)
    for lv in levels:
        se.next_pending_topics(lv)
    worst_now = max(_content_reads(reads_now, ".md").values(), default=0)

    # ---- 阶段 2：还原成基线 05c5baa 的写法 ----
    monkeypatch.setattr(se, "_lib_ids", lambda: set(load_library().by_id))
    se.next_pending_topics(levels[0])                  # 预热
    reads_old = _count_reads(monkeypatch)
    for lv in levels:
        se.next_pending_topics(lv)
    worst_old = max(_content_reads(reads_old, ".md").values(), default=0)

    assert worst_now <= 1, f"现在的实现仍然重复解析全库（同一文件 {worst_now} 次）"
    assert worst_old >= 3, (
        f"阳性对照没量到重复解析（旧写法下同一文件最多只被读了 {worst_old} 次）——"
        "说明这把尺子量不到问题，A-① 的断言不可信，必须先修量法")


# ============================================================ A-③ 蓝图缓存（任务 ②）

def test_r63_a3_roadmap_cache_hits_and_invalidates(tmp_path, monkeypatch):
    """**A-③**：蓝图缓存命中 / 文件一变立刻读到新的 / 新增删除文件也能反映 / 有清缓存入口。"""
    from app.content import roadmap as rm

    root = tmp_path / "content"
    (root / "roadmap").mkdir(parents=True)
    monkeypatch.setenv("MF_CONTENT_ROOT", str(root))
    rm.clear_roadmap_cache()
    p = root / "roadmap" / "primary.yaml"
    p.write_text("level: primary\nentries:\n  - id: primary.0001\n    title: 甲\n    topic: 主题甲\n",
                 encoding="utf-8")

    reads = _count_reads(monkeypatch)
    a = rm.load_roadmap("primary")
    b = rm.load_roadmap("primary")
    assert a is b, "第二次应当命中缓存（同一个对象）"
    assert reads.get(str(p)) == 1, f"缓存命中时不该再读盘（读了 {reads.get(str(p))} 次）"

    # 文件变了（内容与大小都变）→ 指纹变化 → 立刻读到新的
    p.write_text("level: primary\nentries:\n  - id: primary.0002\n    title: 乙乙\n    topic: 主题乙\n",
                 encoding="utf-8")
    c = rm.load_roadmap("primary")
    assert [e.id for e in c.entries] == ["primary.0002"], "文件改了却读到旧内容"

    # 新增一个学段文件 → all_entries() 也要能看到（目录枚举纳入指纹）
    (root / "roadmap" / "middle.yaml").write_text(
        "level: middle\nentries:\n  - id: middle.0001\n    title: 丙\n    topic: 主题丙\n",
        encoding="utf-8")
    reg = rm.all_entries()
    assert "middle.0001" in reg and "primary.0002" in reg, sorted(reg)

    # 删掉 → 也一样立刻反映
    (root / "roadmap" / "middle.yaml").unlink()
    assert "middle.0001" not in rm.all_entries(), "文件删了却还在注册表里"

    # 显式清缓存入口（形状照 service/outline_gate.clear_outline_cache）
    rm.clear_roadmap_cache()
    d = rm.load_roadmap("primary")
    assert d is not c, "clear_roadmap_cache() 之后应当重新解析"


def test_r63_a4_all_entries_returns_a_copy(app_client):
    """**A-③（补）**：`all_entries()` 返回浅拷贝——调用方改它不会污染进程缓存。"""
    from app.content import roadmap as rm

    first = rm.all_entries()
    assert first, "临时内容目录里应当有蓝图条目"
    key = next(iter(first))

    first.clear()                                     # 调用方清空这份拷贝
    first[key] = ("primary", None)                    # 调用方往这份拷贝里塞脏数据
    again = rm.all_entries()
    assert again, "调用方改了返回值之后，缓存里的注册表不该跟着空"
    assert again[key] != ("primary", None), "调用方改了返回值，缓存被污染了"
    assert key in again
