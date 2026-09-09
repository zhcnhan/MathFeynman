import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

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
  outline: OutlineSummary | null;
}

export default function SubjectsPage() {
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [label, setLabel] = useState("");
  const [desc, setDesc] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await api.get<{ subjects: SubjectItem[] }>("/subjects");
      setSubjects(r.subjects);
    } catch (e) {
      setErr(String(e));
    }
  };
  useEffect(() => {
    void load();
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

  return (
    <div>
      <h1>学科（Subjects）</h1>
      {err && <div className="banner error">{err}</div>}
      <div className="grid">
        {subjects.map((s) => (
          <Link key={s.id} to={`/subjects/${s.id}`} style={{ textDecoration: "none", color: "inherit" }}>
            <div className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>{s.label}</strong>
                <span className={`badge ${s.kind === "preset" ? "" : "pass"}`}>
                  {s.kind === "preset" ? "预置" : "自建"}
                </span>
              </div>
              <div className="dim">{s.id}</div>
              {s.description && <div className="dim">{s.description}</div>}
              <div className="dim" style={{ marginTop: 6 }}>
                {s.outline
                  ? `大纲 v${s.outline.revision}（${s.outline.status}/${s.outline.source}）· ${s.outline.units} 单元`
                  : "尚无大纲（点击起草）"}
              </div>
            </div>
          </Link>
        ))}
      </div>
      <div className="card">
        <h2>新建学科（自定义 · docs/14 通用教练）</h2>
        <div className="input-row" style={{ margin: "6px 0" }}>
          <input placeholder="学科名称（必填）" value={label}
                 onChange={(e) => setLabel(e.target.value)} style={{ padding: 7, borderRadius: 8, border: "1px solid #c5cdd6" }} />
          <input placeholder="学科 id（小写字母数字连字符；留空自动）" value={subjectId}
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
