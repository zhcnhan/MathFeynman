// R39 §3 · **AI 对话记录**（提示词监听 / 对话审计；仅"开发者 / 调试"模式开启后可见）
// 硬约束：**非流式**（加载完再看，一次拉全）；失败与丢弃**置顶并红色标记**；
//         点开一条：上=发给 AI 的完整内容，下=AI 返回的完整内容（分区折叠、等宽字体、可全文展开）；
//         长文本默认收起（>10 万字不卡界面：详情按需请求 + 折叠渲染 + 仅前 20 万字给浏览器）。
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const FULL_RENDER_CAP = 200000; // 单块最多渲染 20 万字（再长只提示字符数，避免浏览器卡死）

type TraceItem = {
  id: number;
  at: string;
  call_name: string;
  call_label: string;
  subject_id: string;
  unit_id: string;
  tier: string;
  model: string;
  ok: boolean;
  outcome: string;
  outcome_label: string;
  retries: number;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  error: string;
  trace_path: string;
  trace_chars: number;
  system_preview: string;
  user_preview: string;
  response_preview: string;
  parse_result: string;
  prompt_versions: string;
  is_failure: boolean;
};

type TraceDetail = TraceItem & {
  full: { system: string; user: string; response: string; parse_result: string; meta: string };
  note: string;
  file_exists: boolean;
};

type ListResp = {
  items: TraceItem[];
  count: number;
  total: number;
  call_sites: { name: string; label: string }[];
  outcomes: { key: string; label: string }[];
  trace_dir: string;
  keep_days: number;
};

const OUTCOME_CLS: Record<string, string> = {
  adopted: "pass",
  degraded: "deferred",
  dropped: "error",
  failed: "error",
};

function Meta({ d }: { d: TraceDetail }) {
  return (
    <div className="dim" style={{ fontSize: 12, marginBottom: 6 }}>
      用途：<strong>{d.call_label}</strong> · 模型 {d.model || "—"} ·
      用量 {d.prompt_tokens}+{d.completion_tokens} 字 · 用时 {d.latency_ms} ms · 重试 {d.retries} 次 ·
      结果 <span className={`badge ${OUTCOME_CLS[d.outcome] ?? ""}`}>{d.outcome_label}</span>
      {d.subject_id ? ` · 学科 ${d.subject_id}` : ""}
      {d.unit_id ? ` · 单元 ${d.unit_id}` : ""}
    </div>
  );
}

function Block({ title, text }: { title: string; text: string }) {
  const body = text.length > FULL_RENDER_CAP ? text.slice(0, FULL_RENDER_CAP) : text;
  return (
    <details style={{ marginTop: 8 }} open={false}>
      <summary>
        {title}（{(text || "").length.toLocaleString("zh-CN")} 字）
      </summary>
      <pre
        style={{
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontFamily: "Consolas, Menlo, monospace",
          fontSize: 12,
          background: "#f7f9fb",
          border: "1px solid #e3e9ef",
          borderRadius: 8,
          padding: 8,
          maxHeight: 460,
          overflow: "auto",
        }}
      >
        {body}
        {text.length > FULL_RENDER_CAP && (
          <span className="dim">
            {"\n\n…（超出界面一次渲染上限，仅显示前 "}
            {FULL_RENDER_CAP.toLocaleString("zh-CN")}
            {" 字；完整内容已保存成文件（位置见下方「检查结果与本次参数」）"}
          </span>
        )}
      </pre>
    </details>
  );
}

