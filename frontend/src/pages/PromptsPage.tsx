// R39 §2 · 设置 →「提示词」页（**R42 C2：system 与 user 模板都可编辑**）
// 左侧调用点列表（中文名 + 用途一句话）；右侧编辑器（system / user 两个字段切换）；
// 显示**当前值 / 是否默认 / 上次修改时间**；
// 单条恢复默认（可按字段）+ 全部恢复默认（恢复前确认）；显示"与默认的差异（改了哪几行）"；
// 删掉必填占位符/硬约束 → 中文报错并**拒绝保存**。
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

type DiffLine = { kind: "hunk" | "add" | "del"; line: string; text: string };

type PromptItem = {
  call_name: string;
  label: string;
  purpose: string;
  notes?: string;
  editable_fields: string[];
  system: string;
  default_system: string;
  system_is_default: boolean;
  system_diff: DiffLine[];
  /** 可编辑的模板原文（带 {占位符}） */
  raw_template: string;
  default_raw_template: string;
  user: string;
  default_user: string;
  /** R42 C2：user 模板也开放编辑 */
  raw_user_template: string;
  default_raw_user_template: string;
  user_is_default: boolean;
  user_diff: DiffLine[];
  is_default: boolean;
  updated_at: string;
  required_placeholders: string[];
  required_tokens: string[];
  user_required_placeholders?: string[];
  user_required_tokens?: string[];
  placeholders: string[];
};

function DiffView({ title, diff }: { title: string; diff: DiffLine[] }) {
  if (!diff.length) return null;
  return (
    <div style={{ marginTop: 6 }}>
      <div className="dim" style={{ fontSize: 12 }}>
        {title}：与默认的差异（改了 {diff.filter((d) => d.kind !== "hunk").length} 行）
      </div>
      <pre
        style={{
          fontFamily: "Consolas, Menlo, monospace",
          fontSize: 12,
          background: "#fbfbfb",
          border: "1px solid #e3e9ef",
          borderRadius: 8,
          padding: 8,
          maxHeight: 200,
          overflow: "auto",
          margin: 0,
        }}
      >
        {diff.map((d, i) => (
          <div
            key={i}
            style={{
              color: d.kind === "add" ? "#1b5e20" : d.kind === "del" ? "#b3261e" : "#78909c",
              background: d.kind === "add" ? "#eef7ee" : d.kind === "del" ? "#fdecea" : "transparent",
            }}
          >
            {d.kind === "hunk" ? d.line : `${d.kind === "add" ? "+" : "-"}${d.text}`}
          </div>
        ))}
      </pre>
    </div>
  );
}

