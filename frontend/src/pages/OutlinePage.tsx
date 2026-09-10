import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import MaterialBudgetPanel from "../components/MaterialBudgetPanel";
import LedgerAlerts, { LedgerEntry } from "../components/LedgerAlerts";

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
  // R36 D2：逐单元材料溯源（服务端已校验：title 属于本学科引用库，section 为真实章节名或逐字引文）
  materials?: { title: string; section: string }[];
  // R42 B1/B2：附加元数据（难度被非降钳制抬高 / 过短条目已并入）——大纲页必须看得见
  meta?: {
    difficulty_raised?: { from: number; to: number; reason_zh: string; because?: string };
    absorbed_short?: { label: string; chars: number }[];
    coverage?: Record<string, unknown>;
  };
};

/** R36 D3：把大纲层的 source_materials（material_id 列表）显示为材料标题。 */
function materialTitles(ids: string[] | undefined, materials: MaterialItem[]): string[] {
  if (!ids || ids.length === 0) return [];
  const byId = new Map(materials.map((m) => [m.id, m.title]));
  return ids.map((id) => byId.get(id) ?? id);
}

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
  // R38 B2：材料角色（主教材 / 补充材料；未标注 → main + explicit=false，按导入顺序）
  role?: string;
  role_explicit?: boolean;
  role_zh?: string;
  // R37 S7：文本层健康度（扫描/图片版 → 中文告知，不静默出稿）
  text_health?: { pages: number; chars: number; healthy: boolean; checked: boolean; note: string };
};

// R37 S6：覆盖账本（教材章节 ↔ 单元映射 ↔ 单元覆盖状态）
type CoverageEntry = {
  material: string;
  material_id?: string;
  label: string;
  chapter: string;
  chars: number;
  sections: string[];
  pages?: string[];
  units: string[];
  covered: boolean;
};

type CoverageUnit = {
  unit_id: string;
  title: string;
  sources: { title: string; section: string }[];
  status: string;
  note: string;
  grounded_facts: number;
  material_bound: boolean;
  dropped_exercises: number;
  /** R42 B4：章内该节级依据（R40 §2-3 提升项） */
  basis_section?: string;
  basis_quote?: string;
  basis_note?: string;
};

// R38 B1：覆盖账**跨全部材料**统计 + 未覆盖清单**按材料分组**
type CoverageByMaterial = {
  material_id: string;
  title: string;
  role: string;
  role_explicit: boolean;
  role_zh: string;
  total: number;
  covered: number;
  uncovered: string[];
  chars: number;
  pages: number;
  healthy: boolean;
  note: string;
  /** R42 A3：本材料因「总注入上限」未注入的章/节 */
  cap_skipped?: string[];
  cap_skipped_count?: number;
};

type NotInjected = {
  material: string;
  material_id?: string;
  label: string;
  chars: number;
  note: string;
  reason?: string;
  reason_zh?: string;
};

type Coverage = {
  has_materials: boolean;
  total: number;
  covered: number;
  uncovered: string[];
  page_total?: number;
  page_covered?: number;
  by_material?: CoverageByMaterial[];
  uncovered_by_material?: { material_id: string; title: string; role_zh: string; items: { label: string; chapter: string; chars: number; pages: string[] }[] }[];
  uncovered_materials?: { material_id: string; title: string; kind: string; note: string }[];
  order_basis?: string;
  multi_material?: boolean;
  /** R42 B1 / R44 P2：过短条目中**走「跳过」**的那些（另一种去处是「已并入相邻单元」，
      两种都不计入未覆盖缺口；界面两处都写明，别让人以为过短一律被跳过） */
  skipped_short?: {
    count: number;
    labels: string[];
    min_chars?: number;
    items?: { material: string; material_id?: string; label: string; chars: number }[];
  };
  short_entry_min_chars?: number;
  /** R42 A3：未纳入清单（三种原因）+ 总上限状态（覆盖账与预算视图同源） */
  not_injected?: NotInjected[];
  inject_cap?: {
    configured: boolean;
    cap: number;
    used_chars: number;
    remaining: number;
    skipped_count: number;
    skipped_labels: string[];
    skipped_by_material?: { material_id: string; title: string; items: { label: string; chars: number; reason_zh: string }[] }[];
  };
  materials: { id: string; title: string; healthy: boolean; note: string; structure_kind: string; structure_note: string; role?: string; role_zh?: string }[];
  entries: CoverageEntry[];
  units: CoverageUnit[];
};