export default function AiTracePage() {
  const [data, setData] = useState<ListResp | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [callName, setCallName] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [subjects, setSubjects] = useState<{ id: string; label: string }[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const q = new URLSearchParams();
      if (onlyFailed) q.set("only_failed", "true");
      if (callName) q.set("call_name", callName);
      if (subjectId) q.set("subject_id", subjectId);
      q.set("limit", "50");
      setData(await api.get<ListResp>(`/ai-traces?${q.toString()}`));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [onlyFailed, callName, subjectId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .get<{ subjects: { id: string; label: string }[] }>("/subjects?include_removed=1")
      .then((r) => setSubjects(r.subjects))
      .catch(() => setSubjects([]));
  }, []);

  const open = async (id: number) => {
    setErr("");
    try {
      setDetail(await api.get<TraceDetail>(`/ai-traces/${id}`));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const cleanup = async () => {
    if (!window.confirm("清理过期记录？（清理会写进「记录」页，不会悄悄删）")) return;
    try {
      const r = await api.post<{ count: number; keep_days: number }>("/ai-traces/cleanup", {});
      setMsg(`已清理 ${r.count} 份过期记录（保存 ${r.keep_days} 天），这次清理已写进「记录」页。`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div>
      <h1>AI 对话记录</h1>
      <div className="banner warn" style={{ fontSize: 13 }}>
        只存在你本机：这里能看到每次发给 AI 的内容和它的回答。文字较长，默认收起，展开就是完整原文。
        记录里不会出现 API Key（已自动遮掉）。保存 {data?.keep_days ?? "—"} 天。
      </div>
      {err && <div className="banner error">{err}</div>}
      {msg && <div className="banner ok">{msg}</div>}

      <div className="card">
        <div className="input-row" style={{ gap: 10, flexWrap: "wrap" }}>
          <label>
            <input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} />{" "}
            只看出错的
          </label>
          <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
            <option value="">全部学科</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <select value={callName} onChange={(e) => setCallName(e.target.value)}>
            <option value="">全部用途</option>
            {(data?.call_sites ?? []).map((c) => (
              <option key={c.name} value={c.name}>{c.label}</option>
            ))}
          </select>
          <button className="ghost" onClick={() => void load()}>刷新</button>
          <button className="ghost" onClick={() => void cleanup()}>清理过期记录</button>
        </div>
        <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
          共 {data?.total ?? 0} 次。程序一直在记（不需要手动开开关）；出错的排在最前面。
        </div>
      </div>

      <div className="card">
        {(data?.items ?? []).length === 0 && <p className="empty">还没有记录。</p>}
        {(data?.items ?? []).map((t) => (
          <div
            key={t.id}
            style={{
              padding: "6px 0",
              borderBottom: "1px solid #eef2f6",
              borderLeft: t.is_failure ? "3px solid #b3261e" : "3px solid transparent",
              paddingLeft: 8,
            }}
          >
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span className="dim" style={{ fontSize: 12 }}>
                {t.at.replace("T", " ").replace("+00:00", " UTC")}
              </span>
              <strong>{t.call_label}</strong>
              <span className={`badge ${OUTCOME_CLS[t.outcome] ?? ""}`}>{t.outcome_label}</span>
              {t.is_failure && <span className="badge error">需要关注</span>}
              <span className="dim" style={{ fontSize: 12 }}>
                {t.model || "—"} · 用了 {t.prompt_tokens + t.completion_tokens} 字 · {t.latency_ms} ms ·
                重试 {t.retries} 次 · 记录 {t.trace_chars.toLocaleString("zh-CN")} 字
              </span>
              <button className="ghost" onClick={() => void open(t.id)}>看完整对话</button>
            </div>
            {t.error && (
              <div className="dim" style={{ fontSize: 12, color: "#b3261e" }}>问题：{t.error}</div>
            )}
          </div>
        ))}
      </div>

      {detail && (
        <div className="card" style={{ borderColor: detail.is_failure ? "#b3261e" : "#90caf9" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ margin: 0 }}>这一次的完整对话 #{detail.id}</h2>
            <button className="ghost" onClick={() => setDetail(null)}>收起</button>
          </div>
          <Meta d={detail} />
          {detail.note && <div className="banner warn">{detail.note}</div>}
          <h3 style={{ margin: "8px 0 0" }}>发给 AI 的内容</h3>
          <Block title="角色与总纪律" text={detail.full.system} />
          <Block title="这次具体怎么干活" text={detail.full.user} />
          <h3 style={{ margin: "10px 0 0" }}>AI 的回答</h3>
          <Block title="原始回答（未加工）" text={detail.full.response} />
          <details style={{ marginTop: 8 }}>
            <summary>检查结果与本次参数</summary>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{detail.full.parse_result}</pre>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{detail.full.meta}</pre>
            {/* 排查时才需要：记录文件在哪（平时收在折叠里，不打扰普通用户） */}
            <div className="dim" style={{ fontSize: 12, wordBreak: "break-all" }}>
              本次记录存放位置：{detail.trace_path || "（没有单独存文件）"}
              {detail.file_exists ? "" : "（文件已不可读或已清理）"}
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
