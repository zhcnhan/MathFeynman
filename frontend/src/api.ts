// 后端客户端（docs/06）：统一 JSON、错误契约 {error:{code,message}}。
// docs/13 §2 错误中文化：后端无文案/网络错误时前端给中文兜底，绝不裸显英文。
export interface ApiErrorBody {
  error: { code: string; message: string };
}

export class ApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

const ZH_FALLBACK: Record<number, string> = {
  400: "请求不合法，请检查输入内容。",
  401: "未授权访问，请确认配置后重试。",
  403: "没有权限执行此操作。",
  404: "请求的资源不存在，请刷新后重试。",
  409: "操作与当前状态冲突，请按提示完成前置条件后再试。",
  422: "请求参数不合法，请检查输入。",
  429: "请求过于频繁，请稍后重试。",
  500: "服务器开小差了，请稍后重试。",
  502: "服务暂时不可用，请稍后重试。",
  503: "服务暂时不可用，请稍后重试。",
};

function zhFallback(status?: number): string {
  if (status && ZH_FALLBACK[status]) return ZH_FALLBACK[status];
  return "网络异常或服务不可达，请检查连接后重试。";
}

function looksEnglish(message: string): boolean {
  // 无中文字符且主体为 ASCII 字母的 message 视为"未中文化"，交给兜底（后端契约已要求中文）
  const hasCJK = /[\u4e00-\u9fff]/.test(message);
  if (hasCJK) return false;
  return /^[A-Za-z]/.test(message.trim());
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const started = performance.now();
  let res: Response;
  const isForm = init?.body instanceof FormData;
  try {
    res = await fetch(`/api${path}`, {
      headers: isForm ? undefined : { "Content-Type": "application/json" },
      ...init,
    });
  } catch (e) {
    console.warn(`[api] ${init?.method ?? "GET"} ${path} -> network error`, e);
    throw new ApiError("network_error", zhFallback());
  }
  if (!res.ok) {
    let code = "http_error";
    let message = "";
    try {
      const body = (await res.json()) as ApiErrorBody | { detail?: ApiErrorBody };
      // 兼容两种包装：{"detail": {"error": ...}}（仓库契约）或扁平 {"error": ...}
      const eb = (body as any)?.detail?.error ?? (body as any)?.error;
      code = eb?.code ?? code;
      message = eb?.message ?? "";
    } catch {
      /* 非 JSON 错误体 → 按状态兜底 */
    }
    if (!message || looksEnglish(message)) {
      // 后端缺失/未中文化文案 → 前端中文兜底（docs/13 §2）
      message = zhFallback(res.status);
      console.warn(
        `[api] ${init?.method ?? "GET"} ${path} -> ${res.status} code=${code} message=${message} (前端兜底)`
      );
    } else {
      console.warn(`[api] ${init?.method ?? "GET"} ${path} -> ${res.status} code=${code} in ${Math.round(performance.now() - started)}ms`, message);
    }
    throw new ApiError(code, message);
  }
  // 204/空响应（如 DELETE）没有 JSON 体 → 直接返回 undefined
  if (res.status === 204) {
    console.debug(`[api] ${init?.method ?? "GET"} ${path} -> 204`);
    return undefined as T;
  }
  const raw = await res.text();
  let data: T;
  try {
    data = raw ? (JSON.parse(raw) as T) : (undefined as T);
  } catch {
    data = raw as unknown as T; // 非 JSON 文本原样返回（避免二次抛错）
  }
  console.debug(`[api] ${init?.method ?? "GET"} ${path} -> 200 in ${Math.round(performance.now() - started)}ms`);
  return data;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  // C2：文件上传（multipart/form-data；不设 JSON 头）
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
};

