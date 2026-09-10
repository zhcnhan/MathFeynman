"""R35 可答性审计（**长期保留** · 零基础学生模型逐题判定）。

⚠️ **这是工具，不是测试**：文件名不带 `test_` 前缀，**pytest 不会收集它**；它与 `test_live_ai.py`
同属**真模型冒烟**，**不随常规 CI 运行**。手动门槛（架构侧 R35 §11 裁定）：
① **每次改生成器后**跑一次全库审计；② **发版前**跑一次。日常 CI 只跑离线结构校验。

原理（docs/09 R35 §7 / 工单 §5）：把"只读过本单元讲解原文、禁止使用任何课外知识"的学生模型
逐题去答（**选择题必须把 `options` 一并交给它**，否则会误判"没有选项"——架构侧第一版踩过这个假阳性）。
凡它答不出、或必须引用课外知识的，就是**不可答**的题。

用法（需 `.env` 的 LLM_API_KEY；默认用**临时库**、真实内容根，不动用户数据）：
    $env:MF_ALLOW_LIVE_AI=1
    .\\.venv\\Scripts\\python backend/tests/audit_answerability.py --nodes primary.s27
    # 不传 --nodes → 审全部已入库内容节点（全库体检用）

输出：stdout 明细 + 临时目录下 `mf_r35_audit_<yyyyMMdd-HHmmss>.json`（**文件名唯一、不覆盖**，F1 纪律）；
有不可答项 → 退出码 1。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SYSTEM = (
    "你是一个**完全零基础**的学生，刚刚只读过下面这一段讲解，"
    "除此之外你对这个学科一无所知（不知道任何讲解之外的事实、数字、名称、比较结果）。"
    "请严格遵守：\n"
    "1) 只允许使用【讲解原文】里明确写出的信息；\n"
    "2) 如果有任何一步需要讲解之外的常识、课外知识、或某个讲解里没写的事实，"
    "必须回答「无法回答」并说明缺什么；\n"
    "3) 不允许凭印象、不允许猜、不允许用世界知识补齐。\n"
    "只输出 JSON：{\"answerable\": true/false, \"answer\": \"...\", "
    "\"missing\": \"若不可答，指出缺哪条信息\", \"reason\": \"判断理由\"}"
)


def _ask_raw(model: str, msgs: list[dict]) -> str:
    import httpx

    base = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    key = os.getenv("LLM_API_KEY", "")
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": msgs, "temperature": 0.2,
              "response_format": {"type": "json_object"}},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def judge(lecture: str, question: str, model: str) -> dict:
    raw = _ask_raw(model, [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"【讲解原文】\n{lecture}\n\n【要回答的题目/追问】\n{question}"},
    ])
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"answerable": None, "reason": f"JSON 解析失败: {raw[:160]}"}


def _render(node_id: str, ex) -> str:
    """题面 + **选项**（选择题必须给选项，否则误判"没有选项"）。"""
    from app.content.templates import render_exercise

    rendered = render_exercise(node_id, ex, 1)
    q = rendered.prompt or ex.prompt
    if ex.options:
        q += "\n选项：\n" + "\n".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(ex.options))
    ans = getattr(rendered, "canonical_answer", None)
    return f"{q}\n（本题标准答案：{ans}）" if ans else q


def main() -> int:
    ap = argparse.ArgumentParser(description="R35 可答性审计（零基础学生模型）")
    ap.add_argument("--nodes", default="", help="逗号分隔的节点 id；缺省=全部已入库节点")
    ap.add_argument("--limit", type=int, default=0, help="最多审计多少节点（0=不限）")
    args = ap.parse_args()

    if os.getenv("MF_ALLOW_LIVE_AI") != "1":
        print("!! 本审计会真实调用大模型：请设 MF_ALLOW_LIVE_AI=1 后再运行（避免误触真模型）。")
        return 2
    sys.path.insert(0, str(REPO / "backend"))
    os.environ.setdefault("MF_CONTENT_ROOT", str(REPO / "content"))
    # 默认用临时库：审计只读内容库，不碰用户真实进度
    os.environ.setdefault("MF_DB_PATH", os.path.join(tempfile.gettempdir(), "mf_r35_audit.db"))
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env", override=False)
    if not os.getenv("LLM_API_KEY"):
        print("!! 无 LLM_API_KEY，无法跑真模型审计")
        return 2

    from app.content.loader import load_library
    from app.db import SessionLocal, init_db
    from app.service.library import refresh_library, sync_content

    init_db()
    refresh_library()
    with SessionLocal() as db:
        sync_content(db)
        db.commit()
    lib = load_library()
    wanted = [n.strip() for n in args.nodes.split(",") if n.strip()] or list(lib.by_id)
    if args.limit:
        wanted = wanted[: args.limit]
    model = os.getenv("LLM_MODEL_LIGHT", "deepseek-chat")

    findings: list[dict] = []
    for node_id in wanted:
        loaded = lib.by_id.get(node_id)
        if loaded is None:
            print(f"== {node_id}: 内容库缺失，跳过")
            continue
        doc = loaded.doc
        lecture = doc.explanation.body or doc.body_md or ""
        print("=" * 78)
        print(f"单元 {node_id} · {doc.title}")
        print(f"  讲解 {len(lecture)} 字 · 练习 {len(doc.exercises)} · 例题 {len(doc.worked_examples)} · "
              f"taught_facts {len(doc.taught_facts)} · socratic {len(doc.feynman.socratic_followups)}")

        items: list[tuple[str, str, str]] = []          # (kind, id, question)
        for ex in doc.exercises:
            items.append(("exercise", ex.id, _render(node_id, ex)))
        for i, ask in enumerate(doc.feynman.socratic_followups or []):
            items.append(("socratic", str(i + 1), ask))
        if doc.feynman.task_prompt:
            items.append(("feynman_task", "-", doc.feynman.task_prompt))
        for ex in doc.worked_examples:
            items.append(("worked_example", "-", ex.prompt))

        for kind, ident, q in items:
            verdict = judge(lecture, q, model)
            ok = verdict.get("answerable")
            flag = "✅ 可答" if ok is True else ("❌ 不可答" if ok is False else "⚠️ 无法判定")
            print(f"  [{flag}] {kind}[{ident}]：{q[:100].replace(chr(10), ' / ')}")
            if ok is False:
                print(f"        缺什么：{verdict.get('missing')}")
                print(f"        理由：{str(verdict.get('reason'))[:180]}")
            findings.append({"node": node_id, "kind": kind, "id": ident, "q": q,
                             "answerable": ok, "missing": verdict.get("missing"),
                             "reason": verdict.get("reason")})

    total = len(findings)
    bad = [f for f in findings if f["answerable"] is False]
    unknown = [f for f in findings if f["answerable"] is None]
    print("=" * 78)
    print(f"总计 {total} 项受检；❌ 不可答 {len(bad)}；✅ 可答 {total - len(bad) - len(unknown)}；"
          f"⚠️ 无法判定 {len(unknown)}")
    for f in bad:
        print(f"  ❌ {f['node']} / {f['kind']}[{f['id']}]：{str(f['q'])[:80]}")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(tempfile.gettempdir()) / f"mf_r35_audit_{stamp}.json"
    out.write_text(json.dumps({"generated_at": stamp, "model": model, "findings": findings},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细已写入（唯一文件名，不覆盖）:", out)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
