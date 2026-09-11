// 设置页（docs/07：Dashboard/Review 之外 + 画像手调 docs/06 §1；R12 模型模式三档；
// R39 §2/§3：提示词页入口 + 开发者/调试模式开关 + AI 对话记录入口）。
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ConfigModels, ProfileData } from "../api";
import ModelModeSwitch from "../components/ModelModeSwitch";
import { ModelMode } from "../components/ModelMode";

type AppSettings = {
  developer_mode: boolean;
  ai_trace: { dir: string; keep_days: number };
};

export default function SettingsPage() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [cfg, setCfg] = useState<ConfigModels | null>(null);
  const [depth, setDepth] = useState(2);
  const [modelMode, setModelMode] = useState<ModelMode>("smart");
  const [app, setApp] = useState<AppSettings | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

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
      .then(setApp)
      .catch(() => setApp(null));
  }, []);

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
          <h2>模型配置</h2>
          {cfg ? (
            <ul className="plain">
              <li>Provider：{cfg.provider}</li>
              <li>Base URL：{cfg.base_url}</li>
              <li>重推理档（讲解/费曼）：{cfg.tiers.heavy.model}</li>
              <li>轻档（提示/分类）：{cfg.tiers.light.model}</li>
              <li className={cfg.configured ? "ok" : "warn"}>
                {cfg.configured ? "已配置 API Key → AI 在线模式" : "未配置 API Key → 离线兜底模式"}
              </li>
            </ul>
          ) : (
            <p className="empty">无法读取模型配置</p>
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