export default function PromptsPage() {
  const [items, setItems] = useState<PromptItem[]>([]);
  const [active, setActive] = useState<string>("");
  // R42 C2：两个字段各自编辑（system / user）
  const [field, setField] = useState<"system" | "user">("system");
  const [draft, setDraft] = useState("");
  const [draftUser, setDraftUser] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (keep?: string) => {
    try {
      const r = await api.get<{ prompts: PromptItem[] }>("/prompts");
      setItems(r.prompts);
      const name = keep ?? active ?? r.prompts[0]?.call_name ?? "";
      setActive(name);
      const cur = r.prompts.find((p) => p.call_name === name);
      if (cur) {
        setDraft(cur.raw_template);
        setDraftUser(cur.raw_user_template ?? "");
      }
    } catch (e) {
      setErr((e as Error).message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cur = items.find((p) => p.call_name === active) ?? null;

  const pick = (name: string) => {
    setActive(name);
    setErr("");
    setMsg("");
    const it = items.find((p) => p.call_name === name);
    if (it) {
      setDraft(it.raw_template);
      setDraftUser(it.raw_user_template ?? "");
      if (!it.editable_fields.includes("user")) setField("system");
    }
  };

  const save = async () => {
    if (!cur) return;
    if (!window.confirm("改动会影响生成结果（之后的生成会用新提示词；可在审计页对照）。确认保存？"))
      return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      // 只提交当前字段（另一字段保持原样；两个字段都能改 → R42 C2）
      const body = field === "user" ? { user: draftUser } : { system: draft };
      await api.put(`/prompts/${cur.call_name}`, body);
      setMsg(`已保存（${field}）：下一次生成即使用新提示词（可在「AI 对话记录」里对照）。`);
      await load(cur.call_name);
    } catch (e) {
      setErr((e as Error).message); // 中文拒存原因（缺占位符/硬约束）
    } finally {
      setBusy(false);
    }
  };

  const resetOne = async (f?: "system" | "user") => {
    if (!cur) return;
    const what = f === "user" ? "user 模板" : f === "system" ? "system 模板" : "整条提示词";
    if (!window.confirm(`把「${cur.label}」的**${what}**恢复为默认？自定义内容会删除（已记入总账）。`))
      return;
    setBusy(true);
    try {
      await api.post(`/prompts/${cur.call_name}/reset`, { field: f ?? "" });
      setMsg("已恢复默认。");
      await load(cur.call_name);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const resetAll = async () => {
    if (!window.confirm("把**全部**提示词恢复为默认？所有自定义内容都会删除（已记入总账）。")) return;
    setBusy(true);
    try {
      const r = await api.post<{ count: number }>("/prompts/reset-all", {});
      setMsg(`已恢复默认（${r.count} 条）。`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-page">
      <h1>提示词（所有发往模型的模板都可在程序内修改）</h1>
      <div className="dim" style={{ fontSize: 13 }}>
        左侧是全部调用点（中文名 + 用途）。改动**立即生效**；随时可恢复默认。带「必填」标记的占位符与
        硬约束**删掉会拒绝保存**（否则改坏提示词会让功能静默失效）。
      </div>
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner ok">{msg}</div>}

      <div style={{ display: "flex", gap: 12, marginTop: 10, alignItems: "flex-start" }}>
        <div className="card" style={{ width: 300, flex: "0 0 auto", maxHeight: 620, overflow: "auto" }}>
          <h2 style={{ marginTop: 0 }}>调用点（{items.length}）</h2>
          {items.map((p) => (
            <div
              key={p.call_name}
              onClick={() => pick(p.call_name)}
              style={{
                padding: "6px 8px",
                borderRadius: 8,
                cursor: "pointer",
                background: p.call_name === active ? "#e8f0fe" : "transparent",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                <strong>{p.label}</strong>
                <span className={`badge ${p.is_default ? "" : "deferred"}`}>
                  {p.is_default ? "默认" : "已改"}
                </span>
              </div>
              <div className="dim" style={{ fontSize: 12 }}>{p.purpose}</div>
            </div>
          ))}
          <button className="ghost" style={{ marginTop: 8 }} disabled={busy} onClick={() => void resetAll()}>
            全部恢复默认
          </button>
        </div>

        <div className="card" style={{ flex: 1, minWidth: 0 }}>
          {!cur ? (
            <p className="empty">请选择左侧调用点。</p>
          ) : (
            <>
              <h2 style={{ marginTop: 0 }}>{cur.label}（{cur.call_name}）</h2>
              <div className="dim" style={{ fontSize: 12 }}>
                {cur.purpose}
                <br />
                当前值：
                {field === "user"
                  ? (cur.user_is_default ? "**默认**" : "**你已修改**")
                  : (cur.system_is_default ? "**默认**" : "**你已修改**")}
                {cur.updated_at ? ` · 上次修改：${cur.updated_at.replace("T", " ").replace("+00:00", " UTC")}` : ""}
                {cur.notes ? ` · 提示：${cur.notes}` : ""}
              </div>
              {/* R42 C2：字段切换（system / user 都可改） */}
              <div className="input-row" style={{ gap: 6, marginTop: 6 }}>
                <button className={field === "system" ? "depth active" : "depth"} disabled={busy}
                        onClick={() => setField("system")}>
                  system 模板{cur.system_is_default ? "" : "（已改）"}
                </button>
                {cur.editable_fields.includes("user") && (
                  <button className={field === "user" ? "depth active" : "depth"} disabled={busy}
                          onClick={() => setField("user")}>
                    user 模板{cur.user_is_default ? "" : "（已改）"}
                  </button>
                )}
              </div>
              {(field === "user" ? cur.user_required_placeholders ?? [] : cur.required_placeholders).length > 0 && (
                <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
                  必填占位符（删掉会拒存）：
                  {(field === "user" ? cur.user_required_placeholders ?? [] : cur.required_placeholders)
                    .map((x) => `{${x}}`).join(" ")}
                </div>
              )}
              {(field === "user" ? cur.user_required_tokens ?? [] : cur.required_tokens).length > 0 && (
                <div className="dim" style={{ fontSize: 12 }}>
                  必留硬约束（删掉会拒存）：
                  {(field === "user" ? cur.user_required_tokens ?? [] : cur.required_tokens).join(" / ")}
                </div>
              )}
              <textarea
                value={field === "user" ? draftUser : draft}
                onChange={(e) => (field === "user" ? setDraftUser(e.target.value) : setDraft(e.target.value))}
                spellCheck={false}
                style={{
                  width: "100%",
                  minHeight: 320,
                  marginTop: 8,
                  fontFamily: "Consolas, Menlo, monospace",
                  fontSize: 12,
                  borderRadius: 8,
                  border: "1px solid #c5cdd6",
                  padding: 8,
                }}
              />
              <div className="input-row" style={{ gap: 8, marginTop: 6 }}>
                <button className="primary" disabled={busy} onClick={() => void save()}>
                  保存（立即生效）
                </button>
                <button className="ghost" disabled={busy} onClick={() => void resetOne()}>
                  恢复默认（整条）
                </button>
                <button className="ghost" disabled={busy} onClick={() => void resetOne(field)}>
                  恢复默认（仅 {field}）
                </button>
                <button className="ghost" disabled={busy}
                        onClick={() => (field === "user"
                          ? setDraftUser(cur.default_raw_user_template ?? "")
                          : setDraft(cur.default_raw_template))}>
                  载入默认文本（不保存）
                </button>
              </div>
              <DiffView title={field === "user" ? "user" : "system"}
                        diff={field === "user" ? cur.user_diff : cur.system_diff} />
              {cur.editable_fields.includes("user") && (
                <details style={{ marginTop: 8 }}>
                  <summary className="dim">
                    {field === "user" ? "system（只读对照）" : "user（只读对照）"}
                  </summary>
                  <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, maxHeight: 240, overflow: "auto" }}>
                    {field === "user" ? cur.system : cur.user}
                  </pre>
                </details>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
