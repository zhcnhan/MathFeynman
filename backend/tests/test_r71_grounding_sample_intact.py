"""R71 任务 ① 用例：**入库样本没被改坏**（毫秒级自检，堵住"静默失效"）。

R69 把 R37 教材锚定审计的样本入了库（`backend/tests/fixtures/grounding_sample/`）。
但样本被误删、被"顺手改一个字节"时，**没有任何东西会报警** —— 那是静默失效：
审计照样能跑，只是它现在审的不再是当初那份东西，17/17、6/6、9/83、37/83 会悄悄变成别的数。

本用例只做两件事（工单 §①）：

1. 三个样本文件**存在**（教材 + 两个内容节点）；
2. 它们的 **SHA256 与 README 里登记的指纹一致**；不一致就**指名道姓说哪个文件变了**。

**它不跑完整审计**（那是约 10 秒的事，照旧按需手动跑、做法不变）；
本用例只读三个文件算哈希 —— 实测 `call` 阶段 **约 1 毫秒**。

纪律：`test_r71_a2_...` 是**阳性对照** ——
"改一个字节 / 删掉一个文件 / 登记表被删 → 检查器必须报出来"。
没有它，"样本完好"那句"0 处问题"就不算数（工单 §纪律）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "backend" / "tests" / "fixtures" / "grounding_sample"

# 入库样本＝这三件（与 README §"这份样本是什么" 一一对应）
EXPECTED_FILES = (
    "materials/researchgate-17551026c7.md",
    "stages/node_s-f2decfcf.u01_auto.md",
    "stages/node_s-f2decfcf.u02_auto.md",
)

# README 里登记表的行格式：64 位十六进制 + 空白 + 相对路径
_FINGERPRINT = re.compile(r"^([0-9a-f]{64})[ \t]+(\S+)$")


def _registered_text(text: str) -> dict[str, str]:
    """从 README 正文里解析出 ``{相对路径: SHA256}``（解析这半单独成函数，便于阳性对照）。"""
    out: dict[str, str] = {}
    for line in text.splitlines():
        hit = _FINGERPRINT.match(line.strip())
        if hit:
            out[hit.group(2)] = hit.group(1)
    return out


def _registered(root: Path) -> dict[str, str]:
    """README 里登记的指纹；README 不在 → 空表（调用方会把"没登记"如实报出来）。"""
    readme = root / "README.md"
    if not readme.is_file():
        return {}
    return _registered_text(readme.read_text(encoding="utf-8"))


def _diff(registered: dict[str, str], blobs: dict[str, bytes | None]) -> list[str]:
    """比对：``blobs``（rel → 内容；``None``＝文件不在）对 ``registered``（rel → 指纹）。"""
    bad: list[str] = []
    for rel in EXPECTED_FILES:
        blob = blobs.get(rel)
        if blob is None:
            bad.append(f"样本文件不在了：{rel}")
            continue
        if rel not in registered:
            bad.append(f"README 的指纹登记表里没有 {rel}（登记那几行被删/被改了？）")
            continue
        got = hashlib.sha256(blob).hexdigest()
        if got != registered[rel]:
            bad.append(f"样本文件变了：{rel}\n      登记指纹：{registered[rel]}\n      现在的指纹：{got}")
    return bad


def _problems(root: Path) -> list[str]:
    """样本现在有什么不对（空表＝三个文件都在、且与登记指纹逐字节一致）。"""
    blobs = {rel: ((root / rel).read_bytes() if (root / rel).is_file() else None)
             for rel in EXPECTED_FILES}
    return _diff(_registered(root), blobs)


# ============================================================ ① 样本完好
def test_r71_a1_sample_files_are_intact():
    """三个样本文件都在，且与 README 登记的 SHA256 逐字节一致（只读、不跑审计）。"""
    bad = _problems(SAMPLE)
    assert bad == [], (
        "入库的接地审计样本被改坏了 —— 审计就算还能跑，它审的也不再是当初那份东西：\n  "
        + "\n  ".join(bad)
    )
    # 登记表本身也得"三个都有"：别让"少了某一行"被静默放过
    assert sorted(_registered(SAMPLE)) == sorted(EXPECTED_FILES), _registered(SAMPLE)


# ============================================================ ② 阳性对照
def test_r71_a2_checker_flags_a_changed_byte_and_a_missing_file():
    """**阳性对照**：改一个字节 / 删掉一个文件 / 登记表被删 → 检查器**必须**报出来。

    全程**在内存里**做（不落盘、不用临时目录）：这样它自己也是毫秒级，
    不会为了证明"能报警"反而给每次 pytest 加几百毫秒。
    解析（`_registered_text`）与比对（`_diff`）两半都在这条里被真正测到。
    """
    good = {rel: f"合成样本（阳性对照用）：{rel}\n".encode("utf-8") for rel in EXPECTED_FILES}
    reg = {rel: hashlib.sha256(blob).hexdigest() for rel, blob in good.items()}
    readme = ("# 合成样本\n\n```\n"
              + "\n".join(f"{reg[rel]}  {rel}" for rel in EXPECTED_FILES) + "\n```\n")
    assert _registered_text(readme) == reg, "README 登记表的解析坏了"
    assert _diff(reg, good) == [], "好样本却被报出问题"

    # ① 改一个字节（两个内容节点里的第一个）
    tampered = dict(good)
    b = bytearray(good[EXPECTED_FILES[1]])
    b[0] ^= 0x01
    tampered[EXPECTED_FILES[1]] = bytes(b)
    bad = _diff(reg, tampered)
    assert bad and EXPECTED_FILES[1] in bad[0] and "变了" in bad[0], \
        f"改了一个字节却没报出来：{bad}"

    # ② 删掉一个文件（教材）
    missing = dict(good)
    missing[EXPECTED_FILES[0]] = None
    bad2 = _diff(reg, missing)
    assert bad2 and EXPECTED_FILES[0] in bad2[0] and "不在了" in bad2[0], \
        f"删了文件却没报出来：{bad2}"

    # ③ 登记表被删 → 也必须报（**不许**"没登记就当没问题"）
    bad3 = _diff({}, good)
    assert len(bad3) == len(EXPECTED_FILES), f"登记表没了却没报全：{bad3}"
    assert all("没有" in x and "登记" in x for x in bad3), bad3
