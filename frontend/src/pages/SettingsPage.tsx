// 设置页（docs/07：Dashboard/Review 之外 + 画像手调 docs/06 §1；R12 模型模式三档；
// R39 §2/§3：提示词页入口 + 开发者/调试模式开关 + AI 对话记录入口）。
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ConfigModels, ProfileData } from "../api";
import ModelModeSwitch from "../components/ModelModeSwitch";
import { ModelMode } from "../components/ModelMode";

type AppSettings = {
  developer_mode: boolean;
  model?: ModelSettings;
  ai_trace: { dir: string; keep_days: number };
};

// R56 第 0 步：模型与 Key（页面设置 > 配置文件 > 程序默认；接口只回掩码，永不回完整 Key）
type ModelSettings = {
  provider: string;
  provider_label: string;
  providers: { key: string; label: string }[];
  configured: boolean;
  api_key_masked: string;
  api_key_source_zh: string;
  memory_only: boolean;
  base_url: string;
  base_url_source_zh: string;
  heavy: string;
  heavy_source_zh: string;
  light: string;
  light_source_zh: string;
  max_tokens_per_day: number;
  daily_source_zh: string;
  /** R57：读图用的模型（留空＝跟随文本模型） */
  vision_model?: string;
  vision_model_set?: string;
  vision_model_source_zh?: string;
  vision_ok?: boolean;
  vision_note_zh?: string;
  key_notice_zh: string;
  need_key_zh: string;
};

type TestResult = { ok: boolean; reason_zh: string; model: string; latency_ms: number };