// ---- R12-b：/session/step?stream=1 SSE 客户端 ----
// 返回与普通 POST 一致的完整 StepResponse；解析失败/非流内容/错误事件 → 抛错，
// 调用方回退普通 POST（docs/09 R12 §3：流不可用自动回退）。
export async function postStepStream(
  sessionId: string,
  action: string,
  payload: Record<string, unknown>,
  onEvent?: (event: string, data: string) => void
): Promise<StepResponse> {
  const res = await fetch(`/api/session/step?stream=1`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, action, payload }),
  });
  if (!res.ok) {
    throw new ApiError("stream_http_error", zhFallback(res.status));
  }
  const ctype = res.headers.get("content-type") ?? "";
  if (!ctype.includes("text/event-stream")) {
    // 服务端未能进入流模式（回退整体 JSON 或错误体）
    const body = await res.json().catch(() => null);
    if (body && body.error) {
      const msg = body.error.message ?? "";
      if (msg && !looksEnglish(msg)) throw new ApiError(body.error.code, msg);
      throw new ApiError(body.error.code ?? "stream_http_error", zhFallback());
    }
    return body as StepResponse;
  }
  if (!res.body) throw new ApiError("stream_empty", "无响应体");
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let result: StepResponse | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const ev = chunk.match(/^event:\s*(.+)$/m)?.[1]?.trim() ?? "";
      const dataLine = chunk.match(/^data:\s*(.+)$/m)?.[1];
      if (!dataLine) continue;
      onEvent?.(ev, dataLine);
      if (ev === "result") result = JSON.parse(dataLine) as StepResponse;
      if (ev === "error") {
        const err = JSON.parse(dataLine) as { code?: string; message?: string };
        console.warn(`[stream] session=${sessionId} action=${action} error-event code=${err.code ?? "stream_error"}`, err.message ?? "");
        throw new ApiError(err.code ?? "stream_error", err.message ?? "流式处理失败");
      }
    }
  }
  if (!result) {
    console.warn(`[stream] session=${sessionId} action=${action} no-result（将自动回退普通 POST）`);
    throw new ApiError("stream_empty", "流式响应未返回结果，请重试（将自动回退普通提交）");
  }
  return result;
}

// ============ 类型（与 docs/06 §2 / 07 契约对齐） ============
export interface DashboardStats {
  mastered: number;
  learning: number;
  available: number;
  locked: number;
  consecutive_days: number;
  today_done: number;
}

export interface DashboardRecommended {
  id: string;
  title: string;
  level: string;
  topic: string;
  prereqs_met: number;
  prereqs_total: number;
}

export interface DueReviewItem {
  node_id: string;
  title: string;
  level: string;
  due_at: string | null;
  stacked: boolean;
  lapse_count: number;
  interval_days: number;
}

export interface DashboardData {
  /** L1（R36 §3）：预置学科（当前=math）生命周期状态；无预置学科时为 null。
   *  停用态由后端直出，前端不再从 `/subjects`（默认不含已移除者）反推。 */
  preset_subject: { id: string; label: string; enabled: boolean } | null;
  recommended_node: DashboardRecommended | null;
  due_reviews: DueReviewItem[];
  breakpoints: unknown[];
  stats: DashboardStats;
}

export interface GraphNode {
  id: string;
  title: string;
  level: string;
  topic: string;
  state: "locked" | "available" | "learning" | "mastered" | "reviewing";
}

export interface GraphData {
  nodes: GraphNode[];
  edges: { node: string; prereq: string }[];
}

export interface NodeMeta {
  id: string;
  title: string;
  level: string;
  topic: string;
  prereqs: string[];
  objectives: string[];
  core_concepts: string[];
  explanation: { role: string; body: string };
  worked_examples: { prompt: string; solution_steps: string[] }[];
  exercises: { id: string; kind: string; difficulty: number; mode: string; interactive: string[]; prompt: string }[];
  feynman: {
    task_prompt: string;
    rubric: { key: string; weight: number; description: string }[];
    pass_threshold: number;
  };
}

// ---- 会话（docs/06 §2 响应协议） ----
export interface SessionMeta {
  id: string;
  node_id: string;
  state: string;
  stage: string;
}

export interface StepEvent {
  type: string;
  [k: string]: unknown;
}

export interface StepResponse {
  step: "explain" | "example" | "practice" | "feynman" | "done";
  payload: Record<string, unknown>;
  events: StepEvent[];
  session: SessionMeta;
}

