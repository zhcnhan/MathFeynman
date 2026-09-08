"""pytest 会话级配置：任何 app 导入前把 DB 指到临时库，保证测试隔离。

另：收集 test_live_ai.py 前先把仓库根 .env 载入环境（该测试直接用 os.getenv 判 skip，
不经过 app.config 的自动加载；此处补上，保证配置了 Key 时真模型冒烟真正执行）。

`app_client`：session 级共享 TestClient。全 API 测试复用**单个** anyio portal，
避免多 with 生命周期下 TestClient 偶发死锁（主线程等 future / portal 空转）。
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests/conftest.py -> 仓库根


def _load_root_dotenv() -> None:
    dotenv_path = _REPO_ROOT / ".env"
    if not dotenv_path.exists():
        return
    try:  # python-dotenv 可用则优先
        from dotenv import load_dotenv

        load_dotenv(dotenv_path, override=False)
        return
    except Exception:
        pass
    # 兜底：极简解析 KEY=VALUE（不覆盖已存在的环境变量）
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_root_dotenv()

# 默认把 LLM_API_KEY 置空：单元/集成套件必须离线（不误触真模型、不阻塞在受限网络）。
# 显式开启真模型冒烟：设 MF_ALLOW_LIVE_AI=1 后运行 `pytest backend/tests/test_live_ai.py`
# （此时保留 .env 的 key；离线路径覆盖见 tests/test_live_ai.py 的 skip 条件）。
if os.environ.get("MF_ALLOW_LIVE_AI") != "1":
    os.environ["LLM_API_KEY"] = ""

_tmp_dir = tempfile.gettempdir()
_db_file = os.path.join(_tmp_dir, f"mf_pytest_{uuid.uuid4().hex}.db")
os.environ["MF_DB_PATH"] = _db_file

# 内容根隔离（R13/A3）：整套测试在真实 content/ 的**临时副本**上运行——
# 流水线/自续测试对 stages/_drafts 的写入与任何中断残留只落在临时副本，
# 绝不污染仓库内容（此前中断测试残留 auto 文件导致图谱校验失败）。
import shutil  # noqa: E402


def _ignore_runtime_auto(_directory: str, names: list[str]) -> list[str]:
    """测试从"人工基线"起步：排除用户/运行期生成的 *_auto.md（其状态由各测试自行产出）。"""
    return [n for n in names if n.endswith("_auto.md")]


_REPO_CONTENT = _REPO_ROOT / "content"
_TMP_CONTENT = os.path.join(_tmp_dir, f"mf_content_{uuid.uuid4().hex}")
if _REPO_CONTENT.exists():
    shutil.copytree(_REPO_CONTENT, _TMP_CONTENT, ignore=_ignore_runtime_auto)
os.environ["MF_CONTENT_ROOT"] = _TMP_CONTENT


@pytest.fixture(scope="session")
def app_client():
    """会话内唯一 TestClient（portal 只启停一次；lifespan 建表+内容同步一次）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _purge_runtime_auto() -> None:
    """把测试内容副本中所有运行期生成的 *_auto 文件清掉（R18：模块共享副本，
    各模块的 seed/unlock 生成必须于模块结束复位，避免级联污染后续模块）。"""
    from app.content import content_root, stages_dir
    from app.service.library import refresh_library

    targets = []
    drafts = content_root() / "_drafts"
    if drafts.exists():
        targets.extend(drafts.glob("*_auto.md"))
    stages = stages_dir()
    if stages.exists():
        targets.extend(stages.rglob("*_auto.md"))
    for p in targets:
        p.unlink(missing_ok=True)
    refresh_library()


@pytest.fixture(scope="module", autouse=True)
def _purge_runtime_auto_per_module():
    """每个测试模块结束后清理本会话副本中运行期生成的 *_auto（幂等；真实仓库不受影响）。"""
    yield
    _purge_runtime_auto()
