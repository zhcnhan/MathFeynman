// 复习页（docs/07 §2.4 Review）：队列逐卡复习 → 判题 → rating 四键。
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, DueReviewItem, ExerciseView } from "../api";
import ExercisePanel, { Feedback } from "../components/ExercisePanel";

const RATINGS = [
  { v: 1, label: "忘记", cls: "again" },
  { v: 2, label: "困难", cls: "hard" },
  { v: 3, label: "良好", cls: "good" },
  { v: 4, label: "轻松", cls: "easy" },
];

export default function ReviewPage() {
  const [queue, setQueue] = useState<{ due: DueReviewItem[]; total_due: number; stacked_count: number } | null>(null);
  const [current, setCurrent] = useState<DueReviewItem | null>(null);
  const [exercise, setExercise] = useState<ExerciseView | null>(null);
  const [fb, setFb] = useState<Feedback | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const nav = useNavigate();

  const loadQueue = useCallback(async () => {
    const q = await api.get<{ due: DueReviewItem[]; total_due: number; stacked_count: number }>("/review/queue");
    setQueue(q);
    if (q.due.length === 0) {
      setCurrent(null);
      setExercise(null);
    }
  }, []);

  useEffect(() => {
    void loadQueue().catch((e) => setMsg((e as Error).message));
  }, [loadQueue]);

  const begin = async (item: DueReviewItem) => {
    setBusy(true);
    setMsg(null);
    setFb(null);
    try {
      setCurrent(item);
      const r = await api.post<{ node_id: string; exercise: ExerciseView }>("/exercises/next", { node_id: item.node_id, exclude_ids: [] });
      setExercise(r.exercise);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const answer = async (text: string) => {
    if (!current || !exercise) return;
    setBusy(true);
    setFb(null);
    try {
      const r = await api.post<{ correct: boolean; verdict: string; hint?: string | null; message?: string }>("/exercises/check", {
        node_id: current.node_id,
        exercise_id: exercise.exercise_id,
        params_seed: exercise.seed,
        user_answer: text,
      });
      setFb(
        r.verdict === "correct"
          ? { verdict: "correct", hint: "答对了！请凭真实记忆自评。" }
          : r.verdict === "notation"
            ? { verdict: "notation", message: r.message, hint: null }
            : { verdict: "wrong", hint: r.hint ?? null }
      );
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitRating = async (rating: number) => {
    if (!current) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.post<{ action: string; reason?: string; next_due_at?: string | null; interval_days?: number }>("/review/submit", {
        node_id: current.node_id,
        rating,
      });
      if (r.action === "relearn") {
        setLastResult(`节点已降级回炉重学：${r.reason ?? ""}`);
      } else {
        setLastResult(`已排程：下次复习约 ${Math.round(r.interval_days ?? 0)} 天后（${r.next_due_at ?? "-"}）`);
      }
      setCurrent(null);
      setExercise(null);
      setFb(null);
      await loadQueue();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="review-page">
      <h1>复习</h1>
      {msg && <div className="banner error">{msg}</div>}
      {lastResult && <div className="banner ok">{lastResult}</div>}
      {!current && (
        <div className="card">
          {!queue ? <p>加载复习队列…</p> : queue.due.length === 0 ? <p className="empty">今日无到期复习 🎉 去学新知识吧。</p> : (
            <ul className="queue-list">
              {queue.due.map((q) => (
                <li key={q.node_id} className={q.stacked ? "stacked" : ""}>
                  <div>
                    <strong>{q.title}</strong> {q.stacked && <span className="badge danger">堆积警示（逾期&gt;3天）</span>}
                    <div className="dim">到期 {q.due_at ? new Date(q.due_at).toLocaleString("zh-CN") : "-"} · 已遗忘 {q.lapse_count} 次</div>
                  </div>
                  <button className="primary" onClick={() => void begin(q)}>开始复习</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {current && exercise && (
        <div>
          <div className="card">
            <h2>复习 · {queue?.due.find((d) => d.node_id === current.node_id)?.title ?? current.node_id}</h2>
            <ExercisePanel exercise={exercise} disabled={busy} feedback={fb} onSubmit={(t) => void answer(t)} />
          </div>
          {fb?.verdict === "correct" && (
            <div className="card rating-card">
              <h2>这次复习，你感觉怎么样？</h2>
              <div className="rating-row">
                {RATINGS.map((r) => (
                  <button key={r.v} className={`rating ${r.cls}`} disabled={busy} onClick={() => void submitRating(r.v)}>
                    {r.label}
                  </button>
                ))}
              </div>
              <p className="dim">忘记/困难 累计 2 次会把节点打回「学习中」重新掌握。</p>
            </div>
          )}
          {fb?.verdict === "wrong" && <button className="ghost" disabled={busy} onClick={() => setExercise(null)}>换一题</button>}
        </div>
      )}
      {queue && queue.due.length === 0 && !current && (
        <button className="ghost" onClick={() => nav("/")}>回仪表盘</button>
      )}
    </div>
  );
}
