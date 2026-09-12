"""service.page_import：**图示教材模式导入的后台任务**（R67 任务 A）。

为什么要它（工单 §0 实测）：整本 126 页逐页读要 ~17 分钟，而导入接口是**同步**的——
一个请求里做完 126 次调用才返回，于是前端**全程拿不到任何进度**；用户中途停掉程序，
连一条材料都没落库（读了几十页、花了几十页的钱，全丢）。

本模块的口径（与既有后台任务同款：`service.selfextend` / `service.feedback`）：

1. **点击后立刻返回**（`start` 只做校验 + 起线程，不做任何模型调用）；
2. **进度可查**（`get`：已读 N / 共 M 页、当前在读第几页、失败几页、已存下来的材料 id）；
3. **可取消**（`cancel` 立一个旗子；引擎**不再往下读**，**已读的页照样留在材料里**）；
4. **分段落盘**在 `outline.mode_pages` 的灌入口径里（每读若干页/若干秒写一次）——
   所以**进程被杀**之后重启，已读部分仍在（`*.pages.json` 里的 `progress` 块说清读到哪、
   还剩哪些页）；
5. **一页都没读成 → 不建材料**（绝不留"空材料"）；
6. 任务表**只在内存**（重启即空）：重启后查旧任务给**中文说明 + 出路**（材料里能看进度），
   不假装任务还在跑（也从不当成"失败"）。
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

# 已结束的任务在内存里留几条（供前端把"刚读完"这一次的进度取完）
_KEEP_FINISHED = 20
_JOBS: dict[str, dict] = {}
_ORDER: list[str] = []
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start(subject_id: str, *, title: str, files: list[tuple[str, bytes]], provider,
          want: str = "", pdf_pages: str = "", max_pages=None, strategy: str = "",
          concurrency: int = 1, batch_pages: int = 1, source: str = "页面图片导入",
          checkpoint_every_pages: int = 5, checkpoint_every_seconds: float = 30.0) -> dict:
    """起一次后台导入 → **立刻**回 ``{job_id, status, …}``（校验与模型调用都在后台/之前）。

    ``provider`` 由调用方（API 层）**在请求线程里**建好——这样测试替换的"假模型"一定生效，
    不会出现"后台线程拿到真模型去打真接口"这种危险情况。
    """
    running = active_for(subject_id)
    if running:
        raise RuntimeError(
            f"这个学科已经有一次导入在进行（已读 {running['done']} / {running['total']} 页）——"
            "等它读完，或先点「停止这次导入」再开始新的")
    job_id = "imp-" + uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "subject_id": subject_id, "title": title or "页面图片教材",
        "status": "running", "total": 0, "done": 0, "failed": 0, "current": "",
        "material_id": "", "note_zh": "已开始：正在准备页面…", "strategy": strategy,
        "sampled": False, "planned": [], "pending": [], "read_labels": [],
        "unreadable": [], "started_at": _now(), "updated_at": _now(),
        "finished_at": "", "cancel_requested": False, "error_zh": "",
        "checkpoint_every_pages": int(checkpoint_every_pages or 5),
        "checkpoint_every_seconds": float(checkpoint_every_seconds or 30.0),
    }
    with _LOCK:
        _JOBS[job_id] = job
        _ORDER.append(job_id)
        _trim_locked()
    stop = threading.Event()
    job["_stop"] = stop
    args = {"title": title, "files": files, "want": want, "pdf_pages": pdf_pages,
            "max_pages": max_pages, "strategy": strategy, "concurrency": concurrency,
            "batch_pages": batch_pages, "source": source}
    threading.Thread(target=_worker, args=(job_id, subject_id, args, provider, stop),
                     daemon=True).start()
    return view(job_id)


def _trim_locked() -> None:
    """内存里最多留 `_KEEP_FINISHED` 条已结束的任务（运行中的一条都不删）。"""
    finished = [j for j in _ORDER if _JOBS.get(j, {}).get("status") != "running"]
    for jid in finished[: max(0, len(finished) - _KEEP_FINISHED)]:
        _JOBS.pop(jid, None)
        try:
            _ORDER.remove(jid)
        except ValueError:
            pass


def _worker(job_id: str, subject_id: str, args: dict, provider, stop: threading.Event) -> None:
    """后台线程：独立 DB 会话跑同一条导入路径（`outline.mode_pages.import_pages`）。"""
    from ..db import SessionLocal

    job = _JOBS.get(job_id)
    if job is None:                      # pragma: no cover - 极端竞态
        return

    def on_event(ev: dict) -> None:
        _on_event(job_id, ev)

    try:
        with SessionLocal() as db:
            from ..outline import mode_pages

            out = mode_pages.import_pages(
                db, subject_id, provider=provider, on_event=on_event,
                should_stop=stop.is_set, source=str(args.get("source") or "页面图片导入"),
                title=str(args.get("title") or ""), files=args.get("files") or [],
                want=str(args.get("want") or ""), pdf_pages=str(args.get("pdf_pages") or ""),
                max_pages=args.get("max_pages"), strategy=str(args.get("strategy") or ""),
                concurrency=int(args.get("concurrency") or 1),
                batch_pages=int(args.get("batch_pages") or 1),
                checkpoint={"every_pages": int(job.get("checkpoint_every_pages") or 5),
                            "every_seconds": float(job.get("checkpoint_every_seconds") or 30.0),
                            "state": "importing"})
            db.commit()
        _finish(job_id, out, cancelled=bool(stop.is_set()))
    except Exception as e:                # 后台失败**不许静默**：状态里给中文原因
        _fail(job_id, e)


def _on_event(job_id: str, ev: dict) -> None:
    kind = str(ev.get("kind") or "")
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        if kind == "start":
            job["total"] = int(ev.get("total") or 0)
            job["planned"] = [str(x) for x in (ev.get("labels") or [])]
            job["pending"] = list(job["planned"])
            job["strategy"] = str(ev.get("strategy") or job.get("strategy") or "")
            job["note_zh"] = (f"已开始：共 {job['total']} 页，正在读第 1 页…"
                              if job["total"] else "已开始")
        elif kind == "render":
            job["note_zh"] = str(ev.get("note_zh") or "正在把 PDF 逐页转成图片…")
        elif kind == "page":
            job["done"] = int(ev.get("done") or job["done"])
            job["current"] = str(ev.get("label") or "")
            if job["done"] and job["done"] <= 1:
                job["note_zh"] = (f"正在读：已读 {job['done']} / 共 {job['total']} 页")
            else:
                job["note_zh"] = f"正在读：已读 {job['done']} / 共 {job['total']} 页"
        elif kind == "checkpoint":
            if ev.get("material_id"):
                job["material_id"] = str(ev["material_id"])
            if ev.get("saved") is False:
                job["note_zh"] = "刚读到的页这次没存下来（下次会再试）——读取还在继续"
        job["updated_at"] = _now()


def _finish(job_id: str, out: dict, *, cancelled: bool) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["material_id"] = str(out.get("id") or job.get("material_id") or "")
        job["done"] = int(out.get("read_pages") or job.get("done") or 0)
        job["failed"] = len(out.get("unreadable") or [])
        job["unreadable"] = [str(x) for x in (out.get("unreadable") or [])]
        job["pending"] = [str(x) for x in (out.get("pending_pages") or [])]
        job["sampled"] = bool(out.get("sampled"))
        job["title"] = str(out.get("title") or job.get("title") or "")
        job["status"] = "cancelled" if cancelled else "done"
        job["current"] = ""
        job["note_zh"] = (("已停止：读到的页都存下来了" if job["material_id"]
                           else "已停止：一页都没读完，所以没有存下材料")
                          if cancelled else str(out.get("note_zh") or "读完了"))
        job["finished_at"] = _now()
        job["updated_at"] = job["finished_at"]


def _fail(job_id: str, e: Exception) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "failed"
        job["error_zh"] = f"{type(e).__name__}：{str(e)[:200]}"
        job["note_zh"] = ("这次导入没能继续：" + str(e)[:160]
                          + ("；已经读到的页都还在材料里" if job.get("material_id") else ""))
        job["finished_at"] = _now()
        job["updated_at"] = job["finished_at"]
    try:
        from . import ledger

        ledger.note(ledger.CAT_MATERIAL, "导入（图片为主的教材）",
                    f"这次导入没能继续：{str(e)[:160]}"
                    + ("；已经读到的页都还在材料里" if _JOBS.get(job_id, {}).get("material_id") else ""),
                    impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_RETRY,
                    subject_id=str(_JOBS.get(job_id, {}).get("subject_id") or ""),
                    detail={"kind": "pages_import_failed", "job_id": job_id})
    except Exception:
        pass


def view(job_id: str) -> dict:
    """对外形状（**不含**线程对象）；查不到 → 空 dict（调用方给中文说明）。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return {}
        return {k: v for k, v in job.items() if not k.startswith("_")}


