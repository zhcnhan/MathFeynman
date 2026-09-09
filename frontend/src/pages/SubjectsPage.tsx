import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

interface OutlineSummary {
  exists: boolean;
  revision: number;
  status: string;
  source: string;
  schema_version: number;
  units: number;
  groups: string[];
  updated_at: string;
}
interface SubjectItem {
  id: string;
  label: string;
  kind: string;
  description: string;
  enabled: boolean;
  removed_at?: string | null;
  source_policy?: string;
  outline: OutlineSummary | null;
}

export default function SubjectsPage() {
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [label, setLabel] = useState("");
  const [desc, setDesc] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [showRemoved, setShowRemoved] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async (incl: boolean) => {
    try {
      const q = incl ? "?include_removed=1" : "";
      const r = await api.get<{ subjects: SubjectItem[] }>(`/subjects${q}`);
      setSubjects(r.subjects);
    } catch (e) {
      setErr(String(e));
    }
  };
  useEffect(() => {
    void load(showRemoved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showRemoved]);

  const create = async () => {
    setErr("");
    setBusy(true);
    try {
      await api.post("/subjects", {
        label,
        description: desc,
        subject_id: subjectId.trim() || undefined,
      });
      setLabel("");
      setDesc("");
      setSubjectId("");
      await load(showRemoved);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    setErr("");
    setBusy(true);
    try {
      await fn();
      await load(showRemoved);
      setErr(okMsg); // 复用横幅显示成功提示
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1>学科（Subjects）</h1>
      {err && <div className={`banner ${err.startsWith("✅") ? "ok" : "error"}`}>{err}</div>}
      <label className="dim" style={{ marginBottom: 8, display: "inline-flex", gap: 6, alignItems: "center" }}>
        <input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} />
        显示已移除（可重新启用）
      </label>
      <div className="grid" style={{ marginTop: 8 }}>
        {subjects.map((s) => (
          <div key={s.id} className="card" style={{ opacity: s.enabled ? 1 : 0.72 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Link to={`/subjects/${s.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                <strong>{s.label}</strong>
              </Link>
              <span className={`badge ${!s.enabled ? "deferred" : s.kind === "preset" ? "" : "pass"}`}>
                {!s.enabled ? "已停用" : s.kind === "preset" ? "预置" : "自建"}
              </span>
            </div>
            <div className="dim">{s.id} · 来源策略 {s.source_policy ?? "ai"}</div>
            {s.description && <div className="dim">{s.description}</div>}
            <div className="dim" style={{ marginTop: 6 }}>
              {s.outline
                ? `大纲 v${s.outline.revision}（${s.outline.status}/${s.outline.source}）· ${s.outline.units} 单元`
                : "尚无大纲"}
            </div>
            <div className="input-row" style={{ marginTop: 8 }}>
              {!s.enabled ? (
                <button className="primary" disabled={busy}
                        onClick={() => void act(() => api.post(`/subjects/${s.id}/enable`), "✅ 已重新启用")}>
                  重新启用
                </button>
              ) : (
                <button className="ghost" disabled={busy}
                        onClick={() => {
                          if (window.confirm(`移除学科「${s.label}」？（停用隐藏、进度清空；文件留盘可随时重新启用）`)) {
                            void act(() => api.del(`/subjects/${s.id}`), "✅ 已移除（可重新启用）");
                          }
                        }}>
                  移除
                </button>
              )}
              {s.enabled && s.kind !== "preset" && (
                <button className="ghost" disabled={busy}
                        onClick={() => {
                          if (window.confirm(`彻底删除「${s.label}」连同内容文件？（不可恢复）`)) {
                            void act(() => api.del(`/subjects/${s.id}?hard=true`), "✅ 已彻底删除");
                          }
                        }}>
                  连同文件删除
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="card">
        <h2>新建学科（自定义 · docs/14 通用教练）</h2>
        <div className="input-row" style={{ margin: "6px 0" }}>
          <input placeholder="学科名称（必填）" value={label}
                 onChange={(e) => setLabel(e.target.value)} style={{ padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }} />
          <input placeholder="学科 id（小写字母数字连字符；留空自动）" value={subjectId}
                 onChange={(e) => setSubjectId(e.target.value)} style={{ padding: 7, borderRadius: 8, border: "1px solid #c5cdd6", width: 280 }} />
        </div>
        <div className="input-row" style={{ margin: "6px 0" }}>
          <input placeholder="学习目标/简介（选填，供 AI 起草参考）" value={desc}
                 onChange={(e) => setDesc(e.target.value)}
                 style={{ flex: 1, padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }} />
          <button className="primary" onClick={create} disabled={busy || !label.trim()}>创建学科</button>
        </div>
      </div>
    </div>
  );
}
