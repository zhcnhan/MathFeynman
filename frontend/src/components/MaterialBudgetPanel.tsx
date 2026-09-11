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

/** 数值 → 中文档位文案（0 = 不限；数字用"万字"更好读）。 */
export function budgetText(v: number): string {
  return v === 0 ? "不限" : charsText(v);
}

/** 字数说人话：60000 → "6 万字"；800 → "800 字"。 */
export function charsText(n: number): string {
  const v = Math.max(0, Math.round(n || 0));
  if (v < 10000) return `${v.toLocaleString("zh-CN")} 字`;
  const wan = v / 10000;
  const s = wan >= 100 ? Math.round(wan).toString() : wan.toFixed(1).replace(/\.0$/, "");
  return `${Number(s).toLocaleString("zh-CN")} 万字`;
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
      setMsg("已保存，下一次生成就用新设置");
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
        <div className="dim">正在读取设置…</div>
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
      <h3 style={{ margin: "0 0 4px" }}>读多少书（本学科单独设）</h3>
      <div className="dim" style={{ fontSize: 12, marginBottom: 6 }}>
        这里只影响起草大纲和出题时**读多少教材内容**：读得少就省时间、省钱，读得多就更有依据。
        两项都可以设成「不限」。
      </div>
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner ok">{msg}</div>}

      {tierRow("① 每次读多少", bv.tiers.batch, bv.batch_chars, (v) =>
        void save({ batch_chars: v })
      )}
      <div className="dim" style={{ fontSize: 12, margin: "2px 0 8px" }}>
        一次最多读这么多。**调小只是分成几次读，一章都不会少**。
        当前：{bv.promises_zh?.batch_chars ?? "一次读不完就分次读，章节不受影响"}
      </div>

      {tierRow("② 这本书最多读多少", bv.tiers.inject, bv.inject_max_chars, (v) =>
        void save({ inject_max_chars: v })
      )}
      <div className="dim" style={{ fontSize: 12, margin: "2px 0 8px" }}>
        全书的总量上限，默认「不限」。**读到上限就停，并明确告诉你哪几章没读**。
        当前：{bv.promises_zh?.inject_max_chars ?? "到上限就停，没读的章节会列出来"}
      </div>

      {/* R42 A4：触发总上限时**就地**显示"到上限了，这些章节没读"+ 可展开清单 */}
      {!!bv.inject_cap?.configured && (bv.inject_cap.skipped_count > 0) && (
        <div className="banner warn" style={{ marginTop: 4 }}>
          这本书的「最多读多少」已经读完（已读 {charsText(bv.inject_cap.used_chars ?? 0)}），
          还有 <strong>{bv.inject_cap.skipped_count}</strong> 章/节<strong>没有读</strong>。
          到达上限时是**整章停下**的，不会把一段话读一半。
          <details style={{ marginTop: 4 }}>
            <summary>看看是哪些章节没读</summary>
            <ul className="plain" style={{ margin: "4px 0 0 12px" }}>
              {(bv.inject_cap.skipped_by_material ?? []).map((g) => (
                <li key={g.material_id}>
                  《{g.title}》：
                  {g.items.map((it) => `${it.label}（${charsText(it.chars)}）`).join("、")}
                </li>
              ))}
            </ul>
            <div className="dim" style={{ fontSize: 12 }}>
              想让这些章节也读上：把「这本书最多读多少」调大或设成不限，再重新起草；
              想更省又不想漏章节：把「每次读多少」调小（只是分几次读）。
            </div>
          </details>
        </div>
      )}
      {!!bv.inject_cap?.configured && bv.inject_cap.first_batch_over_cap && (
        <div className="banner warn" style={{ marginTop: 4 }}>
          你设的总量比第一章/第一节本身还小。为了不把正文读一半，第一章仍然整章读了
          （实际 {charsText(bv.inject_cap.used_chars ?? 0)}）——建议把总量调大或设成不限。
        </div>
      )}

      <details open style={{ marginTop: 4 }}>
        <summary>
          上次读了：{bv.last_usage.summary_zh}
          {!!bv.last_usage.cap_skipped_count &&
            ` · 到上限没读 ${bv.last_usage.cap_skipped_count} 章`}
        </summary>
        <div className="dim" style={{ fontSize: 12, margin: "4px 0" }}>
          一共 <strong>{charsText(bv.last_usage.used_chars)}</strong>（按章切分）·
          分 <strong>{bv.last_usage.batch_count}</strong> 次读完 ·
          被截掉：<strong>{bv.last_usage.truncated ? "有" : "无"}</strong> ·
          没用上：<strong>{bv.last_usage.dropped.length}</strong> 条 ·
          到上限没读：<strong>{bv.last_usage.cap_skipped_count ?? 0}</strong> 章/节 ·<br />
          阅读顺序：{bv.last_usage.order_basis}
          {bv.context_valve.applied && (
            <>
              <br />
              这本书比较大，已经自动分次读（一次最多约 {charsText(bv.context_valve.limit_chars)}）——
              不截掉正文、也不漏章节。
            </>
          )}
        </div>
        {bv.last_usage.per_material.length > 0 && (
          <table style={{ width: "100%", fontSize: 12 }}>
            <thead>
              <tr className="dim">
                <th style={{ textAlign: "left" }}>材料</th>
                <th>用途</th>
                <th>全文字数</th>
                <th>章/节数</th>
                <th>第几次读</th>
                <th>读了吗</th>
                <th>到上限没读</th>
              </tr>
            </thead>
            <tbody>
              {bv.last_usage.per_material.map((m) => (
                <tr key={m.material_id}>
                  <td style={{ textAlign: "left" }}>{m.title}</td>
                  <td>{m.role_zh}{m.role_explicit ? "" : "（未标注）"}</td>
                  <td>{charsText(m.chars_total)}</td>
                  <td>{m.entries_total}</td>
                  <td>{m.batches.length ? m.batches.join("、") : "—"}</td>
                  <td>
                    {m.injected
                      ? "读了"
                      : (m.cap_skipped_count
                          ? `读了一部分（到上限没读 ${m.cap_skipped_count} 章）`
                          : `没读（${m.blocked_reason}）`)}
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
            没读的章节（{bv.not_injected.length}）：
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
        {!bv.materials.length && <div className="dim">（还没有导入教材）</div>}
      </details>
    </div>
  );
}
