// 后端客户端（docs/06）：统一 JSON、错误契约 {error:{code,message}}。
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const started = performance.now();
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let code = "http_error";
    let message = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as ApiErrorBody;
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      /* 非 JSON 错误体 */
    }
    console.warn(`[api] ${init?.method ?? "GET"} ${path} -> ${res.status} code=${code} in ${Math.round(performance.now() - started)}ms`, message);
    throw new ApiError(code, message);
  }
  const data = (await res.json()) as T;
  console.debug(`[api] ${init?.method ?? "GET"} ${path} -> 200 in ${Math.round(performance.now() - started)}ms`);
  return data;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
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
    throw new ApiError("stream_http_error", `HTTP ${res.status}`);
  }
  const ctype = res.headers.get("content-type") ?? "";
  if (!ctype.includes("text/event-stream")) {
    // 服务端未能进入流模式（回退整体 JSON 或错误体）
    const body = await res.json().catch(() => null);
    if (body && body.error) throw new ApiError(body.error.code, body.error.message);
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
