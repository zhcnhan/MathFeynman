// 设置页（docs/07：Dashboard/Review 之外 + 画像手调 docs/06 §1；R12 模型模式三档）。
import { useEffect, useState } from "react";
import { api, ConfigModels, ProfileData } from "../api";
import ModelModeSwitch from "../components/ModelModeSwitch";
import { ModelMode } from "../components/ModelMode";

export default function SettingsPage() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [cfg, setCfg] = useState<ConfigModels | null>(null);
  const [depth, setDepth] = useState(2);
  const [modelMode, setModelMode] = useState<ModelMode>("smart");
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
  }, []);

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
      </div>
    </div>
  );
}

function describe(d: number): string {
  if (d <= 2) return "直觉类比优先，避免术语压力";
  if (d === 3) return "平衡：类比 + 简要推导";
  return "严格推导优先";
}
