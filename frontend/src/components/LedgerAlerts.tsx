// R39 §1「一切显性」铁则 · **就地提示**组件
// 用途：材料页/大纲页/单元页就地显示"本次丢弃/降级/失败/跳过"了哪些东西、中文原因、
// 影响面与可否补救；并提供"看全部账目"（总账页）入口。
// 铁则：**不许**只在 prompt 尾部提一句、**不许**只在日志里——界面必须能看见。
import { Link } from "react-router-dom";

/** R54 B：账目上的"出路"（后端只读派生：remedy=可补救 且知道学科/单元 → 一键重新生成该单元） */
export type LedgerAction = {
  kind: "regenerate_unit" | string;
  label_zh: string;
  subject_id?: string;
  unit_id?: string;
};

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
  /** R54 B：可操作出路（丢弃 → 一键重新生成该单元） */
  action?: LedgerAction | null;
  /** R54 B：该单元后来已重新生成 → 这条旧记录已作废（界面不该再当作当前问题） */
  resolved?: boolean;
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
  onAction,
}: {
  entries?: LedgerEntry[] | null;
  title?: string;
  subjectId?: string;
  compact?: boolean;
  /** R54 B：点"重新生成这个单元"时回调（页面负责真正去生成） */
  onAction?: (action: LedgerAction) => void;
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
        <div key={`${e.category}-${i}`} style={{ marginTop: 6, fontSize: 13, opacity: e.resolved ? 0.55 : 1 }}>
          <span
            className="badge"
            style={{ background: CAT_COLOR[e.category] ?? "#546e7a", color: "#fff", border: "none" }}
          >
            {e.category_label}
          </span>{" "}
          <strong>{e.object}</strong>
          {/* R54 B：该单元后来已重新生成 → 旧记录标"已解决"，别让用户以为问题还在 */}
          {e.resolved && <span className="badge pass" style={{ marginLeft: 6 }}>已解决</span>}
          <div style={{ marginTop: 2 }}>{e.reason}</div>
          {(e.impact || e.remedy) && (
            <div className="dim" style={{ fontSize: 12 }}>
              影响：{e.impact || "—"} · 能不能补救：{e.remedy || "—"}
              {e.unit_id ? ` · 单元：${e.unit_id}` : ""}
            </div>
          )}
          {/* R54 B：**丢弃必须有出路**——就地给可点的"重新生成这个单元"（不再只写"可通过重试补救"） */}
          {!e.resolved && e.action && onAction && (
            <button
              className="ghost"
              style={{ marginTop: 4, padding: "3px 10px", fontSize: 12 }}
              onClick={() => onAction(e.action as LedgerAction)}
            >
              {e.action.label_zh || "重新生成这个单元"}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
