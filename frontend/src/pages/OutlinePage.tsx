import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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

type MaterialItem = {
  id: string;
  title: string;
  source: string;
  url: string;
  kind: string;
  file: string;
  filename?: string;
};

type SearchCandidate = {
  title: string;
  url: string;
  source: string;
  summary: string;
  reason?: string;
};

type SearchResult = {
  items: SearchCandidate[];
  note: string;
  backend: { configured: boolean; provider: string; url?: string; note?: string };
};

const KIND_LABEL: Record<string, string> = {
  local: "文本",
  web: "网页",
  pdf: "PDF",
};

export default function OutlinePage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
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
  const [policy, setPolicy] = useState("ai"); // B3：来源策略
  const [matTitle, setMatTitle] = useState("");
  const [matText, setMatText] = useState("");
  const [materials, setMaterials] = useState<MaterialItem[]>([]);
  // Phase C C1：联网候选清单（provider 状态标注 + 勾选 → 本地化引用）
  const [searchQ, setSearchQ] = useState("");
  const [searchRes, setSearchRes] = useState<SearchResult | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [searchBusy, setSearchBusy] = useState(false);
  // C2：PDF 上传（pypdf 分页/分节入库）
  const pdfFileRef = useRef<HTMLInputElement>(null);

  const uploadPdf = async () => {
    const inp = pdfFileRef.current;
    const f = inp?.files?.[0];
    if (!f) {
      setErr("请先选择要上传的 PDF 文件");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const fd = new FormData();
      if (matTitle.trim()) fd.append("title", matTitle.trim());
      fd.append("file", f);
      const r = await api.upload<{ id: string; title: string; pages: number; filename: string }>(
        `/subjects/${id}/materials/upload-pdf`, fd
      );
      setMsg(`PDF 已解析入库「${r.title}」（${r.pages} 页，分页文本可作为参考来源）`);
      if (inp) inp.value = "";
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const loadMaterials = async () => {
    try {
      const r = await api.get<{ materials: MaterialItem[] }>(
        `/subjects/${id}/materials`
      );
      setMaterials(r.materials);
      const p = await api.get<{ source_policy: string }>(`/subjects/${id}/policy`);
      setPolicy(p.source_policy);
    } catch {
      /* 停用/无权限等：静默 */
    }
  };

  const deleteMaterial = async (mid: string) => {
    if (!window.confirm("确认删除该引用材料？（重生成单元时将不再引用）")) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api.del(`/subjects/${id}/materials/${mid}`);
      setMsg("材料已删除");
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const runSearch = async () => {
    if (!searchQ.trim()) return;
    setSearchBusy(true);
    setErr("");
    setMsg("");
    setSearchRes(null);
    try {
      const r = await api.post<SearchResult>(`/subjects/${id}/materials/search`, { query: searchQ });
      setSearchRes(r);
      setChecked({});
    } catch (e) {
      setErr(String(e));
    } finally {
      setSearchBusy(false);
    }
  };

  const selectChecked = async () => {
    const items = (searchRes?.items ?? []).filter((_, i) => checked[String(i)]);
    if (items.length === 0) {
      setErr("请先勾选至少 1 条候选");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{ saved: { title: string; kind: string }[] }>(`/subjects/${id}/materials/select`, {
        items: items.map((it) => ({ title: it.title, url: it.url, source: it.source, summary: it.summary, reason: it.reason ?? "", fetch: true })),
      });
      setMsg(`已本地化入库 ${r.saved.length} 条引用材料（勾选公开网页已抓取正文，可追溯来源）`);
      setSearchRes(null);
      setChecked({});
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const setPolicyNow = async (value: string) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.put<{ source_policy: string }>(`/subjects/${id}/policy`, { source_policy: value });
      setPolicy(r.source_policy);
      setMsg("内容来源策略已更新");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const uploadMaterial = async () => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{ title: string }>(`/subjects/${id}/materials/upload`, {
        title: matTitle,
        text: matText,
        source: "本地导入",
      });
      setMsg(`已导入材料「${r.title}」（重生成单元时会作为参考来源）`);
      setMatTitle("");
      setMatText("");
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

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
    void loadMaterials();
  }, [load]);

  const draft = async (regen = false) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const path = regen
        ? `/subjects/${id}/outline/regenerate`
        : `/subjects/${id}/outline/draft`;
      const c = await api.post<Record<string, any>>(
        path,
        regen ? undefined : { brief: draftBrief, count: draftCount, group_hint: "" }
      );
      if (c && typeof c.ok === "boolean") {
        // 候选（custom 起草/重起草）：预览后采纳
        setCandidate(c as any);
        if (!c.ok) setErr("起草候选存在问题：" + (c.problems || []).slice(0, 3).join("；"));
      } else {
        // math preset regenerate = 已直接派生落盘（非候选）→ 刷新展示
        setCandidate(null);
        await load();
        setMsg("大纲已重新生成并落盘（revision 递增）");
      }
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

  const learnUnit = async (uid: string) => {
    setBusy(true);
    setErr("");
    try {
      const r = await api.post<{ session: { id: string } }>("/session/start", { node_id: uid });
      nav(`/session/${r.session.id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const isPreset = subject?.kind === "preset";
  const progressById: Record<string, UnitView> = {};
  if (progress) for (const u of progress.units) progressById[u.id] = u;
  // 分组不在大纲顶层字段：由单元 group 首次出现序派生（后端 unit.group 为准）
  const groups: string[] = outline
    ? Array.from(new Set((outline.units as Unit[]).map((u) => u.group).filter(Boolean) as string[]))
    : [];

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

      {/* 学科管理：内容来源策略 + 材料层（docs/14 §8 · Phase B B3 + Phase C C1） */}
      <div className="card">
        <h2>学科管理 · 内容来源与材料</h2>
        <div className="input-row" style={{ gap: 10, margin: "6px 0" }}>
          <label className="dim">来源策略</label>
          <select value={policy} disabled={busy} onChange={(e) => void setPolicyNow(e.target.value)}>
            <option value="ai">AI 全生成</option>
            <option value="import">本地教材导入</option>
            <option value="web">联网候选清单</option>
            <option value="mixed">混合</option>
          </select>
        </div>

        <div className="dim" style={{ margin: "4px 0" }}>
          引用材料（{materials.length}）：本地导入/联网勾选/PDF 上传入库后，重生成单元会作为
          可追溯参考来源注入讲解（讲解尾部出现"参考材料（可追溯来源）"）。
        </div>

        {/* 联网候选清单（C1：provider 抽象 + 勾选入库） */}
        <div style={{ margin: "6px 0" }}>
          <div className="input-row" style={{ gap: 8 }}>
            <input placeholder="检索词（如：行星科学 入门教材）" value={searchQ}
                   onChange={(e) => setSearchQ(e.target.value)}
                   style={{ flex: 1, padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }} />
            <button className="ghost" disabled={busy || searchBusy || !searchQ.trim()}
                    onClick={() => void runSearch()}>
              {searchBusy ? "检索中…" : "联网检索 → 候选清单"}
            </button>
          </div>
          {searchRes && (
            <div style={{ marginTop: 6 }}>
              {searchRes.backend && !searchRes.backend.configured && (
                <div className="banner warn">检索后端未配置（当前无检索 provider）。{searchRes.note}</div>
              )}
              {searchRes.note && searchRes.backend?.configured && (
                <div className="dim">{searchRes.note}</div>
              )}
              {searchRes.items.length > 0 && (
                <>
                  <div className="dim" style={{ margin: "4px 0" }}>
                    候选 {searchRes.items.length} 条 · 勾选后"本地化入库"（勾选公开网页将抓取正文；
                    书籍类不整本下载，PDF 请走上传）
                  </div>
                  {searchRes.items.map((it, i) => (
                    <div key={`${it.url}-${i}`} style={{ padding: "3px 0", display: "flex", gap: 8, alignItems: "flex-start" }}>
                      <input type="checkbox" checked={!!checked[String(i)]}
                             onChange={(e) => setChecked({ ...checked, [String(i)]: e.target.checked })} />
                      <div>
                        <strong>{it.title}</strong>{" "}
                        <span className="dim">{it.source}</span>
                        <div className="dim" style={{ fontSize: 12 }}>
                          {it.summary}
                          {it.reason && <span> · 理由：{it.reason}</span>}
                        </div>
                        <div className="dim" style={{ fontSize: 12, wordBreak: "break-all" }}>{it.url}</div>
                      </div>
                    </div>
                  ))}
                  <button className="primary" disabled={busy}
                          onClick={() => void selectChecked()}>
                    勾选入库（{Object.values(checked).filter(Boolean).length}）
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {/* 本地导入：粘贴文本 */}
        <div className="input-row" style={{ gap: 8, margin: "6px 0" }}>
          <input placeholder="材料标题（如：教材第一章）" value={matTitle} onChange={(e) => setMatTitle(e.target.value)}
                 style={{ flex: 1, padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }} />
          <button className="primary" disabled={busy || !matTitle.trim() || !matText.trim()}
                  onClick={() => void uploadMaterial()}>
            导入文本
          </button>
        </div>
        <textarea placeholder="粘贴自有/授权教材文本…（选填更多材料）" value={matText}
                  onChange={(e) => setMatText(e.target.value)}
                  style={{ width: "100%", minHeight: 56, border: "1px solid #c5cdd6", borderRadius: 8, padding: 8, font: "inherit" }} />

        {/* C2：PDF 上传（分页/分节 → 引用库 kind:pdf；保留文本粘贴入口） */}
        <div className="input-row" style={{ gap: 8, margin: "8px 0" }}>
          <input type="file" accept=".pdf,application/pdf" ref={pdfFileRef} disabled={busy}
                 style={{ flex: 1 }} />
          <button className="primary" disabled={busy} onClick={() => void uploadPdf()}>
            上传 PDF → 引用库
          </button>
        </div>
        <div className="dim" style={{ fontSize: 12 }}>
          PDF ≤20MB，解析为分页/分节文本入库（kind=PDF，来源可追溯）；扫描图片版请先 OCR 或改用文本粘贴；
          仅上传自有/授权资料，不整本下载书籍。
        </div>

        {/* 引用材料列表（可删除） */}
        {materials.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {materials.map((m) => (
              <div key={m.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                                       padding: "4px 0", borderBottom: "1px solid #eef2f6", gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  <strong>{m.title}</strong>{" "}
                  <span className="badge">{KIND_LABEL[m.kind] ?? m.kind}</span>{" "}
                  <span className="dim">{m.source}</span>
                  {m.filename && <div className="dim" style={{ fontSize: 12 }}>文件：{m.filename}</div>}
                  {m.url && <div className="dim" style={{ fontSize: 12, wordBreak: "break-all" }}>{m.url}</div>}
                </div>
                <button className="ghost" disabled={busy} style={{ whiteSpace: "nowrap" }}
                        onClick={() => void deleteMaterial(m.id)}>
                  删除
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

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
          {groups.map((g: string) => (
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
                              <>
                                <button style={{ padding: "4px 10px" }} onClick={() => genContent(u.id)} disabled={busy}>
                                  懒生成内容
                                </button>{" "}
                                <button style={{ padding: "4px 10px" }} onClick={() => learnUnit(u.id)} disabled={busy}
                                  title={pv?.open ? "开始学习此单元" : "未解锁（需先完成前置单元）"}>
                                  开始学习
                                </button>
                              </>
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
