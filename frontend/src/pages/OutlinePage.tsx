import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import MaterialBudgetPanel, { charsText } from "../components/MaterialBudgetPanel";
import LedgerAlerts, { LedgerEntry } from "../components/LedgerAlerts";
import { Collapsible, PageHead } from "../components/ui";

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

// R67：材料上的"上次读到哪了"（程序重启过也留着）+ 该走哪条路的建议
type MaterialImportState = {
  state?: string;
  strategy?: string;
  sampled?: boolean;
  read?: number;
  total?: number;
  pending?: string[];
  failed?: string[];
  note_zh?: string;
};

type MaterialSuggest = {
  better?: string;
  reason_zh?: string;
  can_switch_to_pages?: boolean;
  can_switch_to_text?: boolean;
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
  /** R67：上次读到哪了（进度；程序重启后仍能看出来） */
  import_state?: MaterialImportState;
  /** R67：该走哪条路 + 能不能一键改道 */
  suggest?: MaterialSuggest;
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
  /** R67 任务 D：这份材料的读书账（进流程 / 没进去 / 差在哪） */
  text_account?: TextAccount;
  /** R67 任务 F：是不是"抽样读"的（读了哪几页 / 还剩哪些页） */
  sampled?: boolean;
  read_pages?: number;
  planned_pages?: number;
  pages_pending?: string[];
  import_state?: string;
};

/** R67 任务 D：一份材料的"读书账"（进流程多少字 / 没进去多少字 / 差在哪）。 */
type TextAccount = {
  material_id?: string;
  title?: string;
  body_chars?: number;
  injected_chars?: number;
  blocks_chars?: number;
  not_injected_chars?: number;
  cap_skipped_chars?: number;
  unused_page_chars?: number;
  marker_chars?: number;
  note_zh?: string;
  groups?: { kind: string; label_zh: string; count: number; chars: number; sample_zh: string }[];
};

