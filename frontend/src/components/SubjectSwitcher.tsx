// 顶栏学科切换（纯链接式，避免 select 事件歧义）：
// 预置学科（当前为 math）→ 首页仪表盘；其它学科 → /subjects/<id> 大纲页。
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
  // R65 任务 A：预置学科（当前为 math）**存在才画**。
  // 以前是 `{preset?.label ?? "数学"}` —— 数学被停用后 /api/subjects 不再返回它，
  // preset 是 undefined，于是画了个字面量「数学」，点它又回主页（主页只列启用中的学科）
  // ⇒ 顶栏挂着一个"点不进去"的死链接。现在没有预置学科就不画这一项。
  const preset = subjects.find((s) => s.id === "math");
  return (
    <span className="subject-switch">
      <span className="dim small">学科·</span>
      {preset && (
        <NavLink to="/" end className="nav-subject">
          {preset.label}
        </NavLink>
      )}
      {subjects
        // 当前假设 math 是唯一预置学科；新增预置学科时按 kind 过滤
        .filter((s) => s.id !== "math")
        .map((s) => (
          <NavLink key={s.id} to={`/subjects/${encodeURIComponent(s.id)}`} className="nav-subject">
            {s.label}
          </NavLink>
        ))}
    </span>
  );
}
