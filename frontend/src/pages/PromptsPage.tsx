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
  /** R52 A2（后端只读统计）：与其它调用点"共用同一份模板文本"的个数（0＝本调用点独有） */
  system_shared_with?: number;
  user_shared_with?: number;
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
  // R52 A1：**默认显示 user 模板**——它才是每个调用点各不相同的"这次具体干什么活"；
  //          各调用点的 system 往往共用同一份，先看 system 会以为"提示词都是同一个"。
  const [field, setField] = useState<"system" | "user">("user");
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
        // 该调用点没有 user 模板时，别把编辑器停在空的 user 栏上
        if (field === "user" && !cur.editable_fields.includes("user")) setField("system");
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
      setMsg("已保存：下一次生成就用新提示词（可在「AI 对话记录」里对照）。");
      await load(cur.call_name);
    } catch (e) {
      setErr((e as Error).message); // 中文拒存原因（缺占位符/硬约束）
    } finally {
      setBusy(false);
    }
  };

  const resetOne = async (f?: "system" | "user") => {
    if (!cur) return;
    const what = f === "user" ? "「每次具体怎么干活」那一份" : f === "system" ? "「角色与总纪律」那一份" : "整条";
    if (!window.confirm(`把「${cur.label}」的${what}恢复成默认？你改过的内容会删除（会记进「记录」里）。`))
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
    if (!window.confirm("把全部提示词恢复成默认？你改过的内容都会删除（会记进「记录」里）。")) return;
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
      <h1>提示词（可以自己改）</h1>
      <div className="dim" style={{ fontSize: 13 }}>
        这里列的是程序每次问 AI 时用的原话。左边挑一处，右边直接改，保存后**下一次就生效**；
        改坏了随时能恢复默认。带「必填」标记的花括号是程序往里填内容的位置（比如这次的题目、学生的回答），
        删掉就存不了——这是防止改坏之后功能悄悄失灵。
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
              <h2 style={{ marginTop: 0 }}>{cur.label}</h2>
              <div className="dim" style={{ fontSize: 12 }}>
                {cur.purpose}
                <br />
                现在这份：
                {field === "user"
                  ? (cur.user_is_default ? "默认" : "你改过")
                  : (cur.system_is_default ? "默认" : "你改过")}
                {cur.updated_at ? ` · 上次修改：${cur.updated_at.replace("T", " ").replace("+00:00", " UTC")}` : ""}
                {cur.notes ? ` · 提示：${cur.notes}` : ""}
              </div>
              {/* R52 A1：字段按钮各自写明性质（哪个"每个调用点都不一样"、哪个"多处共用"） */}
              <div className="input-row" style={{ gap: 6, marginTop: 6, alignItems: "stretch" }}>
                {cur.editable_fields.includes("user") && (
                  <button className={field === "user" ? "depth active" : "depth"} disabled={busy}
                          onClick={() => setField("user")}
                          style={{ textAlign: "left", lineHeight: 1.35 }}>
                    <div>这次具体怎么干活{cur.user_is_default ? "" : "（已改）"}</div>
                    <div className="dim" style={{ fontSize: 11 }}>
                      每处都不一样{(cur.user_shared_with ?? 0) > 0 ? `（与 ${cur.user_shared_with} 处相同）` : ""}
                    </div>
                  </button>
                )}
                <button className={field === "system" ? "depth active" : "depth"} disabled={busy}
                        onClick={() => setField("system")}
                        style={{ textAlign: "left", lineHeight: 1.35 }}>
                  <div>角色与总纪律{cur.system_is_default ? "" : "（已改）"}</div>
                  <div className="dim" style={{ fontSize: 11 }}>
                    {(cur.system_shared_with ?? 0) > 0
                      ? `${(cur.system_shared_with ?? 0) + 1} 处共用同一份`
                      : "只有这一处在用"}
                  </div>
                </button>
              </div>
              {/* R52 A2：把"共用"这件事直接说白（N 由后端算）——共用文本 ≠ 改一处全变 */}
              {field === "system" && (
                <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>
                  {(cur.system_shared_with ?? 0) > 0
                    ? `这份「角色与总纪律」和另外 ${cur.system_shared_with} 处用的是同一段文字——在这里改，只影响「${cur.label}」这一处。`
                    : "这份「角色与总纪律」只有这一处在用。"}
                </div>
              )}
              {(field === "user" ? cur.user_required_placeholders ?? [] : cur.required_placeholders).length > 0 && (
                <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
                  必须留着的位置（删掉就存不了，花括号里是程序填内容的地方）：
                  {(field === "user" ? cur.user_required_placeholders ?? [] : cur.required_placeholders)
                    .map((x) => `{${x}}`).join(" ")}
                </div>
              )}
              {(field === "user" ? cur.user_required_tokens ?? [] : cur.required_tokens).length > 0 && (
                <div className="dim" style={{ fontSize: 12 }}>
                  必须留着的要求（删掉就存不了）：
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
                  保存（下一次就生效）
                </button>
                <button className="ghost" disabled={busy} onClick={() => void resetOne()}>
                  两处都恢复默认
                </button>
                <button className="ghost" disabled={busy} onClick={() => void resetOne(field)}>
                  只恢复这一份
                </button>
                <button className="ghost" disabled={busy}
                        onClick={() => (field === "user"
                          ? setDraftUser(cur.default_raw_user_template ?? "")
                          : setDraft(cur.default_raw_template))}>
                  填入默认文字（先不保存）
                </button>
              </div>
              <DiffView title={field === "user" ? "这次具体怎么干活" : "角色与总纪律"}
                        diff={field === "user" ? cur.user_diff : cur.system_diff} />
              {cur.editable_fields.includes("user") && (
                <details style={{ marginTop: 8 }}>
                  <summary className="dim">
                    {field === "user" ? "另一份（角色与总纪律，只看不改）" : "另一份（这次具体怎么干活，只看不改）"}
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