const COVERAGE_CLS: Record<string, string> = { 完整: "pass", 部分: "deferred", 未覆盖: "error" };

/** R39 §1：学科页的**就地账目**（材料吸纳/生成丢弃/模型调用/覆盖——最近 20 条）。 */
function SubjectLedgerInline({ subjectId }: { subjectId: string }) {
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null);
  useEffect(() => {
    api
      .get<{ entries: LedgerEntry[] }>(`/subjects/${subjectId}/ledger?limit=20`)
      .then((r) => setEntries(r.entries))
      .catch(() => setEntries([]));
  }, [subjectId]);
  return <LedgerAlerts entries={entries} subjectId={subjectId} compact title="本学科就地账目（最近 20 条）" />;
}

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
  const [candidate, setCandidate] = useState<{ units: Unit[]; source: string; problems: string[]; ok: boolean; source_materials?: string[]; material_usage?: { count: number; used_chars: number; dropped: string[]; truncated: boolean; batches?: number; inject_max_chars?: number; batch_chars?: number; blocked?: { title: string; note: string }[]; budget?: Record<string, unknown>; per_material?: unknown[]; not_injected?: unknown[]; order_basis?: string; context_valve?: { applied: boolean; limit_chars: number; context_tokens: number }; inject_cap?: { configured: boolean; cap: number; used_chars: number; remaining: number; skipped_count: number; skipped_labels: string[]; skipped_by_material?: { material_id: string; title: string; items: { label: string; chars: number; reason_zh: string }[] }[] } }; coverage?: { total: number; covered: number; uncovered: string[] } | null; ledger?: LedgerEntry[] } | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
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
  // R39 §1：最近一次"单元出稿"的就地账目（丢弃/降级/失败——界面必须能看见）
  const [lastUnitLedger, setLastUnitLedger] = useState<LedgerEntry[] | null>(null);

  const setMaterialRole = async (mid: string, role: string) => {
    setBusy(true);
    setErr("");
    try {
      await api.put(`/subjects/${id}/materials/${mid}/role`, { role });
      await loadMaterials();
      setMsg(role === "main" ? "已标为**主教材**（定顺序与范围）" : "已标为**补充材料**（只补细节与例题）");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

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
      const r = await api.upload<{ id: string; title: string; pages: number; filename: string; text_health?: { healthy: boolean; checked: boolean; note: string } }>(
        `/subjects/${id}/materials/upload-pdf`, fd
      );
      if (r.text_health && r.text_health.checked && !r.text_health.healthy) {
        setErr(`PDF 已入库「${r.title}」，但**没有可用文本层**：${r.text_health.note}`);
      } else {
        setMsg(`PDF 已解析入库「${r.title}」（${r.pages} 页；将作为教材真源参与大纲与出题）`);
      }
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
      try {
        setCoverage(await api.get<Coverage>(`/subjects/${id}/coverage`));
      } catch {
        setCoverage(null);
      }
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
      const r = await api.post<{ status: string; node_id: string; note?: string; coverage?: { status: string }; ledger?: LedgerEntry[] }>(`/subjects/${id}/units/${uid}/content`);
      setLastUnitLedger(r.ledger ?? []);
      if (r.status === "uncovered") {
        setErr(`单元 ${uid} 未出稿：${r.note || "教材未覆盖此单元"}`);
      } else if (r.status === "failed") {
        setErr(`单元 ${uid} 出稿失败：${r.note || "未通过内容校验"}`);
      } else {
        setMsg(`单元 ${uid} 内容：${r.status === "exists" ? "已在库（幂等）" : `已生成（source:auto${r.coverage ? ` · 教材覆盖：${r.coverage.status}` : ""}）`}`);
      }
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
            <span className="badge">{isPreset ? "预置学科（roadmap 治理）" : "自定义学科"}</span>
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
          引用材料（{materials.length}）：**教材＝权威真源**——大纲由书的目录派生、单元讲解与题目只从
          教材正文出（服务端逐字校验，教材里查不到的题会被丢弃、查不到的事实句会让整单元不出稿）。
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
                  {m.text_health?.checked && !m.text_health.healthy && (
                    <span className="badge error">无可用文本层</span>
                  )}
                  {m.filename && <div className="dim" style={{ fontSize: 12 }}>文件：{m.filename}</div>}
                  {m.url && <div className="dim" style={{ fontSize: 12, wordBreak: "break-all" }}>{m.url}</div>}
                  {m.text_health?.checked && !m.text_health.healthy && (
                    <div className="dim" style={{ fontSize: 12, color: "#b3261e" }}>{m.text_health.note}</div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center", whiteSpace: "nowrap" }}>
                  {/* R38 B2：材料角色（主教材定顺序与范围；未标注 → 按导入顺序并在覆盖账注明） */}
                  <select
                    value={m.role_explicit ? (m.role ?? "main") : ""}
                    disabled={busy}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      void setMaterialRole(m.id, e.target.value);
                    }}
                    title="主教材定顺序与范围；补充材料只补细节与例题"
                  >
                    <option value="">未标注（按导入顺序）</option>
                    <option value="main">主教材</option>
                    <option value="supplement">补充材料</option>
                  </select>
                  <button className="ghost" disabled={busy}
                          onClick={() => void deleteMaterial(m.id)}>
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* R38：材料注入预算（两个滑块 + 上一轮实际注入量/批次 + 未纳入清单） */}
        <MaterialBudgetPanel subjectId={id} onChanged={() => void load()} />

        {/* R39 §1：材料层的**就地**账目（材料吸纳/被挡下/未纳入 —— 界面必须能看见） */}
        <div style={{ marginTop: 8 }}>
          <SubjectLedgerInline subjectId={id} />
        </div>
      </div>

      {/* 起草 / 采纳（无大纲或重生成时） */}
      <div className="card">
        <h2>大纲起草与审阅</h2>
        {isPreset ? (
          <div className="dim">
            预置学科大纲按其课程蓝图（roadmap）派生治理（docs/14 §5）。当前版本：
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
            <div className="dim">
              起草仅生成候选（不落盘）；审阅后点“采纳”（大纲版本 revision+1）。无 LLM_KEY 时为离线启发式候选。
              {/* R42 B3：`count` 语义的 UI 说明（避免用户以为"我填了 20 却出 46"是 bug） */}
              {materials.length > 0 && (
                <>
                  <br />
                  ⚠️ <strong>「单元数」只在没有教材时生效</strong>：本学科有引用材料时，
                  **单元数由书的章节结构决定**（每个章/节至少 1 个单元），
                  所以实际单元数可能多于/少于你选的数量——这是**按书出稿**，不是 bug。
                </>
              )}
              {materials.length > 0
                ? `起草会**先读懂教材**（当前 ${materials.length} 份）：按章/节地图注入完整正文（默认不设预算，
                   书太大按章分批），由书的目录派生单元——每个章节都必须映射到单元，未映射的按教材目录补齐；
                   每个单元的依据（材料 + 章节标签）由服务端逐字校验。`
                : "（当前无引用材料：起草只按学科简介进行，会在覆盖账本里显式标注「本内容无教材依据」。）"}
            </div>
          </>
        )}
        {candidate && (
          <div className="card" style={{ borderColor: "#90caf9" }}>
            <h2>起草候选（{candidate.source === "ai" ? "AI" : "启发式（离线）"} · 未落盘）</h2>
            {candidate.problems?.length > 0 && (
              <div className="banner warn">候选提示：{candidate.problems.slice(0, 5).join("；")}</div>
            )}
            {candidate.coverage && (
              <div className={candidate.coverage.uncovered.length ? "banner warn" : "banner ok"}>
                教材覆盖：已覆盖节 {candidate.coverage.covered} / {candidate.coverage.total}
                {candidate.coverage.uncovered.length > 0
                  ? `；未覆盖：${candidate.coverage.uncovered.join("、")}`
                  : "（未覆盖清单为空）"}
              </div>
            )}
            {/* R38 A1 必显 + **R42 A1/A4**：本轮实际注入总量/批次数 + 两个滑块的生效值与来源 +
                因总上限未纳入的章节数（就地可见，可展开） */}
            {candidate.material_usage && candidate.material_usage.count > 0 && (
              <div className="dim" style={{ fontSize: 12, margin: "4px 0" }}>
                本轮材料注入：共 <strong>{candidate.material_usage.used_chars.toLocaleString("zh-CN")}</strong> 字 ·
                分 <strong>{candidate.material_usage.batches ?? 0}</strong> 批 ·
                单次预算 {candidate.material_usage.batch_chars === 0 ? "不限" : `${(candidate.material_usage.batch_chars ?? 0).toLocaleString("zh-CN")} 字符`} ·
                总上限 {candidate.material_usage.inject_max_chars === 0 ? "不限" : `${(candidate.material_usage.inject_max_chars ?? 0).toLocaleString("zh-CN")} 字符`} ·
                顺序依据：{candidate.material_usage.order_basis ?? "导入顺序"}
                {candidate.material_usage.context_valve?.applied && (
                  <> · 安全阀：本书较大，已自动分批（不截断、不漏章节）</>
                )}
                {!!candidate.material_usage.inject_cap?.skipped_count && (
                  <>
                    <br />
                    <span style={{ color: "#b3261e" }}>
                      因「总注入上限」已用完，本教材有{" "}
                      <strong>{candidate.material_usage.inject_cap.skipped_count}</strong> 章/节**未纳入**
                      （已注入 {(candidate.material_usage.inject_cap.used_chars ?? 0).toLocaleString("zh-CN")} 字；
                      按章/节边界停止，未截断）：
                      {(candidate.material_usage.inject_cap.skipped_labels ?? []).join("、")}
                    </span>
                  </>
                )}
              </div>
            )}
            {/* R39 §1：本次起草的**就地**账目（驳回重生成/降级/材料未纳入…） */}
            <LedgerAlerts entries={candidate.ledger} subjectId={id} title="本次起草记录（一切显性）" compact />
            {(candidate as any).notes?.length > 0 && (
              <div className="dim" style={{ fontSize: 12 }}>{(candidate as any).notes.join("；")}</div>
            )}
            {candidate.units.map((u, i) => (
              <div key={u.id} style={{ padding: "4px 0", borderBottom: "1px solid #eef2f6" }}>
                <strong>{i + 1}. {u.title}</strong>{" "}
                <span className="badge">{u.group}</span>
                {u.prereqs.length > 0 && <span className="dim"> 前置：{u.prereqs.join("、")}</span>}
                {u.materials && u.materials.length > 0 && (
                  <div className="dim" style={{ fontSize: 12 }}>
                    依据材料：{u.materials.map((r) => `《${r.title}》${r.section ? " · " + r.section : ""}`).join("；")}
                  </div>
                )}
                <div className="chip">{u.concept_tags?.join(" · ")}</div>
              </div>
            ))}
            {materialTitles(candidate.source_materials, materials).length > 0 && (
              <div className="dim" style={{ marginTop: 6 }}>
                本候选依据的材料：{materialTitles(candidate.source_materials, materials).map((t) => `《${t}》`).join("、")}
              </div>
            )}
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
          {materialTitles(outline.source_materials, materials).length > 0 && (
            <div className="banner ok" style={{ margin: "6px 0" }}>
              本大纲依据的材料（{materialTitles(outline.source_materials, materials).length}）：
              {materialTitles(outline.source_materials, materials).map((t) => `《${t}》`).join("、")}
            </div>
          )}
          {coverage && coverage.has_materials && (
            <div className="card" style={{ borderColor: coverage.uncovered.length ? "#e6a23c" : "#90caf9", margin: "8px 0" }}>
              <h2 style={{ margin: "0 0 4px" }}>
                教材覆盖账本 · 已覆盖节 {coverage.covered} / {coverage.total}
                {typeof coverage.page_covered === "number" && coverage.page_total ? (
                  <span className="dim" style={{ fontSize: 13 }}>
                    {" "}（页级：{coverage.page_covered}/{coverage.page_total} 页已有对应单元，可下钻）
                  </span>
                ) : null}
              </h2>
              <div className="dim" style={{ fontSize: 12 }}>
                教材结构：
                {coverage.materials.map((m) => `${m.title}（${m.structure_kind}：${m.structure_note}）`).join("；")}
                {coverage.multi_material ? ` · 共 ${coverage.materials.length} 份材料（已合并成一份章节地图）` : ""}
                {coverage.order_basis ? ` · 顺序依据：${coverage.order_basis}` : ""}
              </div>

              {/* R38 B1：**按材料分组**的覆盖统计（跨全部材料；未覆盖清单按材料分组） */}
              {coverage.by_material && coverage.by_material.length > 0 && (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 6 }}>
                  <thead>
                    <tr className="dim">
                      <th style={{ textAlign: "left" }}>材料</th>
                      <th>角色</th>
                      <th>已覆盖节 / 总节</th>
                      <th>字数</th>
                      <th>页数</th>
                      <th>因总上限未纳入</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coverage.by_material.map((b) => (
                      <tr key={b.material_id} style={{ borderBottom: "1px solid #eef2f6" }}>
                        <td style={{ padding: "3px" }}>{b.title}</td>
                        <td style={{ padding: "3px" }}>
                          {b.role_zh}
                          {b.role_explicit ? "" : "（未标注）"}
                        </td>
                        <td style={{ padding: "3px", textAlign: "center" }}>
                          <span className={b.covered === b.total ? "badge pass" : "badge deferred"}>
                            {b.covered} / {b.total}
                          </span>
                        </td>
                        <td style={{ padding: "3px", textAlign: "center" }}>{b.chars.toLocaleString("zh-CN")}</td>
                        <td style={{ padding: "3px", textAlign: "center" }}>{b.pages}</td>
                        <td style={{ padding: "3px", textAlign: "center" }}>
                          {b.cap_skipped_count
                            ? <span className="badge deferred" title={(b.cap_skipped ?? []).join("、")}>
                                {b.cap_skipped_count} 章
                              </span>
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {/* R42 A3：因「总注入上限」未纳入（覆盖账如实降 —— 不许"没喂却算覆盖"） */}
              {!!coverage.inject_cap?.configured && (coverage.inject_cap.skipped_count > 0) && (
                <div className="banner warn" style={{ marginTop: 6 }}>
                  因「总注入上限」{(coverage.inject_cap.cap ?? 0).toLocaleString("zh-CN")} 字已用完，
                  本教材有 <strong>{coverage.inject_cap.skipped_count}</strong> 章/节**未纳入**（覆盖账已如实降）：
                  <ul className="plain" style={{ margin: "4px 0 0 12px" }}>
                    {(coverage.inject_cap.skipped_by_material ?? []).map((g) => (
                      <li key={g.material_id}>
                        《{g.title}》：
                        {g.items.map((it) => `${it.label}（${it.chars.toLocaleString("zh-CN")} 字）`).join("、")}
                      </li>
                    ))}
                  </ul>
                  <div className="dim" style={{ fontSize: 12 }}>
                    这些章节**没有被喂给模型**，因此**不算覆盖**；调大「总注入上限」或设为 0（不限）
                    后重新起草即可纳入（想更省又不想丢章节 → 调小「单次调用预算」）。
                  </div>
                </div>
              )}

              {coverage.uncovered.length === 0 ? (
                <div className="badge pass">未覆盖清单为空：书的每个章/节都有对应单元</div>
              ) : (
                <>
                  {/* R38 B1：未覆盖清单**按材料分组**显式列出（不是只在 prompt 尾部提一句） */}
                  {coverage.uncovered_by_material && coverage.uncovered_by_material.length > 0 ? (
                    coverage.uncovered_by_material.map((g) => (
                      <div className="banner warn" key={g.material_id} style={{ marginTop: 4 }}>
                        《{g.title}》（{g.role_zh}）未覆盖 {g.items.length} 条：
                        {g.items.map((x) => `${x.label}（${x.chars.toLocaleString("zh-CN")} 字）`).join("、")}
                      </div>
                    ))
                  ) : (
                    <div className="banner warn">
                      未覆盖清单（{coverage.uncovered.length}）：{coverage.uncovered.join("、")}
                    </div>
                  )}
                  <div className="dim" style={{ fontSize: 12 }}>
                    教材有而内容没覆盖的部分**不会被编造**，请补充/调整单元后重新生成大纲；
                    这些未覆盖项也已写入总账（
                    <Link to={`/ledger?subject_id=${id}&category=coverage`}>就地看着</Link>）。
                  </div>
                </>
              )}
              {/* R42 A3：未纳入清单（三种原因都列出来——健康度不合格 / 未进批次 / 总注入上限） */}
              {coverage.not_injected && coverage.not_injected.length > 0 && (
                <details style={{ marginTop: 6 }}>
                  <summary className="dim">
                    未纳入注入清单（{coverage.not_injected.length}，含原因）
                  </summary>
                  <ul className="plain" style={{ margin: "4px 0 0 12px", fontSize: 12 }}>
                    {coverage.not_injected.map((x, i) => (
                      <li key={`${x.material_id ?? x.material}-${x.label}-${i}`}>
                        {x.material} · {x.label}
                        {x.reason_zh || x.reason ? ` —— ${x.reason_zh ?? x.reason}` : ""}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {/* R42 B1 + R44 P2：过短条目**两种去处都写明**（别让人以为"过短＝一律被跳过"）——
                  ① 已并入相邻单元（留在该单元依据材料里）；② 已跳过（过短），未成为单元（下列即此类）。
                  两种去处都不计入未覆盖缺口，且都在总账留了中文原因。 */}
              {!!coverage.skipped_short?.count && (
                <details style={{ marginTop: 6 }}>
                  <summary className="dim">
                    过短条目（{coverage.skipped_short.count} 条走「跳过」；另有若干条已「并入相邻单元」）
                    —— 两种去处都不计入未覆盖缺口
                  </summary>
                  <div className="dim" style={{ fontSize: 12, margin: "4px 0 0 12px" }}>
                    过短条目（&lt; {coverage.skipped_short?.min_chars} 字）有两种去处：
                    <strong>① 已并入相邻单元</strong>——它留在了那个单元的依据材料里
                    （在下方"逐单元覆盖状态"里显示"并入过短条目 N"）；
                    <strong>② 已跳过（过短），未成为单元</strong>——下列即此类的全部。
                    两种去处都在总账留了中文原因（
                    <Link to={`/ledger?subject_id=${id}&category=other`}>就地看着</Link>）。
                  </div>
                  <ul className="plain" style={{ margin: "4px 0 0 12px", fontSize: 12 }}>
                    {(coverage.skipped_short.items ?? []).map((x, i) => (
                      <li key={`${x.material_id ?? x.material}-${x.label}-${i}`}>
                        {x.material} · {x.label}（{x.chars} 字 &lt; {coverage.skipped_short?.min_chars} 字）
                        —— 已跳过（过短），未成为单元
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {coverage.uncovered_materials && coverage.uncovered_materials.length > 0 && (
                <div className="banner error" style={{ marginTop: 4 }}>
                  整份未纳入的材料（{coverage.uncovered_materials.length}）：
                  {coverage.uncovered_materials.map((m) => `${m.title}（${m.kind}）`).join("、")}
                </div>
              )}
              <details style={{ marginTop: 6 }}>
                <summary className="dim">逐单元覆盖状态（{coverage.units.length}）</summary>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <tbody>
                    {coverage.units.map((u) => (
                      <tr key={u.unit_id} style={{ borderBottom: "1px solid #eef2f6" }}>
                        <td style={{ padding: "4px", width: 120 }} className="dim">{u.unit_id}</td>
                        <td style={{ padding: "4px" }}>{u.title}</td>
                        <td style={{ padding: "4px", width: 90 }}>
                          <span className={`badge ${COVERAGE_CLS[u.status] ?? ""}`}>{u.status}</span>
                        </td>
                        <td style={{ padding: "4px" }} className="dim">
                          {u.sources.length > 0
                            ? u.sources.map((s) => `${s.title} · ${s.section}`).join("；")
                            : "无教材依据"}
                          {u.grounded_facts > 0 && ` · ${u.grounded_facts} 条事实句逐字出自教材`}
                          {u.dropped_exercises > 0 && ` · 丢弃 ${u.dropped_exercises} 题`}
                          {/* R42 B4：章内该节级依据（比"整章"更精确；取不到就不显示，不编造） */}
                          {u.basis_section && (
                            <div style={{ fontSize: 12 }}>
                              📍 依据（章内该节）：{u.basis_section}
                              {u.basis_quote && <span title={u.basis_quote}> · 引文：{u.basis_quote.slice(0, 60)}…</span>}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </div>
          )}
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
                            {(() => {
                              const c = coverage?.units.find((x) => x.unit_id === u.id);
                              if (!c || c.status === "未知") return null;
                              return (
                                <span className={`badge ${COVERAGE_CLS[c.status] ?? ""}`}
                                      title={c.note}>
                                  教材：{c.status}
                                </span>
                              );
                            })()}
                            {/* R42 B2：难度被"非降钳制"抬高 —— 大纲页单元行**可见**（不只在库里） */}
                            {u.meta?.difficulty_raised && (
                              <span className="badge deferred"
                                    title={u.meta.difficulty_raised.reason_zh}>
                                难度被抬高 {u.meta.difficulty_raised.from}→{u.meta.difficulty_raised.to}
                              </span>
                            )}
                            {/* R42 B1：过短条目已并入本单元（覆盖账可解释"它去哪了"） */}
                            {!!u.meta?.absorbed_short?.length && (
                              <span className="badge"
                                    title={u.meta.absorbed_short.map((x) => `${x.label}（${x.chars} 字）`).join("、")}>
                                并入过短条目 {u.meta.absorbed_short.length}
                              </span>
                            )}
                            {u.materials && u.materials.length > 0 && (
                              <div className="dim" style={{ fontSize: 12 }}>
                                依据：{u.materials.map((r) => `《${r.title}》${r.section ? " · " + r.section : ""}`).join("；")}
                              </div>
                            )}
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
          {/* R39 §1：单元出稿的**就地**账目（题/事实句被丢弃、降级启发式、整单元未出稿…） */}
          <LedgerAlerts entries={lastUnitLedger} subjectId={id} title="最近一次单元出稿记录" compact />
        </div>
      )}
    </div>
  );
}