def get(job_id: str) -> dict:
    return view(job_id)


def cancel(job_id: str) -> dict:
    """请求停止（**不硬杀线程**）：已读的页会在收尾时写进材料。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return {}
        if job["status"] == "running":
            job["cancel_requested"] = True
            ev = job.get("_stop")
            if ev is not None:
                ev.set()
            job["note_zh"] = "收到停止请求：读完手上这一页就停，已读的页会存下来"
            job["updated_at"] = _now()
        return {k: v for k, v in job.items() if not k.startswith("_")}


def active_for(subject_id: str) -> dict:
    """该学科正在跑的导入任务（没有 → ``{}``）。"""
    with _LOCK:
        for jid in _ORDER:
            job = _JOBS.get(jid)
            if job and job["status"] == "running" and job["subject_id"] == subject_id:
                return {k: v for k, v in job.items() if not k.startswith("_")}
    return {}


def list_for(subject_id: str, *, limit: int = 10) -> list[dict]:
    """该学科最近的导入任务（新的在前；含刚读完的那一条，方便界面把结果说完）。"""
    out: list[dict] = []
    with _LOCK:
        for jid in reversed(_ORDER):
            job = _JOBS.get(jid)
            if job and job["subject_id"] == subject_id:
                out.append({k: v for k, v in job.items() if not k.startswith("_")})
            if len(out) >= max(1, int(limit)):
                break
    return out


def reset_for_tests() -> None:
    """清空任务表（**只给测试用**：任务表本来就是"进程内、重启即空"的）。"""
    with _LOCK:
        _JOBS.clear()
        _ORDER.clear()


__all__ = ["active_for", "cancel", "get", "list_for", "reset_for_tests", "start", "view"]
