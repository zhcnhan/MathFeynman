// R38/R42 材料注入预算滑块（学科管理卡 → 材料区，**每学科独立**）
// **R42 A1：两个滑块的承诺不同，各自写清**（不许一句话糊两个滑块）——
//   滑块 A「单次调用预算」：调小 → 只是分更多批，**一个章节都不会少学**；
//   滑块 B「总注入上限」：**是真上限** → 超了真的不再注入，但**每一处没进去的都明确列出 + 中文原因**。
// 必显：① 两档当前值 + 来源（"你设定的"/"默认"）；② 上一轮实际注入总量与批次数；
//       ③ 因总上限未注入的章节数 + 可展开清单（就地）。
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
  /** R42：因「总注入上限」被跳过的章/节（逐材料） */
  cap_skipped?: string[];
  cap_skipped_count?: number;
};

export type CapSkipGroup = {
  material_id: string;
  title: string;
  items: { label: string; chars: number; reason_zh: string }[];
};

export type InjectCap = {
  configured: boolean;
  cap: number;
  used_chars: number;
  remaining: number;
  skipped_count: number;
  skipped_chars: number;
  skipped_labels: string[];
  skipped_by_material?: CapSkipGroup[];
  first_batch_over_cap: boolean;
};

export type NotInjected = {
  material: string;
  material_id?: string;
  label: string;
  chars: number;
  note: string;
  reason?: string;
  reason_zh?: string;
};