export interface ExerciseView {
  exercise_id: string;
  prompt: string;
  mode: string;
  difficulty: number;
  interactive: string[];
  seed: number;
  /** B2：single_choice 的选项列表（前端渲染用；判题在服务端，不泄 index/答案） */
  options?: string[];
}

// ---- R27：费曼缺口账本（实时得分条数据源） ----
export interface FeynmanLedgerDim {
  key: string;
  label: string;
  /** 账本维度分 = 历轮最高分（答对认账、看得见涨分） */
  score: number;
  best: number;
  latest: number;
  weight: number;
  evidence_quote: string;
  comment: string;
  updated_round: number;
}

export interface FeynmanGap {
  key: string;
  description: string;
  score: number;
}

export interface FeynmanLedger {
  dimensions: FeynmanLedgerDim[];
  combined: number;
  threshold: number;
  gaps: FeynmanGap[];
}

export interface FeynmanGapUpdate {
  key: string;
  score: number;
  weight: number;
  evidence_quote: string;
  comment: string;
  evidence_valid: boolean;
  evidence_reason?: string;
}

// ---- R35 S3：挑战题池（**完全不上算**；永不出现在默认流程） ----
export interface ChallengeQuestion {
  prompt_md: string;
  answer_hint_md: string;
  why_hard_md: string;
  difficulty: number;
}

export interface ChallengeLast {
  correct: boolean;
  score: number;
  feedback_md: string;
  better_md: string;
}

export interface ChallengeView {
  /** 后端直出的**显式标注**（UI 必须展示）："挑战题：需要讲解之外的知识，答不出不影响任何进度" */
  notice: string;
  /** 单题三态：idle（无题）/ offered（已生成，可开始作答）/ answering / graded */
  phase: "idle" | "offered" | "answering" | "graded";
  question: ChallengeQuestion | null;
  last: ChallengeLast | null;
  asked: number;
  answered: number;
  degraded: boolean;
  /** 契约位：恒为 true —— 挑战题不计入任何进度（前端不得据此渲染进度影响） */
  counts_nothing: boolean;
}

// ---- R35 S4：追问必须逐字引用学生原话并指出"这句话缺了什么" ----
export interface FollowupEvidence {
  quote: string;
  missing: string;
}

export interface ReteachPayload {
  reason: string;
  message_md: string;
  lecture_md: string;
  missing_dimensions: { key: string; description: string }[];
}

export interface ProfileData {
  user_id: string;
  preferred_explanation_depth: number;
  preferred_examples: string[];
  error_profile: Record<string, number>;
  styling_notes: string[];
  session_counts: Record<string, number>;
  model_mode: "smart" | "light" | "deep"; // R12：自动 | ⚡快 | 🧠深度
}

export interface ConfigModels {
  provider: string;
  base_url: string;
  tiers: { heavy: { model: string }; light: { model: string } };
  configured: boolean;
}

export interface FeynmanHistoryItem {
  id: number;
  node_id: string;
  node_title?: string;
  transcript: string;
  verdict: string;
  score: number | null;
  meta: Record<string, unknown>;
  created_at: string;
}

// ---- 关卡地图（阶段 2 / docs/10 §2.1） ----
export interface CampaignNode {
  id: string;
  title: string;
  kind: "normal" | "boss";
  state: string;
}
export interface CampaignGroup {
  topic: string;
  completed: boolean;
  progress: { mastered: number; total: number };
  nodes: CampaignNode[];
  boss: { id: string; title: string; state: string } | null;
}
export interface CampaignLevel {
  level: string;
  unlocked: boolean;
  groups: CampaignGroup[];
}
export interface CampaignData {
  levels: CampaignLevel[];
  next: { level: string; topic: string; key: string } | null;
  next_generating: boolean;
}

// ---- 内容自续（阶段 3 / docs/10 §2.3） ----
export interface SelfExtendStatus {
  levels: string[];
  active_level: string | null;
  ratio: number | null;
  pending_topics: string[];
  running: boolean;
  last_status: string;
  last_summary: string;
  last_at: string | null;
}