export default function SettingsPage() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [cfg, setCfg] = useState<ConfigModels | null>(null);
  const [depth, setDepth] = useState(2);
  const [modelMode, setModelMode] = useState<ModelMode>("smart");
  const [app, setApp] = useState<AppSettings | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // R56：模型与 Key（表单草稿与生效值分开——留空＝不改）
  const [model, setModel] = useState<ModelSettings | null>(null);
  const [keyDraft, setKeyDraft] = useState("");
  const [provider, setProvider] = useState("deepseek");
  const [baseUrl, setBaseUrl] = useState("");
  const [heavy, setHeavy] = useState("");
  const [light, setLight] = useState("");
  const [visionModel, setVisionModel] = useState("");   // R57：读图用的模型（留空＝跟随快档）
  const [daily, setDaily] = useState("0");
  const [memoryOnly, setMemoryOnly] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);

  const applyModel = (m: ModelSettings) => {
    setModel(m);
    setProvider(m.provider);
    setBaseUrl(m.base_url);
    setHeavy(m.heavy);
    setLight(m.light);
    setVisionModel(m.vision_model_set ?? "");
    setDaily(String(m.max_tokens_per_day || 0));
    setMemoryOnly(!!m.memory_only);
  };

  useEffect(() => {
    api
      .get<ProfileData>("/profile")
      .then((p) => {
        setProfile(p);
        setDepth(p.preferred_explanation_depth);
        setModelMode(p.model_mode ?? "smart");
      })
      .catch((e) => setErr((e as Error).message));
    api
      .get<ConfigModels>("/config/models")
      .then(setCfg)
      .catch(() => setCfg(null));
    // R39 §3：开发者/调试模式（决定界面入口是否出现；审计本身默认记录）
    api
      .get<AppSettings>("/settings")
      .then((s) => {
        setApp(s);
        if (s.model) applyModel(s.model);
      })
      .catch(() => setApp(null));
    // R56 第 0 步：模型与 Key 的当前状态（只回掩码）
    api
      .get<ModelSettings>("/settings/model")
      .then(applyModel)
      .catch(() => setModel(null));
  }, []);

  const saveModel = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    setTestResult(null);
    try {
      const body: Record<string, unknown> = {
        provider,
        base_url: baseUrl,
        heavy,
        light,
        vision_model: visionModel.trim(),
        max_tokens_per_day: Number(daily || 0),
        memory_only: memoryOnly,
      };
      if (keyDraft.trim()) body.api_key = keyDraft.trim();
      const next = await api.put<ModelSettings>("/settings/model", body);
      applyModel(next);
      setKeyDraft("");
      setMsg(next.configured ? "已保存模型设置（Key 不回显，只显示后 4 位）。" : "已保存；还没有填 Key，AI 功能暂时用不了。");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const clearKey = async () => {
    setBusy(true);
    try {
      applyModel(await api.put<ModelSettings>("/settings/model", { api_key: "" }));
      setKeyDraft("");
      setMsg("已清除 Key（AI 功能会停用，直到你重新填）。");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const testConnection = async () => {
    setBusy(true);
    setTestResult(null);
    try {
      setTestResult(await api.post<TestResult>("/settings/model/test", {}));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggleDev = async (on: boolean) => {
    try {
      const next = await api.put<AppSettings>("/settings", { developer_mode: on });
      setApp(next);
      setMsg(on ? "已开启开发者/调试模式：侧栏出现「AI 对话记录」入口。" : "已关闭开发者/调试模式。");
      window.dispatchEvent(new Event("yanhui:settings-changed"));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const saveDepth = async () => {
    try {
      const p = await api.patch<ProfileData>("/profile", { preferred_explanation_depth: depth });
      setProfile(p);
      setMsg("已保存解释深度偏好。");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const changeModelMode = async (mode: ModelMode) => {
    setModelMode(mode);
    try {
      const p = await api.patch<ProfileData>("/profile", { model_mode: mode });
      setProfile(p);
      setMsg(`已切换模型模式：${mode === "light" ? "⚡ 快" : mode === "deep" ? "🧠 深度" : "自动"}。`);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="settings-page">
      <h1>设置</h1>
      {msg && <div className="banner ok">{msg}</div>}
      {err && <div className="banner error">{err}</div>}
      <div className="grid">
        <section className="card">
          <h2>模型模式</h2>
          <ModelModeSwitch value={modelMode} onChange={(m) => void changeModelMode(m)} />
          <p className="dim">
            自动 = 一般内容用快模型，难题和纠错自动换更强的；⚡ 快 = 一直用快模型；
            🧠 深度 = 一直用最强模型。讲解和评分卡会标出这次用的是哪一档，学习页顶部随时能切换。
          </p>
          <h2>讲解偏好</h2>
          <label>解释深度（1 直觉类比 → 5 严格推导）</label>
          <div className="depth-row">
            {[1, 2, 3, 4, 5].map((d) => (
              <button key={d} className={depth === d ? "depth active" : "depth"} onClick={() => setDepth(d)}>
                {d}
              </button>
            ))}
            <button className="primary" onClick={() => void saveDepth()}>保存</button>
          </div>
          <p className="dim">当前深度：{depth} · {profile ? describe(depth) : ""}</p>
          {profile && (
            <>
              <h2>错误画像（累计）</h2>
              <div>
                {Object.entries(profile.error_profile).map(([k, v]) => (
                  <span key={k} className="chip">{k}×{v}</span>
                ))}
                {Object.keys(profile.error_profile).length === 0 && <span className="empty">暂无记录</span>}
              </div>
            </>
          )}
        </section>
        <section className="card">
          <h2>模型与 Key</h2>
          {!model?.configured && <div className="banner warn">{model?.need_key_zh ?? "还没有配模型 Key。"}</div>}
          <p className="dim" style={{ fontSize: 13 }}>
            在这里填就行（不用改程序文件）。填完点「保存」，再点「测试连接」确认能用。
            这里的设置优先于程序文件里的设置，改了立刻生效。
          </p>
          <label>服务商</label>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            {(model?.providers ?? [{ key: "deepseek", label: "DeepSeek（默认）" }]).map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </select>
          <label>API Key</label>
          <input
            type="password"
            autoComplete="off"
            placeholder={model?.configured ? `已配置（${model.api_key_masked}）——留空表示不改` : "把 Key 粘到这里"}
            value={keyDraft}
            onChange={(e) => setKeyDraft(e.target.value)}
            style={{ width: "100%" }}
          />
          <div className="dim" style={{ fontSize: 12 }}>
            当前：{model?.configured ? `已配置（${model.api_key_masked}）` : "未配置"} · 来自：{model?.api_key_source_zh ?? "—"}
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
            <input type="checkbox" checked={memoryOnly} onChange={(e) => setMemoryOnly(e.target.checked)} />
            只放在内存里（关掉程序就要重填；勾上就不写进本地数据）
          </label>
          <label>模型名（快：答疑、分类这类）</label>
          <input value={light} onChange={(e) => setLight(e.target.value)} style={{ width: "100%" }} />
          <label>模型名（深：讲解、评分、难题）</label>
          <input value={heavy} onChange={(e) => setHeavy(e.target.value)} style={{ width: "100%" }} />
          <label>读图用的模型（留空＝跟随上面那个"快"档）</label>
          <input value={visionModel} onChange={(e) => setVisionModel(e.target.value)}
                 placeholder="留空就跟随快档；要单独指定读图的模型时才填"
                 style={{ width: "100%" }} />
          <div className="dim" style={{ fontSize: 12 }}>
            这一项来自：{model?.vision_model_source_zh ?? "—"}
            {model?.vision_note_zh ? `；${model.vision_note_zh}` : ""}
          </div>
          <label>服务地址</label>
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} style={{ width: "100%" }} />
          <div className="dim" style={{ fontSize: 12 }}>
            这一项来自：{model?.base_url_source_zh ?? "—"}（模型名同理：快 {model?.light_source_zh ?? "—"} /
            深 {model?.heavy_source_zh ?? "—"}）
          </div>
          <label>每天最多用多少 token（0 = 不限）</label>
          <input
            type="number"
            min={0}
            value={daily}
            onChange={(e) => setDaily(e.target.value)}
            style={{ width: 160 }}
          />
          <div className="dim" style={{ fontSize: 12 }}>这一项来自：{model?.daily_source_zh ?? "—"}</div>
          <div className="depth-row" style={{ marginTop: 10 }}>
            <button className="primary" disabled={busy} onClick={() => void saveModel()}>保存</button>
            <button className="ghost" disabled={busy} onClick={() => void testConnection()}>测试连接</button>
            {model?.configured && (
              <button className="ghost" disabled={busy} onClick={() => void clearKey()}>清除 Key</button>
            )}
          </div>
          {testResult && (
            <div className={testResult.ok ? "banner ok" : "banner error"}>
              {testResult.reason_zh}
              {testResult.latency_ms ? `（耗时 ${testResult.latency_ms} 毫秒）` : ""}
            </div>
          )}
          <p className="dim" style={{ fontSize: 12 }}>{model?.key_notice_zh ?? "Key 存在这台机器上，别把本地数据文件发给别人。"}</p>
        </section>
        <section className="card">
          <h2>当前生效值（只读，要改就在上面改）</h2>
          {cfg ? (
            <ul className="plain">
              <li>服务商：{cfg.provider_label ?? cfg.provider}</li>
              <li>服务地址：{cfg.base_url}</li>
              <li>讲解/评分用的模型：{cfg.tiers.heavy.model}</li>
              <li>答疑/分类用的模型：{cfg.tiers.light.model}</li>
              <li className={cfg.configured ? "ok" : "warn"}>
                {cfg.configured
                  ? `已配置 Key（${cfg.api_key_masked || "已保存"}）→ AI 功能可用`
                  : "还没配 Key → AI 功能用不了；去上面的「模型与 Key」里填一下"}
              </li>
            </ul>
          ) : (
            <p className="empty">暂时读不到模型设置，刷新页面试试</p>
          )}
        </section>
        <section className="card">
          <h2>提示词（可以自己改）</h2>
          <p className="dim" style={{ fontSize: 13 }}>
            程序每次问 AI 用的话都在这里，可以自己改，也能一键恢复默认。改完下一次就生效；
            删掉必须留的内容会被拒绝保存（会有中文说明）。
          </p>
          <p>
            <Link className="button-link" to="/prompts">打开「提示词」页 →</Link>
          </p>
          <h2>高级：查看 AI 对话记录</h2>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={!!app?.developer_mode}
              onChange={(e) => void toggleDev(e.target.checked)}
            />
            开启「AI 对话记录」（排查问题用，平时可以不开）
          </label>
          <p className="dim" style={{ fontSize: 12 }}>
            这个开关只决定侧栏里是否出现「AI 对话记录」入口；程序**一直在记录**每次问 AI 的完整内容，
            方便出问题时回看。记录存在本地文件里（{app?.ai_trace?.dir ?? "—"}），页面上看的时候不是边生成边刷；
            出错和没用上的内容会排在前面、标红。
            {app?.ai_trace && (
              <>
                <br />
                记录保存 {app.ai_trace.keep_days} 天后自动清理（清理会写进「记录」页）。
              </>
            )}
          </p>
          {app?.developer_mode && (
            <p>
              <Link className="button-link" to="/ai-traces">打开「AI 对话记录」→</Link>
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

function describe(d: number): string {
  if (d <= 2) return "直觉类比优先，避免术语压力";
  if (d === 3) return "平衡：类比 + 简要推导";
  return "严格推导优先";
}
