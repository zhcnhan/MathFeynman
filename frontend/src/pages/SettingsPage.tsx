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
          <h2>模型模式（R12）</h2>
          <ModelModeSwitch value={modelMode} onChange={(m) => void changeModelMode(m)} />
          <p className="dim">
            自动 = 基础快模型 + 边缘分/轮次≥2/超纲答疑自动升深度；⚡ 快 = 关闭自动升级（college/AI 仍深度）；
            🧠 深度 = 全部深度。讲解/评分卡会标注本次所用档位，会话页头部可即时切换。
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
          <h2>提示词（R39 §2）</h2>
          <p className="dim" style={{ fontSize: 13 }}>
            程序里用到的**所有**发往模型的提示词都可以在这里改，并随时恢复默认。
            改动立即生效；删掉必填占位符/硬约束会被**中文拒存**。
          </p>
          <p>
            <Link className="button-link" to="/prompts">打开「提示词」页 →</Link>
          </p>
          <h2>开发者 / 调试（R39 §3）</h2>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={!!app?.developer_mode}
              onChange={(e) => void toggleDev(e.target.checked)}
            />
            开启「AI 对话记录」（提示词监听 / 对话审计）
          </label>
          <p className="dim" style={{ fontSize: 12 }}>
            注意：审计**默认记录**（不靠本开关决定“要不要留证据”），本开关只控制界面入口是否出现。
            全文落本地文件（{app?.ai_trace?.dir ?? "—"}），库内只存路径 + 预览 + 字符数；
            界面**不流式**、加载完再看；失败与丢弃项在列表里**置顶并红色标记**。
            {app?.ai_trace && (
              <>
                <br />
                审计目录：{app.ai_trace.dir}（保留期 {app.ai_trace.keep_days} 天；清理会记入总账）
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
