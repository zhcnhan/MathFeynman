// R38 材料注入预算滑块（学科管理卡 → 材料区，**每学科独立**）
// 必显：① 两档当前值 + 来源（"你设定的"/"默认"）；② 上一轮实际注入总量与批次数；
//       ③ 滑块 A 调小的语义说明（"只是分更多批，不会少学章节"）。
import { useEffect, useState } from "react";
import { api } from "../api";

export type BudgetSource = "request" | "subject" | "env" | "builtin";

export type BudgetValue = {
  value: number;
  source: BudgetSource;
  source_zh: string;
  set: number | null;
};

export type PerMaterialUsage = {
  material_id: string;
  title: string;
  role: string;
  role_explicit: boolean;
  role_zh: string;
  chars_total: number;
  entries_total: number;
  batches: number[];
  injected: boolean;
  blocked_reason: string;
};

export type BudgetView = {
  subject_id: string;
  batch_chars: BudgetValue;
  inject_max_chars: BudgetValue;
  per_call_chars: number;
  tiers: { batch: { label: string; value: number }[]; inject: { label: string; value: number }[] };
  last_usage: {
    used_chars: number;
    batch_count: number;
    per_material: PerMaterialUsage[];
    truncated: boolean;
    dropped: string[];
    order_basis: string;
    summary_zh: string;
    note_zh: string;
  };
  context_valve: { applied: boolean; context_tokens: number; limit_chars: number };
  materials: { id: string; title: string; role: string; role_zh: string; healthy: boolean; chars: number; entries: number; note: string }[];
  not_injected: { material: string; label: string; chars: number; note: string }[];
};

/** 数值 → 中文档位文案（0 = 不限）。 */
export function budgetText(v: number): string {
  return v === 0 ? "不限" : `${v.toLocaleString("zh-CN")} 字符`;
}

export default function MaterialBudgetPanel({
  subjectId,
  onChanged,
}: {
  subjectId: string;
  onChanged?: () => void;
}) {
  const [bv, setBv] = useState<BudgetView | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    try {
      setBv(await api.get<BudgetView>(`/subjects/${subjectId}/budget`));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subjectId]);

  const save = async (patch: { batch_chars?: number; inject_max_chars?: number }) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const next = await api.put<BudgetView>(`/subjects/${subjectId}/budget`, patch);
      setBv(next);
      setMsg("已保存（下一次起草/生成**立即生效**）");
      onChanged?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!bv) {
    return (
      <div style={{ marginTop: 8 }}>
        {err && <div className="banner error">{err}</div>}
        <div className="dim">正在读取材料注入预算…</div>
      </div>
    );
  }

  const tierRow = (
    label: string,
    tiers: { label: string; value: number }[],
    cur: BudgetValue,
    apply: (v: number) => void
  ) => (
    <div className="input-row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center" }}>
      <span className="dim" style={{ minWidth: 132 }}>{label}</span>
      {tiers.map((t) => (
        <button
          key={`${label}-${t.value}`}
          className={cur.value === t.value ? "depth active" : "depth"}
          disabled={busy}
          onClick={() => apply(t.value)}
          title={`${t.label}：${budgetText(t.value)}`}
        >
          {t.label}
        </button>
      ))}
      <span className={`badge ${cur.source === "subject" ? "pass" : ""}`}>
        当前：{budgetText(cur.value)}（{cur.source_zh}）
      </span>
    </div>
  );

  return (
    <div
      style={{ marginTop: 10, padding: 10, borderRadius: 10, background: "#f7fafd", border: "1px solid #dbe6f0" }}
    >
      <h3 style={{ margin: "0 0 4px" }}>材料注入预算（本学科独立 · R38）</h3>
      <div className="dim" style={{ fontSize: 12, marginBottom: 6 }}>
        两个滑块都按**整本书**的真实量级设计；**0 = 不限**。优先级：单次请求参数 &gt; 本学科滑块 &gt;
        .env 配置 &gt; 内置默认。
      </div>
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner ok">{msg}</div>}

      {tierRow("单次调用预算（每次喂多少）", bv.tiers.batch, bv.batch_chars, (v) =>
        void save({ batch_chars: v })
      )}
      <div className="dim" style={{ fontSize: 12, margin: "2px 0 8px" }}>
        ← 这才是"字符太少"的主控。**调小只会分成更多批，不会少学章节**（覆盖账不变）。
      </div>

      {tierRow("总注入上限（花费天花板）", bv.tiers.inject, bv.inject_max_chars, (v) =>
        void save({ inject_max_chars: v })
      )}
      <div className="dim" style={{ fontSize: 12, margin: "2px 0 8px" }}>
        ← 默认**不限**；给"想设花费天花板"的用户用。为不丢任何章节，系统不会为满足上限而静默削减，
        实际用量会如实列出（见下方"上一轮实际注入"）。
      </div>

      <details open style={{ marginTop: 4 }}>
        <summary>
          上一轮实际注入：{bv.last_usage.summary_zh}
        </summary>
        <div className="dim" style={{ fontSize: 12, margin: "4px 0" }}>
          合计 <strong>{bv.last_usage.used_chars.toLocaleString("zh-CN")}</strong> 字 ·
          分 <strong>{bv.last_usage.batch_count}</strong> 批 ·
          截断 <strong>{bv.last_usage.truncated ? "有" : "无"}</strong> ·
          丢弃 <strong>{bv.last_usage.dropped.length}</strong> 条 ·<br />
          顺序依据：{bv.last_usage.order_basis}
          {bv.context_valve.applied && (
            <>
              <br />
              安全阀已生效：本书较大，按模型上下文硬上限（≈{bv.context_valve.context_tokens.toLocaleString("zh-CN")}{" "}
              token）自动分批，单次最多约 {bv.context_valve.limit_chars.toLocaleString("zh-CN")} 字——不截断、不漏章节。
            </>
          )}
        </div>
        {bv.last_usage.per_material.length > 0 && (
          <table style={{ width: "100%", fontSize: 12 }}>
            <thead>
              <tr className="dim">
                <th style={{ textAlign: "left" }}>材料</th>
                <th>角色</th>
                <th>全文字数</th>
                <th>章/节条目</th>
                <th>所在批次</th>
                <th>是否注入</th>
              </tr>
            </thead>
            <tbody>
              {bv.last_usage.per_material.map((m) => (
                <tr key={m.material_id}>
                  <td style={{ textAlign: "left" }}>{m.title}</td>
                  <td>{m.role_zh}{m.role_explicit ? "" : "（未标注）"}</td>
                  <td>{m.chars_total.toLocaleString("zh-CN")}</td>
                  <td>{m.entries_total}</td>
                  <td>{m.batches.length ? m.batches.join("、") : "—"}</td>
                  <td>{m.injected ? "是" : `否（${m.blocked_reason}）`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {bv.not_injected.length > 0 && (
          <div className="banner warn" style={{ marginTop: 6 }}>
            未纳入注入的章节（{bv.not_injected.length}）：{" "}
            {bv.not_injected.map((x) => `${x.material}·${x.label}`).join("、")}
          </div>
        )}
        {!bv.materials.length && <div className="dim">（本学科暂无引用材料）</div>}
      </details>
    </div>
  );
}