type NotInjected = {  material: string;
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
  /** R67 任务 D：跨材料的读书账合计（进流程多少字 / 没进去多少字 / 差在哪） */
  text_account?: TextAccount & { materials?: TextAccount[]; all_checks_ok?: boolean };
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

const POLICY_LABEL: Record<string, string> = {
  ai: "AI 全生成",
  import: "本地教材导入",
  web: "联网候选清单",
  mixed: "混合",
};

// R67：读法三档 / 一次读多少页 / 同时读几页（都由后端给默认值与上限，界面不写死）
type ReadOptions = {
  strategies: { value: string; label: string }[];
  default_strategy: string;
  default_max_pages: number;
  hard_max_pages: number;
  default_concurrency: number;
  max_concurrency: number;
  default_batch_pages: number;
  max_batch_pages: number;
  fast_pages_per_chapter: number;
  checkpoint_every_pages: number;
  seconds_per_page_hint: number;
  note_zh: string;
};

// R67 任务 A：一次导入的进度（后台任务；刷新页面也能接着看）
type ImportJob = {
  id: string;
  status: "running" | "done" | "cancelled" | "failed";
  title: string;
  total: number;
  done: number;
  failed: number;
  current: string;
  material_id: string;
  note_zh: string;
  strategy?: string;
  sampled?: boolean;
  pending?: string[];
  unreadable?: string[];
  error_zh?: string;
  read_options?: ReadOptions;
  poll_zh?: string;
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
  // 学科本身读不出来（已停用 / 已移除 / 不存在）→ 与「保存、导入失败」分开记：
  // 前者给提示态卡片（下一步该去哪），后者仍走上面的红色横幅。
  const [loadErr, setLoadErr] = useState<string | null>(null);
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
    read_options?: ReadOptions;
    entry_zh: {
      label: string; what_zh: string; pros_zh: string; costs_zh: string[];
      not_better_zh: string; need_images_zh: string;
    };
  } | null>(null);
  // R67：读法三档 + 一次读多少页（默认 60，用户可改）+ 同时读几页 + 一次读几页
  const [readMaxPages, setReadMaxPages] = useState("60");
  const [readStrategy, setReadStrategy] = useState("full");
  const [readConcurrency, setReadConcurrency] = useState("3");
  const [readBatch, setReadBatch] = useState("1");
  // R67 任务 A：导入进度（点击后立刻返回，进度在这里一直更新；可随时停止）
  const [job, setJob] = useState<ImportJob | null>(null);
  const [cancelling, setCancelling] = useState(false);
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
      setMsg(role === "main" ? "已标为主教材（定顺序与范围）" : "已标为补充材料（只补细节与例题）");
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
        setErr(`PDF 已入库「${r.title}」，但没有可用文本层：${r.text_health.note}`);
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
  // 大纲/进度读完之前不挂载折叠区（否则"默认收起"会被误判成"还没有大纲→展开"）
  const [loaded, setLoaded] = useState(false);
  // 旧格式页（标签里没有页号）→ 人工指定"当作第几页"（每个材料一行输入）
  const [mapLabel, setMapLabel] = useState<Record<string, string>>({});
  const [mapNo, setMapNo] = useState<Record<string, string>>({});

  /** 把某个旧标签当作第 N 页（后端：冲突/非法都给中文说明，不静默覆盖）。 */
  const mapLegacyPage = async (mid: string) => {
    const label = (mapLabel[mid] ?? "").trim();
    const n = Number((mapNo[mid] ?? "").trim());
    if (!label) {
      setErr("请先填页面上原来的标签（例如 封面）");
      return;
    }
    if (!Number.isInteger(n) || n < 1) {
      setErr("页号要填 1 以上的整数（页码从 1 开始数）");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{ label: string; page_no: number; note_zh?: string }>(
        `/subjects/${id}/materials/${mid}/page-mapping`, { label, page_no: n });
      setMsg(r.note_zh || `已把「${label}」当作第 ${n} 页。`);
      setMapLabel({ ...mapLabel, [mid]: "" });
      setMapNo({ ...mapNo, [mid]: "" });
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  /** 撤销人工指定（指定错了能改回来；撤销也留痕）。 */
  const unmapLegacyPage = async (mid: string) => {
    const label = (mapLabel[mid] ?? "").trim();
    if (!label) {
      setErr("请先填要撤销的那个标签（例如 封面）");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.del<{ label: string; note_zh?: string }>(
        `/subjects/${id}/materials/${mid}/page-mapping/${encodeURIComponent(label)}`);
      setMsg(r.note_zh || `已撤销「${label}」的人工页号。`);
      setMapLabel({ ...mapLabel, [mid]: "" });
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

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

  // R67 任务 A：导入改**后台任务**——点击后立刻返回，进度在这里一直更新，随时可以停。
  // 任务号记在本地：刷新页面后先按"最近一次任务"把进度接回来（任务记录只在程序内存里，
  // 程序重启过就查不到 → 那时按材料上留下的"读到哪了"如实显示，不假装还在跑）。
  const jobIdRef = useRef<string>("");

  const uploadPages = async () => {
    const inp = pagesFileRef.current;
    const list = Array.from(inp?.files ?? []);
    if (!list.length) {
      setErr("请先选择教材的页面图片或 PDF（PDF 会自动按页转成图片；也可以一次选多张图片）");
      return;
    }
    const fd = new FormData();
    if (matTitle.trim()) fd.append("title", matTitle.trim());
    for (const f of list) fd.append("files", f);
    // 先把文件塞进 fd，再补读法参数（同一个 FormData 一起提交）
    const extra = {
      pages: modePages.trim(),
      strategy: readStrategy,
      max_pages: readMaxPages.trim(),
      concurrency: readConcurrency,
      batch_pages: readBatch,
    };
    for (const [k, v] of Object.entries(extra)) if (v) fd.append(k, v);
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.upload<ImportJob>(`/subjects/${id}/materials/upload-pages/start`, fd);
      jobIdRef.current = r.id;
      setJob(r);
      setMsg(r.poll_zh || "已开始导入：进度会一直在页面上更新（可以随时点「停止这次导入」）。");
      if (inp) inp.value = "";
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  /** 停止这次导入：已读的页会留在材料里（一页都不丢）。 */
  const cancelImport = async () => {
    if (!job?.id) return;
    setCancelling(true);
    setErr("");
    try {
      const r = await api.post<ImportJob>(`/subjects/${id}/import-jobs/${job.id}/cancel`, {});
      setJob(r);
      setMsg(r.note_zh || "已请求停止：读完手上这一页就停，已读的页会存下来。");
    } catch (e) {
      setErr(String(e));
    } finally {
      setCancelling(false);
    }
  };

  /** R67 任务 E：选错了能**一键改道**——把这份 PDF 改成"连图一起看"（不必重导一遍）。 */
  const switchToPages = async (mid: string) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const fd = new FormData();
      fd.append("strategy", readStrategy);
      fd.append("max_pages", readMaxPages.trim());
      fd.append("concurrency", readConcurrency);
      fd.append("batch_pages", readBatch);
      const r = await api.upload<ImportJob>(
        `/subjects/${id}/materials/${mid}/switch-to-pages`, fd);
      jobIdRef.current = r.id;
      setJob(r);
      setMsg("已改道：正在把这份 PDF 逐页交给 AI 读（进度会一直更新）。原来那份只看文字的材料没动。");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  /** 反向改道：把"连图一起看"读过的 PDF 再按"只看文字"存一份（原来那份一字不动）。 */
  const switchToText = async (mid: string) => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.post<{ title: string; note_zh?: string }>(
        `/subjects/${id}/materials/${mid}/switch-to-text`, {});
      setMsg(r.note_zh || `已另存一份「${r.title}」。`);
      await loadMaterials();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  /** 接着把没读的页补读（材料里留下的"还剩哪些页没读"）。
   *  页可能很多 → 走**后台任务**（进度可见、可取消、已读的留着），不再是一个请求挂十几分钟。 */
  const readPendingPages = async (mid: string, title: string, pending: string[]) => {
    const nums = pending.map((x) => (x.match(/第\s*(\d+)\s*页/) || [])[1]).filter(Boolean);
    if (!nums.length) {
      setErr("这份材料剩下的页没有页号，没法自动补读——可以在下面按页重读。");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const fd = new FormData();
      fd.append("pages", nums.join(","));
      fd.append("strategy", "range");
      fd.append("max_pages", String(Math.max(nums.length, 1)));
      fd.append("concurrency", readConcurrency);
      fd.append("batch_pages", readBatch);
      const r = await api.upload<ImportJob>(
        `/subjects/${id}/materials/${mid}/read-pages-job`, fd);
      jobIdRef.current = r.id;
      setJob(r);
      setMsg(`已开始接着读《${title}》还没读的 ${nums.length} 页（进度会一直更新；读到的会另存一份新材料）。`);
    } catch (e) {
      // 没有 PDF 缓存（例如页面图片导入的材料）→ 回到按页重读（页少时够用）
      setErr(String(e));
      await rereadMaterialPages(mid, title, nums.slice(0, 12).join(","));
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
      setLoadErr(null);
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
      // 学科本身没读出来（后端给的是中文原话）→ 记下来，页面改成提示态
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      // 折叠区的"默认开/关"在挂载那一刻定下来：必须等这里读完再挂载，
      // 否则会在"还没读到大纲"时误判成"没有大纲"从而默认展开。
      setLoaded(true);
    }
  }, [id]);

  /** 刷新页面后把进度接回来：先看这个学科有没有正在跑的导入（任务记录只在程序内存里，
   *  程序重启过就查不到 → 这时按材料上留下的"读到哪了"如实显示，不假装还在跑）。 */
  const resumeImportJob = async () => {
    try {
      const r = await api.get<{ active: ImportJob | null }>(`/subjects/${id}/import-jobs`);
      if (r.active && r.active.id) {
        jobIdRef.current = r.active.id;
        setJob(r.active);
      }
    } catch {
      /* 读不到就算了：材料列表里仍能看出"读到哪了" */
    }
  };

  useEffect(() => {
    void load();
    void loadMaterials();
    void loadModeEntry();
    void resumeImportJob();
  }, [load]);

  // R67 任务 A：进度轮询（只在这条导入还在跑的时候轮询；跑完就把材料列表刷新一遍）
  useEffect(() => {
    if (!job || job.status !== "running" || !job.id) return;
    let stopped = false;
    const tick = async () => {
      try {
        const r = await api.get<ImportJob>(`/subjects/${id}/import-jobs/${job.id}`);
        if (stopped) return;
        setJob(r);
        if (r.status !== "running") {
          await loadMaterials();
          if (r.status === "cancelled") {
            setMsg(r.note_zh || "已停止：读到的页都存下来了。");
          } else if (r.status === "failed") {
            setErr(`这次导入没能继续：${r.error_zh || r.note_zh || "原因见记录"}`);
          } else {
            setMsg(`「${r.title}」${r.note_zh || "读完了"}` +
              (r.unreadable?.length
                ? `读不出来的页：${r.unreadable.join("、")}（已如实标注，不会当成内容用）`
                : ""));
          }
        }
      } catch (e) {
        if (stopped) return;
        // 程序重启过 / 任务号失效：进度查不到了，但已读的页还在材料里
        setJob(null);
        setErr(`${String(e)}`);
        await loadMaterials();
      }
    };
    const h = window.setInterval(() => void tick(), 900);
    void tick();
    return () => {
      stopped = true;
      window.clearInterval(h);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status, id]);

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

  // 学科本身读不出来（已停用 / 已移除 / 不存在）：只给一张提示态卡片。
  // 材料、大纲、单元那些区块一律不挂载——它们各自都会去打接口，只会在界面上刷一片报错。
  if (loadErr) {
    return (
      <div>
        <PageHead
          crumb={<Link to="/subjects">← 学科列表</Link>}
          title="这个学科现在打不开"
          actions={<Link className="button-link" to="/">← 回主页</Link>}
        />
        <div className="card">
          <div className="empty-state">
            <div className="big">{loadErr}</div>
            <div>如果这个学科被停用了：内容不再显示，到「学科列表」重新启用后，内容和进度都还在。</div>
            <div className="muted">如果是网络或服务暂时出错，稍后再打开一次就好。</div>
            <div className="actions" style={{ justifyContent: "center" }}>
              <Link className="button-link primary" to="/subjects">去学科列表</Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHead
        crumb={<Link to="/subjects">← 学科列表</Link>}
        title={
          <>
            {subject?.label ?? "学科"}
            {subject && (
              <span className="badge" style={{ marginLeft: 10, verticalAlign: "middle" }}>
                {isPreset ? "系统自带的学科" : "自定义学科"}
              </span>
            )}
          </>
        }
        sub={
          outline
            ? `大纲第 ${outline.revision} 版 · ${groups.length} 章 · ${(outline.units as Unit[]).length} 个单元`
            : "还没有课程安排"
        }
        actions={<Link className="button-link" to="/">← 回主页</Link>}
      />
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner ok">{msg}</div>}

      {/* 学科管理：内容来源策略 + 材料层（docs/14 §8 · Phase B B3 + Phase C C1）
          R61：默认收成一行摘要（"有多少份教材、来源是什么"），点开才是导入/检索/PDF/图片为主那套。 */}
      <Collapsible
        id="outline-materials"
        title="材料与来源"
        summary={`${materials.length} 份教材 · 来源：${POLICY_LABEL[policy] ?? policy}${modeLabel ? ` · ${modeLabel}` : ""}`}
      >
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
          教材（{materials.length} 份）：<strong>一切以教材为准</strong>——大纲按书的目录排，讲解和题目只用教材里的原话，
          服务端会逐字核对：教材里查不到的题不会用，查不到依据的内容整个单元都不会生成。
        </div>

        {/* 联网候选清单（C1：provider 抽象 + 勾选入库） */}
        <div style={{ margin: "6px 0" }}>
          <div className="input-row" style={{ gap: 8 }}>
            <input placeholder="检索词（如：行星科学 入门教材）" value={searchQ}
                   onChange={(e) => setSearchQ(e.target.value)}
                   style={{ flex: 1 }} />
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
                 style={{ flex: 1 }} />
          <button className="primary" disabled={busy || !matTitle.trim() || !matText.trim()}
                  onClick={() => void uploadMaterial()}>
            导入文本
          </button>
        </div>
        <textarea placeholder="粘贴自有/授权教材文本…（选填更多材料）" value={matText}
                  onChange={(e) => setMatText(e.target.value)}
                  style={{ width: "100%", minHeight: 56 }} />

        {/* C2：PDF 上传（分页/分节 → 引用库 kind:pdf；保留文本粘贴入口）
            R67 任务 E：两个入口的**区别写在按钮上**（只看文字 vs 连图一起看），
            并把"选错了怎么办"就地写出来（一键改道，不必重导一遍）。 */}
        <div className="input-row" style={{ gap: 8, margin: "8px 0" }}>
          <input type="file" accept=".pdf,application/pdf" ref={pdfFileRef} disabled={busy}
                 style={{ flex: 1 }} />
          <button className="primary" disabled={busy} onClick={() => void uploadPdf()}>
            上传 PDF（只看文字）
          </button>
        </div>
        <div className="dim" style={{ fontSize: 12 }}>
          <strong>只看文字</strong>：把 PDF 里的文字抽出来当教材（快、省；<strong>书里的图看不见</strong>）。
          PDF ≤20MB，扫描图片版请先做文字识别或改用下面那条路；
          仅上传自有/授权资料，不整本下载书籍。
        </div>

        {/* R56 第 3 步：图示教材模式（页面图片 → 全程交给 AI 判断）——
            导入前先把"代价"写在看得见的地方（没有独立核对 / 失败更隐蔽 / 更贵） */}
        <div className="panel-warn" style={{ marginTop: 10, padding: 10 }}>
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
              导入页面图片 / PDF（连图一起看）
            </button>
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 2 }}>
            <strong>连图一起看</strong>：把 PDF 每页转成图片交给 AI 读（<strong>图、公式、版式都看得见</strong>，
            但更慢也更贵）。<strong>图多的书选这条</strong>。
          </div>
          {/* R67 任务 B/F：读法三档 + 一次读多少页 + 两项提速（都由用户定，都有默认值） */}
          <div className="input-row" style={{ gap: 8, marginTop: 6, flexWrap: "wrap",
                                              alignItems: "center" }}>
            <label className="dim">读法</label>
            <select value={readStrategy} disabled={busy}
                    onChange={(e) => setReadStrategy(e.target.value)}
                    title="快读：只读目录页和每章开头几页，够排大纲；按页范围读：只读你填的那几页；整本精读：一页不落">
              {(modeEntry?.read_options?.strategies ?? [
                { value: "fast", label: "快读（挑着读）" },
                { value: "range", label: "按页范围读" },
                { value: "full", label: "整本精读" },
              ]).map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
            <label className="dim">一次读多少页</label>
            <input value={readMaxPages} onChange={(e) => setReadMaxPages(e.target.value)}
                   style={{ width: 70 }} placeholder={String(modeEntry?.read_options?.default_max_pages ?? 60)}
                   title="想读整本就把这本书的页数填进来（例如 126）；填 0 或负数会有中文提示" />
            <input placeholder="页范围（可选，如 1-20；留空＝按读法来）" value={modePages}
                   onChange={(e) => setModePages(e.target.value)}
                   style={{ width: 240 }} />
          </div>
          <div className="input-row" style={{ gap: 8, marginTop: 4, flexWrap: "wrap",
                                              alignItems: "center" }}>
            <label className="dim">同时读几页</label>
            <select value={readConcurrency} disabled={busy}
                    onChange={(e) => setReadConcurrency(e.target.value)}
                    title="同时读几页会快一些；填太大容易被服务商限流">
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={String(n)}>{n} 页</option>
              ))}
            </select>
            <label className="dim">一次读几页（省来回）</label>
            <select value={readBatch} disabled={busy}
                    onChange={(e) => setReadBatch(e.target.value)}
                    title="一次调用塞几页给模型（1 = 一页一页来，最稳）">
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={String(n)}>{n} 页</option>
              ))}
            </select>
            <button className="ghost" disabled={busy || draftingMode || !modeEntry?.vision_ready}
                    onClick={() => void draftModeOutline()}>
              {draftingMode ? "正在按页面记录排大纲…" : "一键起草大纲（本模式）"}
            </button>
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
            读得越多越慢、越贵，<strong>大约每页 8 秒</strong>：想先看个大概就选「快读」
            （目录页 + 每章开头几页，够排大纲），回头再补读没读到的页；
            <strong>没读过的章不会生成讲解和题目</strong>（系统不编造）。
          </div>
          {/* R67 任务 A：导入进度（点击后立刻开始，进度一直更新，随时可以停） */}
          {job && (
            <div className={job.status === "failed" ? "banner error"
                            : job.status === "running" ? "banner warn" : "banner ok"}
                 style={{ marginTop: 6 }}>
              {job.status === "running" ? (
                <>
                  <strong>正在读：{job.done} / {job.total || "…"} 页</strong>
                  {job.current && <span className="dim">（刚读完：{job.current}）</span>}
                  {job.total > 0 && (
                    <progress value={job.done} max={job.total}
                              style={{ width: "100%", marginTop: 4 }} />
                  )}
                  <div className="dim" style={{ fontSize: 12 }}>
                    {job.note_zh} 已经读到的页会一直存在材料里——现在停也不会白读。
                  </div>
                  <button className="ghost" disabled={cancelling} onClick={() => void cancelImport()}>
                    {cancelling ? "正在停止…" : "停止这次导入"}
                  </button>
                </>
              ) : (
                <>
                  <strong>
                    {job.status === "cancelled" ? `已停止：读到了 ${job.done} 页`
                      : job.status === "failed" ? "这次导入没能继续"
                        : `读完了：共 ${job.done} 页`}
                  </strong>
                  <div className="dim" style={{ fontSize: 12 }}>{job.note_zh}</div>
                  {!!job.unreadable?.length && (
                    <div className="dim" style={{ fontSize: 12 }}>
                      读不出来的页：{job.unreadable.join("、")}（已如实标注，不会当成内容用）
                    </div>
                  )}
                  {!!job.pending?.length && (
                    <div className="dim" style={{ fontSize: 12 }}>
                      还有 {job.pending.length} 页没读（已读的都在材料里）：
                      {job.pending.slice(0, 8).join("、")}
                      {job.pending.length > 8 ? "…" : ""}
                    </div>
                  )}
                  <button className="ghost" onClick={() => setJob(null)}>收起</button>
                </>
              )}
            </div>
          )}
          <div className="dim" style={{ fontSize: 12 }}>
            可以<strong>直接选 PDF</strong>：装了渲染组件就<strong>按页转成图片</strong>再交给模型（一页一张、页号留痕；
            出图宽 {modeEntry?.pdf_render_options?.width ?? 1024} px、格式
            {" "}{modeEntry?.pdf_render_options?.format ?? "jpeg"}、DPI 上限
            {" "}{modeEntry?.pdf_render_options?.dpi_cap ?? 200}；参数可在配置里改）；
            {" "}<strong>页面图片不会存进内容目录</strong>（避免仓库膨胀），只留"读到了什么"。
            读不出来的页会<strong>如实标注</strong>、不会被当成内容用。
            {modeEntry?.vision_model ? `读图用的模型：${modeEntry.vision_model}。` : ""}
          </div>
        </div>

        {/* 引用材料列表（可删除） */}
        {materials.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {materials.map((m) => (
              <div key={m.id} className="row-divider"
                   style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                            padding: "4px 0", gap: 8 }}>
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
                    <div className="dim error-text" style={{ fontSize: 12 }}>{m.text_health.note}</div>
                  )}
                  {/* R67 任务 A：这份材料"上次读到哪了"（程序重启过也照样看得见） */}
                  {!!m.import_state?.total && m.import_state.state !== "done" && (
                    <div className="dim" style={{ fontSize: 12 }}>
                      <span className={`badge ${m.import_state.state === "importing" ? "deferred" : ""}`}>
                        {m.import_state.state === "importing" ? "上次没读完" : "已停止"}
                      </span>{" "}
                      已读 {m.import_state.read} / 共 {m.import_state.total} 页
                      {!!m.import_state.pending?.length && (
                        <>（还剩 {m.import_state.pending.length} 页没读：{m.import_state.pending.slice(0, 6).join("、")}{m.import_state.pending.length > 6 ? "…" : ""}）</>
                      )}
                      {!!m.import_state.pending?.length && (
                        <button className="ghost" disabled={busy} style={{ marginLeft: 6 }}
                                onClick={() => void readPendingPages(m.id, m.title, m.import_state!.pending ?? [])}
                                title="把这份材料里还没读的页接着读完（会再问模型，所以会花钱）">
                          接着读完没读的页
                        </button>
                      )}
                    </div>
                  )}
                  {m.import_state?.sampled && (
                    <div className="dim" style={{ fontSize: 12 }}>
                      <span className="badge deferred">抽样读</span>{" "}
                      这本书是挑着读的（目录页 + 每章开头几页）：没读到的章不会生成讲解和题目。
                    </div>
                  )}
                  {/* R67 任务 E：按这份材料的特征给一句人话建议 + 选错了能一键改道 */}
                  {m.suggest?.better === "pages" && (
                    <div className="dim" style={{ fontSize: 12 }}>
                      💡 {m.suggest.reason_zh}
                      {m.suggest.can_switch_to_pages && (
                        <button className="ghost" disabled={busy} style={{ marginLeft: 6 }}
                                onClick={() => void switchToPages(m.id)}
                                title="不用重新上传：直接用这份 PDF 再按「连图一起看」读一遍；原来那份只看文字的材料一字不动">
                          一键改成「连图一起看」
                        </button>
                      )}
                      {!m.suggest.can_switch_to_pages && (
                        <span className="dim">（这份材料的 PDF 不在缓存里了，要改道得把 PDF 再选一次）</span>
                      )}
                    </div>
                  )}
                  {m.mode === "all_ai" && m.suggest?.can_switch_to_text && (
                    <div className="dim" style={{ fontSize: 12 }}>
                      💡 {m.suggest.reason_zh}
                      <button className="ghost" disabled={busy} style={{ marginLeft: 6 }}
                              onClick={() => void switchToText(m.id)}
                              title="不用重新上传：用同一份 PDF 再存一份「只看文字」的材料；原来这份一字不动">
                        再存一份「只看文字」
                      </button>
                    </div>
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
                             style={{ width: 150 }}
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
                      {/* 旧格式页（标签里没有页号，比如「封面」）：在这里人工说清它是第几页 */}
                      <input value={mapLabel[m.id] ?? ""}
                             onChange={(e) => setMapLabel({ ...mapLabel, [m.id]: e.target.value })}
                             placeholder="旧标签（如 封面）"
                             style={{ width: 130 }}
                             title="页面上没有页号的那种标签，照原样填进来" />
                      <span className="dim">当作第</span>
                      <input value={mapNo[m.id] ?? ""}
                             onChange={(e) => setMapNo({ ...mapNo, [m.id]: e.target.value })}
                             placeholder="4"
                             style={{ width: 52 }}
                             title="页码从 1 开始数" />
                      <span className="dim">页</span>
                      <button className="ghost" disabled={busy}
                              onClick={() => void mapLegacyPage(m.id)}
                              title="指定后这一页就有页号了，可以被正常引用；不会自动去问模型">
                        指定
                      </button>
                      <button className="ghost" disabled={busy}
                              onClick={() => void unmapLegacyPage(m.id)}
                              title="指定错了可以改回来（撤销也会留下记录）">
                        撤销指定
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

        {/* R38：材料读多少（两个滑块 + 上一轮实际读了多少 + 哪几章没读） */}
        <MaterialBudgetPanel subjectId={id} onChanged={() => void load()} />
      </Collapsible>

      {/* R39 §1：材料层的就地账目。R61 起**收成一行**（默认收起、可展开、另给「看全部」）——
          正文太长的最大来源就是它；记录本身一条没删，仍在页面上、一键可见。
          ⚠️ 若架构侧要求"必须默认展开"，把 defaultOpen 去掉即可（一行）。 */}
      <Collapsible
        id={`outline-ledger-${id}`}
        title="内容记录（谁被丢下、为什么）"
        summary="材料与出稿用不上的内容都在这里，点开可逐条看；也可以去「记录」页看全部"
      >
        <SubjectLedgerInline subjectId={id} />
      </Collapsible>

      {/* 起草 / 采纳：已经有课程安排时默认收起（主体让给下面的单元列表）
          ⚠️ 折叠区的"默认开/关"在挂载那一刻定下来，所以要等学科数据到位后再挂载，
          否则会在"还没读到大纲"时误判成"没有大纲"从而默认展开。 */}
      {loaded && (
      <Collapsible
        id="outline-draft"
        title="大纲起草与审阅"
        summary={outline
          ? `当前第 ${outline.revision} 版 · ${outline.status === "active" ? "使用中" : "草稿"} · 要重新起草点开`
          : "还没有课程安排——点开这里起草"}
        defaultOpen={!outline}
      >
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
                style={{ flex: 1 }}
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
                  ⚠️ <strong>「单元数」只在没有教材时有用</strong>：有教材时，{" "}
                  <strong>单元数是按书的章节来的</strong>（每章/每节至少一个单元），
                  所以实际会多于或少于你选的数量——这是<strong>照着书排</strong>，不是出错。
                </>
              )}
              {materials.length > 0
                ? `起草时会先读教材（当前 ${materials.length} 份），完全按书的章节来排单元：每个章节都会对应到单元，没人用的章节按目录补齐。`
                : "（还没有教材：只能按你写的简介排，生成的内容会标注「没有教材依据」。）"}
            </div>
          </>
        )}
        {candidate && (
          <div className="card accent">
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
                    <span style={{ color: "var(--danger)" }}>
                      总量已经读完，还有{" "}
                      <strong>{candidate.material_usage.inject_cap.skipped_count}</strong> 章/节<strong>没读</strong>{" "}
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
              <div key={u.id} className="row-divider" style={{ padding: "4px 0" }}>
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
      </Collapsible>
      )}

      {outline && (
        <div className="card">
          <div className="session-head">
            <h2 style={{ margin: 0 }}>
              单元列表 · 第 {outline.revision} 版 · {outline.status === "active" ? "使用中" : outline.status === "draft" ? "草稿" : outline.status} ·{" "}
              {outline.source === "ai" ? "由 AI 生成" : "手工/系统生成"}
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
            <Collapsible
              id={`outline-coverage-${id}`}
              title="章节进度与依据"
              summary={`已有内容 ${coverage.covered} / ${coverage.total} 节${coverage.uncovered.length ? ` · 还没出内容 ${coverage.uncovered.length} 节` : " · 全书都覆盖到了"}`}
            >
              <h4 style={{ margin: "0 0 4px" }}>
                章节进度 · 已有内容 {coverage.covered} / {coverage.total} 节
                {typeof coverage.page_covered === "number" && coverage.page_total ? (
                  <span className="dim" style={{ fontSize: 13 }}>
                    {" "}（按页算：{coverage.page_covered}/{coverage.page_total} 页已对应到单元）
                  </span>
                ) : null}
              </h4>
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
                      <tr key={b.material_id} className="row-divider">
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

              {/* R67 任务 D：**读书账说实话**——进流程多少字 / 没进去多少字 / 差在哪。
                  （以前这里看着像"全读了"，其实有 12% 的正文根本没进去；现在如实列出） */}
              {coverage.text_account && (coverage.text_account.materials?.length ?? 0) > 0 && (
                <details style={{ marginTop: 6 }} open={(coverage.text_account.not_injected_chars ?? 0) > 0}>
                  <summary className="dim">
                    读书账（进流程 {charsText(coverage.text_account.injected_chars ?? 0)}，
                    没进去 {charsText(coverage.text_account.not_injected_chars ?? 0)}）
                  </summary>
                  <div className="dim" style={{ fontSize: 12, margin: "4px 0 0 12px" }}>
                    教材一共 {charsText(coverage.text_account.body_chars ?? 0)}，
                    真正进入流程的是 {charsText(coverage.text_account.injected_chars ?? 0)}
                    ——没进去的部分下面逐份写清了差在哪。
                    {coverage.text_account.all_checks_ok === false && (
                      <span className="error-text">（有一份材料的账对不上，已在下面标出）</span>
                    )}
                  </div>
                  <ul className="plain" style={{ margin: "4px 0 0 12px", fontSize: 12 }}>
                    {(coverage.text_account.materials ?? []).map((a) => (
                      <li key={a.material_id} style={{ marginTop: 2 }}>
                        《{a.title}》：{a.note_zh}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {/* R67 任务 F：抽样读的材料要标出来（哪些章还没读，不许装成"全书都读了"） */}
              {!!coverage.by_material?.some((b) => b.sampled) && (
                <div className="banner warn" style={{ marginTop: 6 }}>
                  这本书是<strong>挑着读</strong>的（快读：目录页 + 每章开头几页）：
                  {coverage.by_material.filter((b) => b.sampled).map((b) => (
                    <span key={b.material_id}>
                      《{b.title}》已读 {b.read_pages ?? 0} / 共 {b.planned_pages ?? 0} 页
                      {!!b.pages_pending?.length && (
                        <>，还剩 {b.pages_pending.length} 页没读（{b.pages_pending.slice(0, 6).join("、")}{b.pages_pending.length > 6 ? "…" : ""}）</>
                      )}
                    </span>
                  ))}
                  <div className="dim" style={{ fontSize: 12 }}>
                    没读到的章<strong>不会生成讲解和题目</strong>；想全读就回上面把「读法」改成「整本精读」重新导入。
                  </div>
                </div>
              )}
              {/* R42 A3：因「总注入上限」未纳入（覆盖账如实降 —— 不许"没喂却算覆盖"） */}
              {!!coverage.inject_cap?.configured && (coverage.inject_cap.skipped_count > 0) && (
                <div className="banner warn" style={{ marginTop: 6 }}>
                  这本书的「最多读多少」已经读完（{charsText(coverage.inject_cap.cap ?? 0)}），
                  还有 <strong>{coverage.inject_cap.skipped_count}</strong> 章/节<strong>没有读</strong>：
                  <ul className="plain" style={{ margin: "4px 0 0 12px" }}>
                    {(coverage.inject_cap.skipped_by_material ?? []).map((g) => (
                      <li key={g.material_id}>
                        《{g.title}》：
                        {g.items.map((it) => `${it.label}（${charsText(it.chars)}）`).join("、")}
                      </li>
                    ))}
                  </ul>
                  <div className="dim" style={{ fontSize: 12 }}>
                    没读过的章节<strong>不会被编造内容</strong>，所以它们算「还没内容」；把「最多读多少」调大或设成不限、
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
                    教材里有、但还没出内容的部分<strong>不会被编造</strong>。补充或调整单元后重新生成大纲即可；
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
                      <tr key={u.unit_id} className="row-divider">
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
            </Collapsible>
          )}
          {groups.map((g: string, gi: number) => {
            const groupUnits = (outline.units as Unit[]).filter((u) => u.group === g);
            const ready = groupUnits.filter((u) => contentOf(u.id)?.usable !== false).length;
            return (
              <Collapsible
                key={g}
                id={`outline-group-${id}-${g}`}
                title={g}
                summary={`${groupUnits.length} 个单元 · 有内容 ${ready} 个`}
                defaultOpen={gi === 0}
              >
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <tbody>
                  {groupUnits
                    .map((u) => {
                      const pv = progressById[u.id];
                      return (
                        <tr key={u.id} className="row-divider">
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
                              style={{ width: 220 }}
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
              </Collapsible>
            );
          })}
          {/* R39 §1：单元出稿的**就地**账目（题/事实句被丢弃、降级启发式、整单元未出稿…）
              R54 B：每条丢弃账目就地给"重新生成这个单元"；已重新生成的旧账目标"已解决"
              R61：收成一行（默认收起；一条记录都没删） */}
          {lastUnitLedger && lastUnitLedger.length > 0 && (
            <Collapsible
              id={`outline-unit-ledger-${id}`}
              title="最近一次单元出稿记录"
              summary={`${lastUnitLedger.length} 条（哪些内容没用上、为什么）`}
            >
              <LedgerAlerts entries={lastUnitLedger} subjectId={id} compact
                            onAction={(a) => void regenerateFromLedger(a)} />
            </Collapsible>
          )}
        </div>
      )}
    </div>
  );
}
