// 内容反馈（纠错记录）查看页：列出 pending/regenerating/regenerated/failed/reviewed 状态与结果。
import { useEffect, useState } from "react";
import { api } from "../api";
import { PageHead } from "../components/ui";

interface FeedbackRow {
  id: number;
  node_id: string;
  kind: string;
  message: string;
  status: string;
  result?: string;
  created_at?: string;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "⏳ 待复核",
  regenerating: "♻️ 重生成中",
  regenerated: "✅ 已重生成替换",
  reviewed: "👀 已人工复核",
  failed: "❌ 失败（保留原内容）",
};
const KIND_LABEL: Record<string, string> = {
  lecture: "讲解",
  exercise: "练习",
  content: "内容",
};

export default function FeedbackPage() {
  const [items, setItems] = useState<FeedbackRow[]>([]);
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null); // 正在"重试处理"的行
  const load = () =>
    api
      .get<{ items: FeedbackRow[] }>("/feedback")
      .then((r) => setItems(r.items || []))
      .catch((e) => setErr(String(e)));
  useEffect(() => {
    void load();
  }, []);

  return (
    <div>
      <PageHead
        title="内容反馈（纠错记录）"
        sub="报错后：AI 生成的内容会自动重做替换；人工精写的内容只记下来等你修改。"
      />
      {items.length === 0 && <p className="empty">当前没有记录。</p>}
      {err && <div className="banner error">{err}</div>}
      <div className="card">
        <button className="btn" onClick={() => void load()}>刷新</button>
        <div className="dim" style={{ margin: "6px 0" }}>
          「待复核」或「失败」的可以直接点「重试处理」：系统会重新生成并替换；失败会写明原因。
        </div>
        {items.map((f) => {
          const retryable = f.status === "pending" || f.status === "failed";
          const busy = busyId === f.id;
          const retry = async () => {
            if (busy) return;
            setErr("");
            setBusyId(f.id); // 立即给出"处理中"反馈，避免按钮无反应感
            try {
              await api.post(`/feedback/${f.id}/regen`, undefined);
              await load();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusyId(null);
            }
          };
          return (
            <div key={f.id} className="item" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <div style={{ width: 120 }} className="dim">{f.node_id}</div>
              <div style={{ width: 60 }}>
                <span className="badge">{KIND_LABEL[f.kind] ?? f.kind}</span>
              </div>
              <div style={{ flex: 1 }}>
                <div>{f.message}</div>
                {f.result && <div className="dim">{f.result}</div>}
              </div>
              <div style={{ width: 130 }}>
                <span className={`badge ${f.status === "regenerated" ? "ok" : f.status === "failed" ? "bad" : ""}`}>
                  {STATUS_LABEL[f.status] ?? f.status}
                </span>
              </div>
              <div style={{ width: 90 }}>
                {retryable && (
                  <button className="btn" disabled={busy} onClick={() => void retry()}>
                    {busy ? "♻️ 处理中…" : "重试处理"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
