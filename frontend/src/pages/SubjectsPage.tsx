import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { PageHead } from "../components/ui";

interface OutlineSummary {
  exists: boolean;
  revision: number;
  status: string;
  source: string;
  schema_version: number;
  units: number;
  groups: string[];
  updated_at: string;
}
interface SubjectItem {
  id: string;
  label: string;
  kind: string;
  description: string;
  enabled: boolean;
  removed_at?: string | null;
  source_policy?: string;
  outline: OutlineSummary | null;
}

// C3（docs/14 §9 / R23 B4）：学科列表 = 学科管理入口——"启用"与"已移除（可恢复）"分组；
// 移除/恢复、来源策略与材料管理（大纲页）收敛到同一管理语义（math 不提供"连同文件删除"）。
export default function SubjectsPage() {
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [label, setLabel] = useState("");
  const [desc, setDesc] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await api.get<{ subjects: SubjectItem[] }>("/subjects?include_removed=1");
      setSubjects(r.subjects);
    } catch (e) {
      setErr(String(e));
    }
  };
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async () => {
    setErr("");
    setBusy(true);
    try {
      await api.post("/subjects", {
        label,
        description: desc,
        subject_id: subjectId.trim() || undefined,
      });
      setLabel("");
      setDesc("");
      setSubjectId("");
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    setErr("");
    setBusy(true);
    try {
      await fn();
      await load();
      setErr(okMsg); // 复用横幅显示成功提示
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const enabledList = subjects.filter((s) => s.enabled);
  const removedList = subjects.filter((s) => !s.enabled);

  const SubjectCard = ({ s }: { s: SubjectItem }) => (
    <div className="card" style={{ opacity: s.enabled ? 1 : 0.72 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Link to={`/subjects/${s.id}`} style={{ textDecoration: "none", color: "inherit" }}>
          <strong>{s.label}</strong>
        </Link>
        <span className={`badge ${!s.enabled ? "deferred" : s.kind === "preset" ? "" : "pass"}`}>
          {!s.enabled ? "已停用" : s.kind === "preset" ? "预置" : "自建"}
        </span>
      </div>
      <div className="dim">{s.id} · 来源策略 {s.source_policy ?? "ai"}</div>
      {s.description && <div className="dim">{s.description}</div>}
      <div className="dim" style={{ marginTop: 6 }}>
        {s.outline
          ? `大纲 v${s.outline.revision}（${s.outline.status}/${s.outline.source}）· ${s.outline.units} 单元`
          : "尚无大纲"}
      </div>
      <div className="input-row" style={{ marginTop: 8, flexWrap: "wrap", gap: 6 }}>
        {s.enabled ? (
          <>
            <Link className="button-link" to={`/subjects/${s.id}`}>大纲管理 →</Link>
            <button className="ghost" disabled={busy}
                    onClick={() => {
                      if (window.confirm(`移除学科「${s.label}」？（停用隐藏、清进度；大纲/内容文件留盘可随时重新启用）`)) {
                        void act(() => api.del(`/subjects/${s.id}`), "✅ 已移除（见下方「已移除」分组，可重新启用）");
                      }
                    }}>
              移除（停用）
            </button>
          </>
        ) : (
          <>
            <button className="primary" disabled={busy}
                    onClick={() => void act(() => api.post(`/subjects/${s.id}/enable`), "✅ 已重新启用（内容/大纲已恢复）")}>
              重新启用
            </button>
            <span className="dim" style={{ fontSize: 12 }}>
              {s.removed_at ? `移除于 ${String(s.removed_at).slice(0, 10)}` : "已停用"}
            </span>
          </>
        )}
        {s.kind !== "preset" && (
          <button className="ghost" disabled={busy}
                  onClick={() => {
                    if (window.confirm(`彻底删除「${s.label}」连同全部内容/材料文件？（不可恢复）`)) {
                      void act(() => api.del(`/subjects/${s.id}?hard=true`), "✅ 已彻底删除");
                    }
                  }}>
            连同文件删除
          </button>
        )}
      </div>
      {s.kind === "preset" && (
        <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
          预置学科仅可停用/重新启用；内容文件与 roadmap 受治理，不提供"连同文件删除"。
        </div>
      )}
    </div>
  );

  return (
    <div>
      <PageHead
        title="学科（Subjects · 管理）"
        sub="自己建学科、启用或移除都在这里；每个学科的内容与进度互相独立。"
      />
      {err && <div className={`banner ${err.startsWith("✅") ? "ok" : "error"}`}>{err}</div>}

      <div className="section-title">启用中</div>
      <div className="grid" style={{ marginTop: 4 }}>
        {enabledList.length === 0 ? (
          <p className="empty">暂无启用中的学科。可新建自定义学科，或在下方「已移除」中重新启用。</p>
        ) : (
          enabledList.map((s) => <SubjectCard key={s.id} s={s} />)
        )}
      </div>

      <h2 style={{ marginTop: 16 }}>已移除（大纲/内容文件留盘 · 可重新启用）</h2>
      <div className="grid" style={{ marginTop: 4 }}>
        {removedList.length === 0 ? (
          <p className="empty">无已移除学科。</p>
        ) : (
          removedList.map((s) => <SubjectCard key={s.id} s={s} />)
        )}
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <h2>新建学科</h2>
        <div className="input-row" style={{ margin: "6px 0" }}>
          <input placeholder="学科名称（必填）" value={label}
                 onChange={(e) => setLabel(e.target.value)} style={{ padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }} />
          <input placeholder="学科代号（小写字母/数字/短横线；留空自动生成）" value={subjectId}
                 onChange={(e) => setSubjectId(e.target.value)} style={{ padding: 7, borderRadius: 8, border: "1px solid #c5cdd6", width: 280 }} />
        </div>
        <div className="input-row" style={{ margin: "6px 0" }}>
          <input placeholder="学习目标/简介（选填，供 AI 起草参考）" value={desc}
                 onChange={(e) => setDesc(e.target.value)}
                 style={{ flex: 1, padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }} />
          <button className="primary" onClick={create} disabled={busy || !label.trim()}>创建学科</button>
        </div>
      </div>
    </div>
  );
}
