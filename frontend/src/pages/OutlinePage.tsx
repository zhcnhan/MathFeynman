import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";

type Unit = {
  id: string;
  title: string;
  objectives: string[];
  concept_tags: string[];
  group: string;
  prereqs: string[];
  difficulty: number;
  requires_thinking: boolean;
  anchors: string[];
  topic: string;
  status: string;
};

type UnitView = {
  id: string;
  title: string;
  group: string;
  concept_tags: string[];
  status: string;
  open: boolean;
  content_ids: string[];
  prereqs: string[];
};

const STATUS_LABEL: Record<string, string> = {
  mastered: "已掌握",
  equivalent: "等效掌握",
  learning: "学习中",
  todo: "待学",
  draft: "草稿",
  reviewed: "转正",
};
const STATUS_CLS: Record<string, string> = {
  mastered: "pass",
  equivalent: "",
  learning: "deferred",
  todo: "",
  draft: "deferred",
};

export default function OutlinePage() {
  const { id = "" } = useParams();
  const [subject, setSubject] = useState<Record<string, any> | null>(null);
  const [outline, setOutline] = useState<Record<string, any> | null>(null);
  const [progress, setProgress] = useState<{ units: UnitView[]; concepts_mastered: number } | null>(null);
  const [candidate, setCandidate] = useState<{ units: Unit[]; source: string; problems: string[]; ok: boolean } | null>(null);
  const [draftBrief, setDraftBrief] = useState("");
  const [draftCount, setDraftCount] = useState(6);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [tagsDraft, setTagsDraft] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const s = await api.get<Record<string, any>>(`/subjects/${id}`);
      setSubject(s);
      let o: Record<string, any> | null = null;
      let p: any = null;
      try {
        o = await api.get<Record<string, any>>(`/subjects/${id}/outline`);
        p = await api.get(`/subjects/${id}/progress`);
      } catch {
        /* 无大纲 404 正常 */
      }
      setOutline(o);
      setProgress(p);
      const t: Record<string, string> = {};
      if (o) for (const u of o.units as Unit[]) t[u.id] = (u.concept_tags || []).join("，");
      setTagsDraft(t);
    } catch (e) {
      setErr(String(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const draft = async (regen = false) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const path = regen
        ? `/subjects/${id}/outline/regenerate`
        : `/subjects/${id}/outline/draft`;
      const c = await api.post<{ units: Unit[]; source: string; problems: string[]; ok: boolean }>(
        path,
        regen ? undefined : { brief: draftBrief, count: draftCount, group_hint: "" }
      );
      setCandidate(c);
      if (!c.ok) setErr("起草候选存在问题：" + c.problems.slice(0, 3).join("；"));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const adopt = async () => {
    if (!candidate) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api.put(`/subjects/${id}/outline`, {
        units: candidate.units,
        status: "active",
        source: candidate.source === "heuristic" ? "heuristic" : candidate.source,
      });
      setCandidate(null);
      await load();
      setMsg("大纲已采纳（revision+1）");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveTags = async (uid: string) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const tags = (tagsDraft[uid] || "")
        .split(/[,，;；]/)
        .map((s) => s.trim())
        .filter(Boolean);
      await api.patch(`/subjects/${id}/outline/units/${uid}`, { fields: { concept_tags: tags } });
      await load();
      setMsg(`单元 ${uid} 概念标签已保存`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const genContent = async (uid: string) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{ status: string; node_id: string }>(`/subjects/${id}/units/${uid}/content`);
      setMsg(`单元 ${uid} 内容：${r.status === "exists" ? "已在库（幂等）" : "已生成（source:auto）"}`);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const resetProgress = async () => {
    if (!window.confirm(`确认显式重置「${subject?.label}」学科进度？概念层与内容掌握将清空。`)) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.post<{ nodes_reset: number }>(`/subjects/${id}/progress/reset`, { mode: "all" });
      setMsg(`进度已重置（清空 ${r.nodes_reset} 个内容节点掌握）`);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const isPreset = subject?.kind === "preset";
  const progressById: Record<string, UnitView> = {};
  if (progress) for (const u of progress.units) progressById[u.id] = u;

  return (
    <div>
      <div className="crumbs">
        <Link to="/subjects">← 学科列表</Link>
      </div>
      {subject && (
        <>
          <h1>
            {subject.label}{" "}
            <span className="badge">{isPreset ? "预置（数学=roadmap 治理）" : "自定义学科"}</span>
          </h1>
          <div className="dim">{subject.id} · {subject.description}</div>
        </>
      )}
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner ok">{msg}</div>}

      {/* 起草 / 采纳（无大纲或重生成时） */}
      <div className="card">
        <h2>大纲起草与审阅</h2>
        {isPreset ? (
          <div className="dim">
            预置学科（数学）大纲由五学段 roadmap 派生治理（docs/14 §5）。当前版本：
            v{outline?.revision ?? "-"} · {outline?.units?.length ?? 0} 单元。
            <button style={{ marginLeft: 10 }} disabled={busy} onClick={() => draft(true)}>
              由 roadmap 重新派生（regenerate）
            </button>
          </div>
        ) : (
          <>
            <div className="input-row" style={{ margin: "6px 0" }}>
              <input
                placeholder="给 AI 的学科简介 / 学习目标（选填）"
                value={draftBrief}
                onChange={(e) => setDraftBrief(e.target.value)}
                style={{ flex: 1, padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }}
              />
              <select value={draftCount} onChange={(e) => setDraftCount(Number(e.target.value))}>
                {[4, 6, 8, 10, 15].map((n) => (
                  <option key={n} value={n}>{n} 单元</option>
                ))}
              </select>
              <button className="primary" disabled={busy} onClick={() => draft(false)}>
                {outline ? "重新起草（丢弃当前稿）" : "AI 起草大纲"}
              </button>
            </div>
            <div className="dim">起草仅生成候选（不落盘）；审阅后点“采纳”（大纲版本 revision+1）。无 LLM_KEY 时为离线启发式候选。</div>
          </>
        )}
        {candidate && (
          <div className="card" style={{ borderColor: "#90caf9" }}>
            <h2>起草候选（{candidate.source === "ai" ? "AI" : "启发式（离线）"} · 未落盘）</h2>
            {candidate.problems?.length > 0 && (
              <div className="banner warn">候选提示：{candidate.problems.slice(0, 5).join("；")}</div>
            )}
            {candidate.units.map((u, i) => (
              <div key={u.id} style={{ padding: "4px 0", borderBottom: "1px solid #eef2f6" }}>
                <strong>{i + 1}. {u.title}</strong>{" "}
                <span className="badge">{u.group}</span>
                {u.prereqs.length > 0 && <span className="dim"> 前置：{u.prereqs.join("、")}</span>}
                <div className="chip">{u.concept_tags?.join(" · ")}</div>
              </div>
            ))}
            <div style={{ marginTop: 10 }}>
              <button className="primary" onClick={adopt} disabled={busy}>采纳此大纲</button>{" "}
              <button onClick={() => setCandidate(null)} disabled={busy}>放弃候选</button>
            </div>
          </div>
        )}
      </div>

      {outline && (
        <div className="card">
          <div className="session-head">
            <h2 style={{ margin: 0 }}>
              大纲 v{outline.revision}（{outline.status}/{outline.source}）· schema v{outline.schema_version}
            </h2>
            {progress && (
              <span className="badge pass">已掌握概念 {progress.concepts_mastered}</span>
            )}
            {!isPreset && (
              <span>
                <button className="ghost" disabled={busy} onClick={resetProgress}>重置学科进度</button>
              </span>
            )}
          </div>
          {outline.note && <div className="dim">{outline.note}</div>}
          {outline.groups?.map?.((g: string) => (
            <div key={g}>
              <h2>▸ {g}</h2>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <tbody>
                  {(outline.units as Unit[])
                    .filter((u) => u.group === g)
                    .map((u) => {
                      const pv = progressById[u.id];
                      return (
                        <tr key={u.id} style={{ borderBottom: "1px solid #eef2f6" }}>
                          <td style={{ padding: "6px 4px", width: 130 }} className="dim">{u.id}</td>
                          <td style={{ padding: "6px 4px" }}>
                            <strong>{u.title}</strong>
                            {u.status === "reviewed" && <span className="badge pass">转正</span>}
                          </td>
                          <td style={{ padding: "6px 4px" }}>
                            {pv && (
                              <span className={`badge ${STATUS_CLS[pv.status] ?? ""}`}>
                                {STATUS_LABEL[pv.status] ?? pv.status}
                                {pv.open && pv.status === "todo" ? " · 可学" : ""}
                              </span>
                            )}
                          </td>
                          <td style={{ padding: "6px 4px" }}>
                            <input
                              value={tagsDraft[u.id] ?? ""}
                              onChange={(e) => setTagsDraft({ ...tagsDraft, [u.id]: e.target.value })}
                              placeholder="概念标签（逗号分隔）"
                              style={{ width: 220, padding: 4, borderRadius: 6, border: "1px solid #c5cdd6" }}
                            />
                            <button style={{ marginLeft: 4, padding: "4px 10px" }} onClick={() => saveTags(u.id)} disabled={busy}>
                              存
                            </button>
                          </td>
                          <td style={{ padding: "6px 4px" }}>
                            {!isPreset && (
                              <button style={{ padding: "4px 10px" }} onClick={() => genContent(u.id)} disabled={busy}>
                                懒生成内容
                              </button>
                            )}
                            {u.prereqs.length > 0 && <span className="dim"> 前置 {u.prereqs.length}</span>}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
