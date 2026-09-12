// R39 §1「一切显性」铁则 · **总账页**
// 一处看全部（可按学科/类别筛）；铁则要求"界面必须能看见"，不许拿日志文件当交付。
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import LedgerAlerts, { LedgerEntry } from "../components/LedgerAlerts";
import { PageHead } from "../components/ui";

type CountItem = { key: string; label: string; count: number };
type LedgerResp = {
  entries: LedgerEntry[];
  count: number;
  categories: { key: string; label: string }[];
  counts?: CountItem[];
  note?: string;
};

type SubjectItem = { id: string; label: string; enabled: boolean };

export default function LedgerPage() {
  const [sp, setSp] = useSearchParams();
  const subjectId = sp.get("subject_id") ?? "";
  const category = sp.get("category") ?? "";
  const [data, setData] = useState<LedgerResp | null>(null);
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const q = new URLSearchParams();
      if (subjectId) q.set("subject_id", subjectId);
      if (category) q.set("category", category);
      setData(await api.get<LedgerResp>(`/ledger?${q.toString()}`));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [subjectId, category]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .get<{ subjects: SubjectItem[] }>("/subjects?include_removed=1")
      .then((r) => setSubjects(r.subjects))
      .catch(() => setSubjects([]));
  }, []);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value);
    else next.delete(key);
    setSp(next);
  };

  return (
    <div>
      <PageHead
        title="记录（它做了什么、为什么）"
        sub="程序没有按你预期的方式使用你给的内容时，这里都留了一条中文原因。"
      />
      <div className="card">
        <div className="dim" style={{ fontSize: 13 }}>
          只要程序没有按你预期的方式使用你给的内容，这里都会留下一条记录，写明对象与原因。
          这里能一次看全部：读书情况 / 出题与检查 / 问 AI 的情况 / 章节进度 / 其它
          （学科停用、内容被纠错替换、重新学一遍、提示词改动…）。各学科页面上也会就近提示。
        </div>
        <div className="input-row" style={{ gap: 10, marginTop: 8, flexWrap: "wrap" }}>
          <label className="dim">学科</label>
          <select value={subjectId} onChange={(e) => setFilter("subject_id", e.target.value)}>
            <option value="">全部学科</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}（{s.id}）{s.enabled ? "" : " · 已停用"}
              </option>
            ))}
          </select>
          <label className="dim">类别</label>
          <select value={category} onChange={(e) => setFilter("category", e.target.value)}>
            <option value="">全部类别</option>
            {(data?.categories ?? []).map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
                {data?.counts ? `（${data.counts.find((x) => x.key === c.key)?.count ?? 0}）` : ""}
              </option>
            ))}
          </select>
          <button className="ghost" onClick={() => void load()}>
            刷新
          </button>
        </div>
        {data?.counts && data.counts.some((c) => c.count > 0) && (
          <div className="input-row" style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
            {data.counts.map((c) => (
              <button
                key={c.key}
                className={category === c.key ? "depth active" : "depth"}
                onClick={() => setFilter("category", category === c.key ? "" : c.key)}
                title={`按「${c.label}」筛`}
              >
                {c.label} ×{c.count}
              </button>
            ))}
          </div>
        )}
      </div>

      {err && <div className="banner error">{err}</div>}
      {data?.note && <div className="banner warn">{data.note}</div>}

      <div className="card">
        <h2>记录明细（{data?.count ?? 0} 条，新的在前）</h2>
        {data && data.entries.length === 0 && (
          <p className="empty">
            当前筛选下没有记录。这通常说明一切正常（也可能是筛选条件太窄）。
          </p>
        )}
        {data && data.entries.length > 0 && (
          <div>
            {data.entries.map((e) => (
              <div
                key={e.id ?? `${e.at}-${e.object}`}
                className="row-divider"
                style={{ padding: "6px 0" }}
              >
                <div className="dim" style={{ fontSize: 12 }}>
                  {e.at ? e.at.replace("T", " ").replace("+00:00", " UTC") : ""}
                  {e.subject_id ? ` · 学科 ${e.subject_id}` : ""}
                  {e.unit_id ? ` · 单元 ${e.unit_id}` : ""}
                </div>
                <LedgerAlerts entries={[e]} title="记录" compact />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
