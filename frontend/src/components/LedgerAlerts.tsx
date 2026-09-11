// R39 §1「一切显性」铁则 · **就地提示**组件
// 用途：材料页/大纲页/单元页就地显示"本次丢弃/降级/失败/跳过"了哪些东西、中文原因、
// 影响面与可否补救；并提供"看全部账目"（总账页）入口。
// 铁则：**不许**只在 prompt 尾部提一句、**不许**只在日志里——界面必须能看见。
import { Link } from "react-router-dom";

export type LedgerEntry = {
  id?: number | null;
  at?: string;
  category: string;
  category_label: string;
  subject_id?: string;
  object: string;
  reason: string;
  impact?: string;
  remedy?: string;
  unit_id?: string;
  detail?: Record<string, unknown>;
};

const CAT_COLOR: Record<string, string> = {
  material: "#e6a23c",
  generation: "#b3261e",
  model_call: "#7b1fa2",
  coverage: "#0277bd",
  other: "#546e7a",
};

export default function LedgerAlerts({
  entries,
  title = "本次的记录",
  subjectId,
  compact = false,
}: {
  entries?: LedgerEntry[] | null;
  title?: string;
  subjectId?: string;
  compact?: boolean;
}) {
  if (!entries || entries.length === 0) {
    return (
      <div className="dim" style={{ fontSize: 12 }}>
        ✓ 本次一切正常：没有用不上的内容，也没有出错的步骤
        {subjectId && (
          <>
            {" · "}
            <Link to={`/ledger?subject_id=${subjectId}`}>查看记录</Link>
          </>
        )}
      </div>
    );
  }
  return (
    <div
      style={{
        marginTop: 8,
        padding: compact ? 8 : 10,
        borderRadius: 10,
        border: "1px solid #f0d7a8",
        background: "#fffaf0",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <strong>
          {title} · {entries.length} 条
        </strong>
        {subjectId && (
          <Link to={`/ledger?subject_id=${subjectId}`} style={{ fontSize: 12 }}>
            查看全部 →
          </Link>
        )}
      </div>
      {entries.map((e, i) => (
        <div key={`${e.category}-${i}`} style={{ marginTop: 6, fontSize: 13 }}>
          <span
            className="badge"
            style={{ background: CAT_COLOR[e.category] ?? "#546e7a", color: "#fff", border: "none" }}
          >
            {e.category_label}
          </span>{" "}
          <strong>{e.object}</strong>
          <div style={{ marginTop: 2 }}>{e.reason}</div>
          {(e.impact || e.remedy) && (
            <div className="dim" style={{ fontSize: 12 }}>
              影响：{e.impact || "—"} · 能不能补救：{e.remedy || "—"}
              {e.unit_id ? ` · 单元：${e.unit_id}` : ""}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
