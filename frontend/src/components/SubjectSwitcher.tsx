// 顶栏学科切换（纯链接式，避免 select 事件歧义）：
// 数学 → 首页仪表盘；其它学科 → /subjects/<id> 大纲页。
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api";

interface SubjectItem {
  id: string;
  label: string;
  kind: string;
}

export default function SubjectSwitcher() {
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);

  useEffect(() => {
    api
      .get<{ subjects: SubjectItem[] }>("/subjects")
      .then((r) => setSubjects(r.subjects || []))
      .catch(() => setSubjects([]));
  }, []);

  if (!subjects.length) return null;
  return (
    <span className="subject-switch" style={{ marginLeft: 4 }}>
      <span className="dim" style={{ fontSize: 12 }}>学科·</span>
      <NavLink to="/" end style={{ marginRight: 4 }}>
        数学
      </NavLink>
      {subjects
        .filter((s) => s.id !== "math")
        .map((s) => (
          <NavLink key={s.id} to={`/subjects/${encodeURIComponent(s.id)}`} style={{ marginRight: 4 }}>
            {s.label}
          </NavLink>
        ))}
    </span>
  );
}
