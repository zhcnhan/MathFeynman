"""R63 任务 ③ · 主页请求序列的**墙钟探针**（真实库 / 真实内容目录）。

用途：把"主页点开要等几秒"这件事变成一把**可重跑的尺子**——按前端主页的请求顺序打一遍，
逐项打印耗时与合计，合计超过阈值就以**非 0** 退出。

跑法（仓库根目录；**不覆盖** MF_DB_PATH / MF_CONTENT_ROOT，用真实库与真实内容）：

    .venv\\Scripts\\python.exe backend\\tests\\home_perf_probe.py
    .venv\\Scripts\\python.exe backend\\tests\\home_perf_probe.py --threshold 400 --rounds 3

说明：
- 这个文件名**故意不叫** `test_*.py` ⇒ pytest 默认收集不会把它当用例（它要真实库，
  不该进 CI；CI 里那条"同一请求全库最多解析 1 次"的判定在 `test_r63_home_perf_cache.py`）。
- 只发**只读 GET**（启动时的 lifespan 会做一次内容同步，与真人打开程序时一样）。
- 阈值口径（工单 §4）：合计 ≤ 400 ms。改前实测约 2.9–3.1 s（dashboard/campaign 各约 1.5 s）。
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# 前端主页的请求顺序（R61 起的主页：学科卡 + 学习地图 + 今天要复习的 + 接着上次）
SEQUENCE = (
    "/api/subjects",
    "/api/dashboard",
    "/api/campaign",
    "/api/graph",
    "/api/review/queue",
    "/api/ledger?limit=20",
)

_real_safe_load = yaml.safe_load
_parse_counter: Counter = Counter()


def _counting_safe_load(stream, *a, **kw):
    """数一数这次请求解析了几个 YAML（按文件路径归口；给"全库最多解析 1 遍"留证据）。"""
    name = getattr(stream, "name", None) or "<string>"
    _parse_counter[str(name)] += 1
    return _real_safe_load(stream, *a, **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=400.0, help="合计耗时上限（毫秒）")
    ap.add_argument("--rounds", type=int, default=3, help="打几遍（第 1 遍＝冷启动后的第一遍）")
    args = ap.parse_args()

    rows: list[tuple[int, float, list[tuple[str, float]]]] = []
    cold_parses: Counter | None = None
    with TestClient(app) as c:
        for i in range(1, max(1, args.rounds) + 1):
            per: list[tuple[str, float]] = []
            total = 0.0
            for path in SEQUENCE:
                if i == 1:
                    _parse_counter.clear()
                    yaml.safe_load = _counting_safe_load  # type: ignore[assignment]
                t0 = time.perf_counter()
                r = c.get(path)
                dt = (time.perf_counter() - t0) * 1000.0
                if i == 1:
                    yaml.safe_load = _real_safe_load  # type: ignore[assignment]
                    cold_parses = (cold_parses or Counter()) + _parse_counter
                if r.status_code != 200:
                    print(f"  !! {path} -> HTTP {r.status_code}")
                per.append((path, dt))
                total += dt
            rows.append((i, total, per))

    print("真实库 · 主页请求序列（第 1 遍 = 冷，其后 = 热）：")
    worst = 0.0
    for i, total, per in rows:
        detail = "  ".join(f"{p.split('/api/')[-1]}={d:.0f}" for p, d in per)
        print(f"  第{i}遍：后端合计 {total:7.0f} ms   逐项：{detail}")
        worst = max(worst, total)

    first = rows[0][2]
    slow = sorted(first, key=lambda x: -x[1])[:2]
    print(f"  最慢两项：{'；'.join(f'{p} {d:.0f} ms' for p, d in slow)}")

    if cold_parses:
        top = cold_parses.most_common(3)
        print(f"  冷启动那遍解析过的 YAML 文件数：{len(cold_parses)}"
              f"（最多的 {top[0][0].split(chr(92))[-1]} × {top[0][1]}）")

    ok = worst <= args.threshold
    print(f"\n判定：最慢一遍 {worst:.0f} ms vs 阈值 {args.threshold:.0f} ms → "
          f"{'通过 ✅' if ok else '超阈值 ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