export type BudgetView = {
  subject_id: string;
  batch_chars: BudgetValue;
  inject_max_chars: BudgetValue;
  per_call_chars: number;
  tiers: { batch: { label: string; value: number }[]; inject: { label: string; value: number }[] };
  /** R42 A1：两个滑块各自的承诺（后端直出中文，界面原样渲染） */
  promises_zh?: { batch_chars: string; inject_max_chars: string };
  last_usage: {
    used_chars: number;
    batch_count: number;
    per_material: PerMaterialUsage[];
    truncated: boolean;
    dropped: string[];
    order_basis: string;
    summary_zh: string;
    note_zh: string;
    cap_skipped_count?: number;
    cap_skipped_labels?: string[];
    cap_skipped_by_material?: CapSkipGroup[];
    cap_note_zh?: string;
  };
  inject_cap?: InjectCap;
  context_valve: { applied: boolean; context_tokens: number; limit_chars: number };
  materials: { id: string; title: string; role: string; role_zh: string; healthy: boolean; chars: number; entries: number; note: string }[];
  not_injected: NotInjected[];
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
      <h3 style={{ margin: "0 0 4px" }}>材料注入预算（本学科独立 · R38/R42）</h3>
      <div className="dim" style={{ fontSize: 12, marginBottom: 6 }}>
        两个滑块都按**整本书**的真实量级设计；**0 = 不限**。优先级：单次请求参数 &gt; 本学科滑块 &gt;
        .env 配置 &gt; 内置默认。<br />
        ⚠️ **两个滑块的承诺不一样**（R42）：下面的说明请分别看。
      </div>
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner ok">{msg}</div>}

      {tierRow("① 单次调用预算（每次喂多少）", bv.tiers.batch, bv.batch_chars, (v) =>
        void save({ batch_chars: v })
      )}
      <div className="dim" style={{ fontSize: 12, margin: "2px 0 8px" }}>
        ← 这才是"字符太少"的主控。承诺：
        <strong>{bv.promises_zh?.batch_chars ?? "调小只是分更多批，不会少学章节"}</strong>
      </div>

      {tierRow("② 总注入上限（总共最多喂多少）", bv.tiers.inject, bv.inject_max_chars, (v) =>
        void save({ inject_max_chars: v })
      )}
      <div className="dim" style={{ fontSize: 12, margin: "2px 0 8px" }}>
        ← 默认**不限**。承诺：
        <strong>{bv.promises_zh?.inject_max_chars ?? "超了就真的不再注入，但每一处没进去的都会被明确列出"}</strong>
      </div>

      {/* R42 A4：触发总上限时**就地**显示"因总注入上限，本教材有 N 章未纳入"+ 可展开清单 */}
      {!!bv.inject_cap?.configured && (bv.inject_cap.skipped_count > 0) && (
        <div className="banner warn" style={{ marginTop: 4 }}>
          因「总注入上限」{(bv.inject_cap.cap ?? 0).toLocaleString("zh-CN")} 字已用完，
          本教材有 <strong>{bv.inject_cap.skipped_count}</strong> 章/节<strong>未纳入</strong>
          （已注入 {(bv.inject_cap.used_chars ?? 0).toLocaleString("zh-CN")} 字；
          按**章/节边界**整条停止，**未在句中截断**）。
          <details style={{ marginTop: 4 }}>
            <summary>展开未纳入清单（按材料分组）</summary>
            <ul className="plain" style={{ margin: "4px 0 0 12px" }}>
              {(bv.inject_cap.skipped_by_material ?? []).map((g) => (
                <li key={g.material_id}>
                  《{g.title}》：
                  {g.items.map((it) => `${it.label}（${it.chars.toLocaleString("zh-CN")} 字）`).join("、")}
                </li>
              ))}
            </ul>
            <div className="dim" style={{ fontSize: 12 }}>
              想让它们也进去：把「总注入上限」调大或设为 0（不限）后重新起草；
              想更省又不想丢章节：调小「单次调用预算」（只会分更多批）。
            </div>
          </details>
        </div>
      )}
      {!!bv.inject_cap?.configured && bv.inject_cap.first_batch_over_cap && (
        <div className="banner warn" style={{ marginTop: 4 }}>
          你设定的总注入上限**小于第一章/节本身**：为不截断正文，首批仍整章注入
          （实际 {(bv.inject_cap.used_chars ?? 0).toLocaleString("zh-CN")} 字）——
          建议调大上限或设 0（不限）。
        </div>
      )}

      <details open style={{ marginTop: 4 }}>
        <summary>
          上一轮实际注入：{bv.last_usage.summary_zh}
          {!!bv.last_usage.cap_skipped_count &&
            ` · 因总上限未纳入 ${bv.last_usage.cap_skipped_count} 章`}
        </summary>
        <div className="dim" style={{ fontSize: 12, margin: "4px 0" }}>
          合计 <strong>{bv.last_usage.used_chars.toLocaleString("zh-CN")}</strong> 字（按章分批） ·
          分 <strong>{bv.last_usage.batch_count}</strong> 批 ·
          截断 <strong>{bv.last_usage.truncated ? "有" : "无"}</strong> ·
          丢弃 <strong>{bv.last_usage.dropped.length}</strong> 条 ·
          因总上限未纳入 <strong>{bv.last_usage.cap_skipped_count ?? 0}</strong> 章/节 ·<br />
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
                <th>因总上限未纳入</th>
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
                  <td>
                    {m.injected
                      ? "是"
                      : (m.cap_skipped_count
                          ? `部分（因总上限未纳入 ${m.cap_skipped_count} 章）`
                          : `否（${m.blocked_reason}）`)}
                  </td>
                  <td>
                    {m.cap_skipped_count
                      ? `${m.cap_skipped_count} 章：${(m.cap_skipped ?? []).join("、")}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {bv.not_injected.length > 0 && (
          <div className="banner warn" style={{ marginTop: 6 }}>
            未纳入注入的章节（{bv.not_injected.length}，含原因）：
            <ul className="plain" style={{ margin: "4px 0 0 12px" }}>
              {bv.not_injected.map((x, i) => (
                <li key={`${x.material_id ?? x.material}-${x.label}-${i}`}>
                  {x.material} · {x.label}
                  {x.reason_zh || x.reason ? ` —— ${x.reason_zh ?? x.reason}` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!bv.materials.length && <div className="dim">（本学科暂无引用材料）</div>}
      </details>
    </div>
  );
}
