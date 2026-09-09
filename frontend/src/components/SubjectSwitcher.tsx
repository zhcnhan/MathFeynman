// 顶部学科切换下拉：math → 原仪表盘（数学地图）；其它学科 → 该学科大纲页。
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";

interface SubjectItem {
  id: string;
  label: string;
  kind: string;
}

export default function SubjectSwitcher() {
  const nav = useNavigate();
  const loc = useLocation();
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);

  useEffect(() => {
    api
      .get<{ subjects: SubjectItem[] }>("/subjects")
      .then((r) => setSubjects(r.subjects || []))
      .catch(() => setSubjects([]));
  }, []);

  // 当前学科：/subjects/:id → id；首页 → math；其余空
  const m = loc.pathname.match(/^\/subjects\/([^/]+)/);
  const active =
    loc.pathname === "/" ? "math" : m ? decodeURIComponent(m[1]) : "";

  const onChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value;
    if (!v) return;
    nav(v === "math" ? "/" : `/subjects/${encodeURIComponent(v)}`);
  };

  if (!subjects.length) return null;
  return (
    <span className="subject-switch" style={{ marginLeft: 6 }}>
      <select
        value={active}
        onChange={onChange}
        style={{ padding: "3px 6px", borderRadius: 6, border: "1px solid #c5cdd6" }}
        title="切换学科"
      >
        <option value="" disabled>学科…</option>
        <option value="math">数学（预置）</option>
        {subjects
          .filter((s) => s.id !== "math")
          .map((s) => (
            <option key={s.id} value={s.id}>{s.label}（{s.id}）</option>
          ))}
      </select>
    </span>
  );
}
