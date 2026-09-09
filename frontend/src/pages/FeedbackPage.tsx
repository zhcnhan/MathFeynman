// 内容反馈（纠错记录）查看页：列出 pending/regenerating/regenerated/failed/reviewed 状态与结果。
import { useEffect, useState } from "react";
import { api } from "../api";

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
      <h1>内容反馈（纠错记录）</h1>
      <div className="dim">
        说明：auto 内容（AI 生成）纠错会自动重生成替换；人工精写内容只记录待人工修订。
        {items.length === 0 && " 当前没有记录。"}
      </div>
      {err && <div className="banner error">{err}</div>}
      <div className="card">
        <button className="btn" onClick={() => void load()}>刷新</button>
        <div className="dim" style={{ margin: "6px 0" }}>
          auto 内容在待复核/失败状态可直接点「重试处理」：会按节点自动重生成替换并清零反馈；失败会写明原因，不再无限待复核。
        </div>
        {items.map((f) => {
          const retryable = f.status === "pending" || f.status === "failed";
          const retry = async () => {
            setErr("");
            try {
              await api.post(`/feedback/${f.id}/regen`, undefined);
              await load();
            } catch (e) {
              setErr(String(e));
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
                  <button className="btn" onClick={() => void retry()}>重试处理</button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
