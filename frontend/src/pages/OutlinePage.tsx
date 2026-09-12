import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import MaterialBudgetPanel, { charsText } from "../components/MaterialBudgetPanel";
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
  // R56 第 3 步：来源模式（all_ai = 图片为主的教材 / 全程交给 AI 判断）
  mode?: string;
  mode_zh?: string;
  page_count?: number;
  // R55 A：教材体检（认不出比例 / 拆字比例 / 公式符号 / 图片数 → 好·一般·差 + 人话）
  text_health?: {
    pages: number; chars: number; healthy: boolean; checked: boolean; note: string;
    grade?: string; summary_zh?: string; fixed?: boolean; raw_file?: string;
    extract?: {
      unrecognized_ratio: number; broken_space_ratio: number; formula_symbols: number;
      images: number; image_pages: number;
    };
  };
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
  /** R54 C：内容状态（与"能不能进学习会话"同源） */
  has_content?: boolean;
  usable?: boolean;
  content_reason_zh?: string;
  exercise_count?: number;
  taught_fact_count?: number;
  /** R55 B：这一节内容基本都在图里（系统读不到图）→ 没出内容（原因不同、下一步不同） */
  figure_unavailable?: boolean;
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
  /** R55 A：这份材料读起来好不好（好/一般/差 + 一句人话） */
  health_grade?: string;
  health_summary_zh?: string;
  image_count?: number;
  /** R55 B：哪几章/节在引用图（系统读不到图；不会被当作依据） */
  figure_unavailable?: string[];
  figure_unavailable_count?: number;
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
  // R56 第 3 步：当前学科是不是"图片为主的教材"（界面上要一直能看出来）
  const [modeLabel, setModeLabel] = useState("");
  const [modeEntry, setModeEntry] = useState<{
    vision_ready: boolean; vision_note_zh: string; vision_model: string;
    pdf_render_ready?: boolean; pdf_render_note_zh?: string;
    pdf_render_options?: { width: number; format: string; dpi_cap: number };
    entry_zh: {
      label: string; what_zh: string; pros_zh: string; costs_zh: string[];
      not_better_zh: string; need_images_zh: string;
    };
  } | null>(null);
  // R57：PDF 页范围（如 1-20；留空＝整本）+ 起草大纲的忙碌状态
  const [modePages, setModePages] = useState("");
  const [draftingMode, setDraftingMode] = useState(false);
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

  // R55 C4：对已有材料重新做一次"抽取修正"（幂等；不动原始文件与已生成内容）
  const reparseMaterial = async (mid: string) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{ title: string; changed: boolean; text_health?: { summary_zh?: string } }>(
        `/subjects/${id}/materials/${mid}/reparse`, {}
      );
      setMsg(r.changed
        ? `「${r.title}」已重新整理：${r.text_health?.summary_zh || ""}`
        : `「${r.title}」再整理一次也没有变化（已经是最干净的了）。`);
      await loadMaterials();
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
      const r = await api.upload<{ id: string; title: string; pages: number; filename: string; text_health?: { healthy: boolean; checked: boolean; note: string; grade?: string; summary_zh?: string } }>(
        `/subjects/${id}/materials/upload-pdf`, fd
      );
      if (r.text_health && r.text_health.checked && !r.text_health.healthy) {
        setErr(`PDF 已入库「${r.title}」，但**没有可用文本层**：${r.text_health.note}`);
      } else {
        // R55 A：导入那一刻就把"这份材料好不好用"说清楚（人话，不堆数字）
        setMsg(`PDF 已入库「${r.title}」（${r.pages} 页）。体检结论：${r.text_health?.summary_zh || "可以直接用。"}`);
      }
      if (inp) inp.value = "";
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  // R56 第 3 步：图示教材模式（页面图片 → 全程交给 AI 判断）
  const pagesFileRef = useRef<HTMLInputElement>(null);

  const loadModeEntry = async () => {
    try {
      const r = await api.get<{
        mode: string; mode_label_zh: string; vision_ready: boolean; vision_note_zh: string;
        vision_model: string; pdf_render_ready?: boolean; pdf_render_note_zh?: string;
        pdf_render_options?: { width: number; format: string; dpi_cap: number };
        entry_zh: { label: string; what_zh: string; pros_zh: string; costs_zh: string[];
                    not_better_zh: string; need_images_zh: string };
      }>(`/subjects/${id}/mode`);
      setModeEntry(r);
      setModeLabel(r.mode_label_zh || "");
    } catch {
      setModeEntry(null);
    }
  };

  // R57 任务 B-①：本模式一键起草大纲（走本模式提示词；依据是页/图号）
  // R58 任务 C：按需重读某几页（后端 /read-pages 已可用，这里补界面入口）
  const [rereadPages, setRereadPages] = useState("");

  const rereadMaterialPages = async (mid: string, title: string, spec?: string) => {
    const pagesSpec = (spec ?? rereadPages).trim();
    if (!pagesSpec) {
      setErr("请先填要重读的页（例如 3 或 3-5；页号从 1 开始数）");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{
        title: string; reread: string[]; count: number; unreadable?: string[];
        skipped?: string[]; note_zh?: string; reason_zh?: string;
      }>(`/subjects/${id}/materials/${mid}/read-pages`, { pages: pagesSpec });
      const skipMsg = r.skipped?.length
        ? `另有 ${r.skipped.length} 页标签里没有页号，已跳过：${r.skipped.join("、")}（这几页要自己填页号重读）。`
        : "";
      if (!r.count) {
        // 没读不出来的页 → 后端**不调用模型**，这里照实说（别让人以为"点了没反应"）；
        // 全是"标签读不出页号"的旧页时后端也会在这句话里如实写明跳过了哪几页
        setMsg(`「${title}」：${r.note_zh || r.reason_zh || "没有需要重读的页"}`);
      } else {
        setMsg(`「${title}」已重新读：${r.reread.join("、")}（共 ${r.count} 页）。` +
          (r.unreadable?.length ? `还是读不出来：${r.unreadable.join("、")}。` : "") +
          skipMsg +
          "其它页的记录没有动；这一步同样要问模型，也会花钱。");
      }
      setRereadPages("");
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const draftModeOutline = async () => {
    setDraftingMode(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{
        units: Unit[]; note: string; absorbed_pages: string[]; page_count: number;
      }>(`/subjects/${id}/mode/outline/draft`, { brief: draftBrief, count: draftCount });
      setCandidate({ units: r.units, source: "all_ai", problems: [], ok: true } as never);
      setMsg(`${r.note}（可下面预览后采纳）` +
        (r.absorbed_pages.length
          ? `；模型没提到的 ${r.absorbed_pages.length} 页已并进最后一个单元：${r.absorbed_pages.slice(0, 8).join("、")}`
          : ""));
    } catch (e) {
      setErr(String(e));
    } finally {
      setDraftingMode(false);
    }
  };

  const uploadPages = async () => {
    const inp = pagesFileRef.current;
    const list = Array.from(inp?.files ?? []);
    if (!list.length) {
      setErr("请先选择教材的页面图片或 PDF（PDF 会自动按页转成图片；也可以一次选多张图片）");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const fd = new FormData();
      if (matTitle.trim()) fd.append("title", matTitle.trim());
      if (modePages.trim()) fd.append("pages", modePages.trim());
      for (const f of list) fd.append("files", f);
      const r = await api.upload<{
        id: string; title: string; page_count: number; unreadable: string[]; note_zh: string;
        render?: { source?: string; pages?: number[]; width?: number; dpi?: number };
      }>(`/subjects/${id}/materials/upload-pages`, fd);
      const fromPdf = r.render?.source === "pdf_render";
      setMsg(`「${r.title}」已按「图片为主的教材」入库：${r.note_zh}。` +
        (fromPdf
          ? `（把 PDF 的第 ${(r.render?.pages ?? []).slice(0, 6).join("、")} 页转成图片后读的，`
            + `出图宽 ${r.render?.width ?? "—"} px；页面图片本身没有存进内容目录）`
          : "") +
        (r.unreadable.length ? `读不出来的页：${r.unreadable.join("、")}（已如实标注，不会当成内容用）` : ""));
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
      const r = await api.get<{ materials: MaterialItem[]; mode?: string; mode_label_zh?: string }>(
        `/subjects/${id}/materials`
      );
      setMaterials(r.materials);
      setModeLabel(r.mode_label_zh || "");
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
    void loadModeEntry();
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
        setMsg("大纲已重新生成（版本号 +1）");
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
        setErr(`「${uid}」还没出内容：${r.note || "教材里没有找到对应这一单元的内容"}`);
      } else if (r.status === "failed") {
        setErr(`「${uid}」出内容失败：${r.note || "内容没有通过检查"}`);
      } else {
        setMsg(`「${uid}」${r.status === "exists" ? "之前已经生成过，不用重复生成" : "已生成"}${r.coverage ? ` · 教材依据：${r.coverage.status}` : ""}`);
      }
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const resetProgress = async () => {
    if (!window.confirm(`确认清空「${subject?.label}」的学习进度？已掌握的内容会被重置。`)) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.post<{ nodes_reset: number }>(`/subjects/${id}/progress/reset`, { mode: "all" });
      setMsg(`已清空学习进度（${r.nodes_reset} 个知识点回到未学）`);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  // **R54 C**：单元有没有内容——与覆盖账**同源**（后端同一实现）。点"还没内容"的不进空会话，
  // 就地提示 + 一键生成。
  const contentOf = (uid: string): CoverageUnit | undefined =>
    (coverage?.units ?? []).find((x) => x.unit_id === uid);
  const [hintUnit, setHintUnit] = useState<string>("");

  const learnUnit = async (uid: string) => {
    const c = contentOf(uid);
    if (c && c.usable === false) {
      // 还没内容/内容不可用 → 不把人带进空会话；就地说明 + 给生成入口
      setHintUnit(uid);
      setErr(c.content_reason_zh || "这个单元还没有内容，先生成内容才能开始学。");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const r = await api.post<{ session: { id: string }; step?: string; payload?: { content_missing?: { reason_zh?: string; can_generate?: boolean } } }>(
        "/session/start", { node_id: uid });
      // R54 C：单元还没有内容 → **不进空会话**；就地提示 + 一键生成
      if (r.step === "content_missing" || !r.session?.id) {
        const info = r.payload?.content_missing;
        setHintUnit(uid);
        setErr(info?.reason_zh || "这个单元还没有内容，先生成内容才能开始学。");
        return;
      }
      nav(`/session/${r.session.id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  // **R54 B**：丢弃账目上的"重新生成这个单元"（就地可点，不再只写"可通过重试补救"）
  const regenerateFromLedger = async (action: { unit_id?: string }) => {
    if (!action?.unit_id) return;
    setHintUnit(action.unit_id);
    await genContent(action.unit_id);
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
            <span className="badge">{isPreset ? "系统自带的学科" : "自定义学科"}</span>
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
          教材（{materials.length} 份）：**一切以教材为准**——大纲按书的目录排，讲解和题目只用教材里的原话，
          服务端会逐字核对：教材里查不到的题不会用，查不到依据的内容整个单元都不会生成。
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

        {/* R56 第 3 步：图示教材模式（页面图片 → 全程交给 AI 判断）——
            导入前先把"代价"写在看得见的地方（没有独立核对 / 失败更隐蔽 / 更贵） */}
        <div style={{ marginTop: 10, padding: 10, border: "1px solid #e6d9a8", borderRadius: 8,
                      background: "#fffdf5" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <strong>{modeEntry?.entry_zh.label ?? "图片为主的教材（全程交给 AI 判断）"}</strong>
            {modeLabel && <span className="badge deferred">当前学科：{modeLabel}</span>}
            {modeEntry && !modeEntry.vision_ready && (
              <span className="badge error">还没配能读图的模型</span>
            )}
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
            {modeEntry?.entry_zh.what_zh ?? "把教材每页的图片交给 AI，由它自己读、自己出题、自己判、自己评。"}
          </div>
          <ul className="plain" style={{ fontSize: 12, margin: "4px 0 4px 16px" }}>
            {(modeEntry?.entry_zh.costs_zh ?? [
              "没有独立的第二次核对：判对错、评分都是模型的判断，程序不替你复核。",
              "失败了不容易发现：这类模型的错法更像「说得很有把握但其实不对」。",
              "更贵：每一步都要问模型。",
            ]).map((c) => (
              <li key={c}>{c.replace(/\*\*/g, "")}</li>
            ))}
          </ul>
          <div className="dim" style={{ fontSize: 12 }}>
            {modeEntry?.entry_zh.pros_zh ?? "长处是能看图、能读公式与版式；但没法逐字核对引用。"}
            <br />
            {modeEntry?.entry_zh.not_better_zh ?? "它不比文字教材模式更可靠。"}
            {" "}{modeEntry?.entry_zh.need_images_zh ?? "要的是页面图片（PNG/JPEG/WebP）。"}
          </div>
          {modeEntry && !modeEntry.vision_ready && (
            <div className="banner warn" style={{ marginTop: 6 }}>
              {modeEntry.vision_note_zh}
            </div>
          )}
          {modeEntry && modeEntry.pdf_render_ready === false && (
            <div className="banner warn" style={{ marginTop: 6 }}>
              这台机器上还不能自动把 PDF 转成页面图片。{modeEntry.pdf_render_note_zh}
            </div>
          )}
          <div className="input-row" style={{ gap: 8, marginTop: 6 }}>
            <input type="file" multiple
                   accept=".pdf,application/pdf,image/png,image/jpeg,image/webp,image/gif"
                   ref={pagesFileRef} disabled={busy} style={{ flex: 1 }} />
            <button className="primary" disabled={busy || !modeEntry?.vision_ready}
                    onClick={() => void uploadPages()}>
              导入页面图片 / PDF（全 AI 模式）
            </button>
          </div>
          <div className="input-row" style={{ gap: 8, marginTop: 4, alignItems: "center" }}>
            <input placeholder="PDF 页范围（可选，如 1-20；留空＝整本）" value={modePages}
                   onChange={(e) => setModePages(e.target.value)}
                   style={{ width: 260, padding: 6, borderRadius: 8, border: "1px solid #c5cdd6" }} />
            <button className="ghost" disabled={busy || draftingMode || !modeEntry?.vision_ready}
                    onClick={() => void draftModeOutline()}>
              {draftingMode ? "正在按页面记录排大纲…" : "一键起草大纲（本模式）"}
            </button>
          </div>
          <div className="dim" style={{ fontSize: 12 }}>
            可以**直接选 PDF**：装了渲染组件就**按页转成图片**再交给模型（一页一张、页号留痕；
            出图宽 {modeEntry?.pdf_render_options?.width ?? 1024} px、格式
            {" "}{modeEntry?.pdf_render_options?.format ?? "jpeg"}、DPI 上限
            {" "}{modeEntry?.pdf_render_options?.dpi_cap ?? 200}；参数可在配置里改）；
            **页面图片不会存进内容目录**（避免仓库膨胀），只留"读到了什么"。
            一次最多 60 页；读不出来的页会**如实标注**、不会被当成内容用。
            {modeEntry?.vision_model ? `读图用的模型：${modeEntry.vision_model}。` : ""}
          </div>
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
                  {/* R56：材料的来源模式（界面一直能看出"这条材料走的是哪条路"） */}
                  {m.mode === "all_ai" && (
                    <span className="badge deferred" title="判对错与评分都由模型给出，程序不替你复核">
                      图片为主 · 全程 AI{m.page_count ? ` · ${m.page_count} 页` : ""}
                    </span>
                  )}{" "}
                  <span className="dim">{m.source}</span>
                  {m.text_health?.checked && !m.text_health.healthy && (
                    <span className="badge error">无可用文本层</span>
                  )}
                  {m.filename && <div className="dim" style={{ fontSize: 12 }}>文件：{m.filename}</div>}
                  {m.url && <div className="dim" style={{ fontSize: 12, wordBreak: "break-all" }}>{m.url}</div>}
                  {/* R55 A：教材体检结论（人话；好/一般/差 + "所以会怎样"） */}
                  {m.text_health?.checked && m.text_health.healthy && m.text_health.summary_zh && (
                    <div className="dim" style={{ fontSize: 12 }}>
                      <span className={`badge ${m.text_health.grade === "好" ? "pass" : "deferred"}`}>
                        体检：{m.text_health.grade || "—"}
                      </span>{" "}
                      {m.text_health.summary_zh}
                      {m.text_health.fixed && <>{" "}（已做抽取修正，原始文本留档：{m.text_health.raw_file || "有"}）</>}
                    </div>
                  )}
                  {m.text_health?.checked && !m.text_health.healthy && (
                    <div className="dim" style={{ fontSize: 12, color: "#b3261e" }}>{m.text_health.note}</div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center", whiteSpace: "nowrap" }}>
                  {/* R55 C4：重新做一次抽取修正（幂等；不动原始文件与已生成内容） */}
                  {m.kind === "pdf" && (
                    <button className="ghost" disabled={busy} onClick={() => void reparseMaterial(m.id)}
                            title="重新整理这份 PDF 的文字（修掉认不出的字和被空格拆开的字）；可反复点，结果一致">
                      重新整理文字
                    </button>
                  )}
                  {/* R58 C：按需重读某几页（图示教材模式；只重读你填的那几页，其它页不动） */}
                  {m.mode === "all_ai" && (
                    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                      <input value={rereadPages} onChange={(e) => setRereadPages(e.target.value)}
                             placeholder="重读第几页（如 3 或 3-5）"
                             style={{ width: 150, padding: 4, borderRadius: 6, border: "1px solid #c5cdd6" }}
                             title="页号从 1 开始数；可以写 3 或 3-5（按页范围重读）" />
                      <button className="ghost" disabled={busy}
                              onClick={() => void rereadMaterialPages(m.id, m.title)}
                              title="只把这几页重新读一遍（会再问一次模型，所以会花钱）；其它页的记录不动">
                        重读这几页
                      </button>
                      {/* R59：一键把**读不出来的页**再读一遍（没有就直说，不打电话给模型） */}
                      <button className="ghost" disabled={busy}
                              onClick={() => void rereadMaterialPages(m.id, m.title, "unreadable")}
                              title="把这份材料里读不出来的页一起再读一遍（没有读不出来的页就不会调用模型）">
                        把读不出来的页再读一遍
                      </button>
                    </span>
                  )}
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
            系统自带学科的大纲按官方课程安排生成。当前：第 {outline?.revision ?? "-"} 版 ·{" "}
            {outline?.units?.length ?? 0} 个单元。
            <button style={{ marginLeft: 10 }} disabled={busy} onClick={() => draft(true)}>
              按课程安排重新生成
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
                {outline ? "重新起草（会丢掉当前这份）" : "让 AI 起草大纲"}
              </button>
            </div>
            <div className="dim">
              起草只是先给一份候选，不会直接覆盖；你看过之后点「采纳」才会生效（版本号 +1）。
              没有配 AI 时会用内置的简单办法先排一版。
              {/* R42 B3：`count` 语义的 UI 说明（避免用户以为"我填了 20 却出 46"是 bug） */}
              {materials.length > 0 && (
                <>
                  <br />
                  ⚠️ <strong>「单元数」只在没有教材时有用</strong>：有教材时，
                  **单元数是按书的章节来的**（每章/每节至少一个单元），
                  所以实际会多于或少于你选的数量——这是**照着书排**，不是出错。
                </>
              )}
              {materials.length > 0
                ? `起草时会先读教材（当前 ${materials.length} 份），完全按书的章节来排单元：每个章节都会对应到单元，没人用的章节按目录补齐。`
                : "（还没有教材：只能按你写的简介排，生成的内容会标注「没有教材依据」。）"}
            </div>
          </>
        )}
        {candidate && (
          <div className="card" style={{ borderColor: "#90caf9" }}>
            <h2>起草候选（{candidate.source === "ai" ? "AI 生成" : "内置办法生成"}，还没生效）</h2>
            {candidate.problems?.length > 0 && (
              <div className="banner warn">需要留意：{candidate.problems.slice(0, 5).join("；")}</div>
            )}
            {candidate.coverage && (
              <div className={candidate.coverage.uncovered.length ? "banner warn" : "banner ok"}>
                章节进度：已有内容 {candidate.coverage.covered} / {candidate.coverage.total} 节
                {candidate.coverage.uncovered.length > 0
                  ? `；还没有内容：${candidate.coverage.uncovered.join("、")}`
                  : "（每一节都有内容）"}
              </div>
            )}
            {/* R38 A1 必显 + **R42 A1/A4**：本轮实际注入总量/批次数 + 两个滑块的生效值与来源 +
                因总上限未纳入的章节数（就地可见，可展开） */}
            {candidate.material_usage && candidate.material_usage.count > 0 && (
              <div className="dim" style={{ fontSize: 12, margin: "4px 0" }}>
                这次读书：共 <strong>{charsText(candidate.material_usage.used_chars)}</strong> ·
                分 <strong>{candidate.material_usage.batches ?? 0}</strong> 次读完 ·
                每次读多少 {candidate.material_usage.batch_chars === 0 ? "不限" : charsText(candidate.material_usage.batch_chars ?? 0)} ·
                最多读多少 {candidate.material_usage.inject_max_chars === 0 ? "不限" : charsText(candidate.material_usage.inject_max_chars ?? 0)} ·
                阅读顺序：{candidate.material_usage.order_basis ?? "导入顺序"}
                {candidate.material_usage.context_valve?.applied && (
                  <> · 书比较大，已自动分次读（不截掉正文、不漏章节）</>
                )}
                {!!candidate.material_usage.inject_cap?.skipped_count && (
                  <>
                    <br />
                    <span style={{ color: "#b3261e" }}>
                      总量已经读完，还有{" "}
                      <strong>{candidate.material_usage.inject_cap.skipped_count}</strong> 章/节**没读**
                      （已读 {charsText(candidate.material_usage.inject_cap.used_chars ?? 0)}；
                      到上限时整章停下，不会读一半）：
                      {(candidate.material_usage.inject_cap.skipped_labels ?? []).join("、")}
                    </span>
                  </>
                )}
              </div>
            )}
            {/* R39 §1：本次起草的**就地**记录（驳回重生成/降级/材料未纳入…） */}
            <LedgerAlerts entries={candidate.ledger} subjectId={id} title="本次起草记录" compact />
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
              大纲 第 {outline.revision} 版 · {outline.status === "active" ? "使用中" : outline.status === "draft" ? "草稿" : outline.status} ·{" "}
              {outline.source === "ai" ? "由 AI 生成" : "手工/系统生成"} · 格式版本 {outline.schema_version}
            </h2>
            {progress && (
              <span className="badge pass">已掌握概念 {progress.concepts_mastered}</span>
            )}
            {!isPreset && (
              <span>
                <button className="ghost" disabled={busy} onClick={resetProgress}>清空本学科学习进度</button>
              </span>
            )}
          </div>
          {outline.note && <div className="dim">{outline.note}</div>}
          {materialTitles(outline.source_materials, materials).length > 0 && (
            <div className="banner ok" style={{ margin: "6px 0" }}>
              这份大纲依据的教材（{materialTitles(outline.source_materials, materials).length} 份）：
              {materialTitles(outline.source_materials, materials).map((t) => `《${t}》`).join("、")}
            </div>
          )}
          {coverage && coverage.has_materials && (
            <div className="card" style={{ borderColor: coverage.uncovered.length ? "#e6a23c" : "#90caf9", margin: "8px 0" }}>
              <h2 style={{ margin: "0 0 4px" }}>
                章节进度 · 已有内容 {coverage.covered} / {coverage.total} 节
                {typeof coverage.page_covered === "number" && coverage.page_total ? (
                  <span className="dim" style={{ fontSize: 13 }}>
                    {" "}（按页算：{coverage.page_covered}/{coverage.page_total} 页已对应到单元）
                  </span>
                ) : null}
              </h2>
              <div className="dim" style={{ fontSize: 12 }}>
                书的结构：
                {coverage.materials.map((m) => `${m.title}（${m.structure_kind}：${m.structure_note}）`).join("；")}
                {coverage.multi_material ? ` · 共 ${coverage.materials.length} 份（已合成一份章节地图）` : ""}
                {coverage.order_basis ? ` · 阅读顺序：${coverage.order_basis}` : ""}
              </div>

              {/* R38 B1：**按材料分组**的覆盖统计（跨全部材料；未覆盖清单按材料分组） */}
              {coverage.by_material && coverage.by_material.length > 0 && (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 6 }}>
                  <thead>
                    <tr className="dim">
                      <th style={{ textAlign: "left" }}>材料</th>
                      <th>用途</th>
                      <th>已有内容 / 总节数</th>
                      <th>字数</th>
                      <th>页数</th>
                      <th>体检</th>
                      <th>图示不可用</th>
                      <th>到上限没读</th>
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
                        {/* R55 A：这份材料读起来好不好（人话在悬停里） */}
                        <td style={{ padding: "3px", textAlign: "center" }}>
                          {b.health_grade
                            ? <span className={`badge ${b.health_grade === "好" ? "pass" : b.health_grade === "差" ? "error" : "deferred"}`}
                                    title={b.health_summary_zh}>
                                {b.health_grade}
                                {!!b.image_count && ` · ${b.image_count} 图`}
                              </span>
                            : "—"}
                        </td>
                        {/* R55 B：哪些章/节在引用图（系统读不到图，不会被当作依据） */}
                        <td style={{ padding: "3px", textAlign: "center" }}>
                          {b.figure_unavailable_count
                            ? <span className="badge deferred" title={(b.figure_unavailable ?? []).join("、")}>
                                {b.figure_unavailable_count} 处
                              </span>
                            : "—"}
                        </td>
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
                  这本书的「最多读多少」已经读完（{charsText(coverage.inject_cap.cap ?? 0)}），
                  还有 <strong>{coverage.inject_cap.skipped_count}</strong> 章/节**没有读**：
                  <ul className="plain" style={{ margin: "4px 0 0 12px" }}>
                    {(coverage.inject_cap.skipped_by_material ?? []).map((g) => (
                      <li key={g.material_id}>
                        《{g.title}》：
                        {g.items.map((it) => `${it.label}（${charsText(it.chars)}）`).join("、")}
                      </li>
                    ))}
                  </ul>
                  <div className="dim" style={{ fontSize: 12 }}>
                    没读过的章节**不会被编造内容**，所以它们算「还没内容」；把「最多读多少」调大或设成不限、
                    再重新起草就能读上（想更省又不想漏章节 → 把「每次读多少」调小）。
                  </div>
                </div>
              )}

              {coverage.uncovered.length === 0 ? (
                <div className="badge pass">书的每一章/每一节都已经有内容了</div>
              ) : (
                <>
                  {/* R38 B1：未覆盖清单**按材料分组**显式列出（不是只在 prompt 尾部提一句） */}
                  {coverage.uncovered_by_material && coverage.uncovered_by_material.length > 0 ? (
                    coverage.uncovered_by_material.map((g) => (
                      <div className="banner warn" key={g.material_id} style={{ marginTop: 4 }}>
                        《{g.title}》（{g.role_zh}）还有 {g.items.length} 节没有内容：
                        {g.items.map((x) => `${x.label}（${charsText(x.chars)}）`).join("、")}
                      </div>
                    ))
                  ) : (
                    <div className="banner warn">
                      还没有内容的章节（{coverage.uncovered.length}）：{coverage.uncovered.join("、")}
                    </div>
                  )}
                  <div className="dim" style={{ fontSize: 12 }}>
                    教材里有、但还没出内容的部分**不会被编造**。补充或调整单元后重新生成大纲即可；
                    这些也都记在了
                    <Link to={`/ledger?subject_id=${id}&category=coverage`}>记录页</Link>。
                  </div>
                </>
              )}
              {/* R42 A3：没读清单（三种原因都列出来——读不了 / 没排上 / 到上限） */}
              {coverage.not_injected && coverage.not_injected.length > 0 && (
                <details style={{ marginTop: 6 }}>
                  <summary className="dim">
                    没读的章节（{coverage.not_injected.length}，含原因）
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
                  两种去处都不算「没出内容」，且都在记录页留了中文原因。 */}
              {!!coverage.skipped_short?.count && (
                <details style={{ marginTop: 6 }}>
                  <summary className="dim">
                    太短的条目（{coverage.skipped_short.count} 条被跳过；另有几条已并进相邻单元）
                    —— 两种都不算「没出内容」
                  </summary>
                  <div className="dim" style={{ fontSize: 12, margin: "4px 0 0 12px" }}>
                    太短的条目（不到 {coverage.skipped_short?.min_chars} 字，多是标题或目录行）有两种去处：
                    <strong>① 并进相邻单元</strong>——它留在了那个单元的依据里
                    （在下面"每个单元的情况"里显示"并入过短条目 N"）；
                    <strong>② 直接跳过</strong>——下面列出的就是这一类。
                    两种都在
                    <Link to={`/ledger?subject_id=${id}&category=other`}>记录页</Link>写明了原因。
                  </div>
                  <ul className="plain" style={{ margin: "4px 0 0 12px", fontSize: 12 }}>
                    {(coverage.skipped_short.items ?? []).map((x, i) => (
                      <li key={`${x.material_id ?? x.material}-${x.label}-${i}`}>
                        {x.material} · {x.label}（{x.chars} 字 &lt; {coverage.skipped_short?.min_chars} 字）
                        —— 太短，跳过了
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {coverage.uncovered_materials && coverage.uncovered_materials.length > 0 && (
                <div className="banner error" style={{ marginTop: 4 }}>
                  整份都没读的教材（{coverage.uncovered_materials.length}）：
                  {coverage.uncovered_materials.map((m) => `${m.title}（${m.kind}）`).join("、")}
                </div>
              )}
              <details style={{ marginTop: 6 }}>
                <summary className="dim">每个单元的情况（{coverage.units.length}）</summary>
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
                            : "没有教材依据"}
                          {u.grounded_facts > 0 && ` · ${u.grounded_facts} 条要点逐字取自教材`}
                          {u.dropped_exercises > 0 && ` · ${u.dropped_exercises} 道题没用上`}
                          {/* R42 B4：章内该节级依据（比"整章"更精确；取不到就不显示，不编造） */}
                          {u.basis_section && (
                            <div style={{ fontSize: 12 }}>
                              📍 依据（这一节）：{u.basis_section}
                              {u.basis_quote && <span title={u.basis_quote}> · 原文：{u.basis_quote.slice(0, 60)}…</span>}
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
                            {u.status === "reviewed" && <span className="badge pass">已定稿</span>}
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
                                难度调高了 {u.meta.difficulty_raised.from}→{u.meta.difficulty_raised.to}
                              </span>
                            )}
                            {/* R42 B1：过短条目已并入本单元（覆盖账可解释"它去哪了"） */}
                            {!!u.meta?.absorbed_short?.length && (
                              <span className="badge"
                                    title={u.meta.absorbed_short.map((x) => `${x.label}（${x.chars} 字）`).join("、")}>
                                并入 {u.meta.absorbed_short.length} 条过短内容
                              </span>
                            )}
                            {u.materials && u.materials.length > 0 && (
                              <div className="dim" style={{ fontSize: 12 }}>
                                来自：{u.materials.map((r) => `《${r.title}》${r.section ? " · " + r.section : ""}`).join("；")}
                              </div>
                            )}
                          </td>
                          <td style={{ padding: "6px 4px" }}>
                            {/* R54 C：有没有内容，一眼看出（与覆盖账/会话守卫同源） */}
                            {(() => {
                              const c = contentOf(u.id);
                              if (!c) return null;
                              // R55 B：整节内容都在图里 → 明确说"读不到图"，不让人以为只是"还没生成"
                              if (c.figure_unavailable && c.usable === false) {
                                return (
                                  <span className="badge deferred"
                                        title={c.content_reason_zh || "这一节的内容基本都在图里，程序读不到图片内容"}>
                                    图示不可用 · 没出内容
                                  </span>
                                );
                              }
                              return c.usable === false ? (
                                <span className="badge deferred" title={c.content_reason_zh}>还没内容</span>
                              ) : (
                                <span className="badge pass">有内容</span>
                              );
                            })()}
                            {pv && (
                              <span className={`badge ${STATUS_CLS[pv.status] ?? ""}`}>
                                {STATUS_LABEL[pv.status] ?? pv.status}
                                {pv.open && pv.status === "todo" ? " · 可学" : ""}
                              </span>
                            )}
                            {/* R54 B：轻微丢弃 → 单元仍可用，但如实提示丢了几道题 */}
                            {(() => {
                              const n = contentOf(u.id)?.dropped_exercises ?? 0;
                              if (!n) return null;
                              return (
                                <span className="badge"
                                      title="题目的依据引文在教材里查不到；按「不编造」的规矩没有采用">
                                  {n} 道题没采用
                                </span>
                              );
                            })()}
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
                                  生成内容
                                </button>{" "}
                                <button style={{ padding: "4px 10px" }} onClick={() => learnUnit(u.id)} disabled={busy}
                                  title={pv?.open ? "开始学习这个单元" : "还没解锁（要先学完前面的单元）"}>
                                  开始学习
                                </button>
                                {/* R54 C：点"还没内容"的单元 → 就地提示 + 一键生成（不把人带进空会话） */}
                                {hintUnit === u.id && contentOf(u.id)?.usable === false && (
                                  <div className="banner warn" style={{ marginTop: 4, fontSize: 12 }}>
                                    {contentOf(u.id)?.content_reason_zh || "这个单元还没有内容"}
                                    <button style={{ marginLeft: 8, padding: "2px 8px" }}
                                            onClick={() => void genContent(u.id)} disabled={busy}>
                                      现在生成
                                    </button>
                                  </div>
                                )}
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
          {/* R39 §1：单元出稿的**就地**账目（题/事实句被丢弃、降级启发式、整单元未出稿…）
              R54 B：每条丢弃账目就地给"重新生成这个单元"；已重新生成的旧账目标"已解决" */}
          <LedgerAlerts entries={lastUnitLedger} subjectId={id} title="最近一次单元出稿记录" compact
                        onAction={(a) => void regenerateFromLedger(a)} />
        </div>
      )}
    </div>
  );
}
