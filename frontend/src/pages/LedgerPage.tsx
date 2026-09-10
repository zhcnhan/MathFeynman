// R39 §1「一切显性」铁则 · **总账页**
// 一处看全部（可按学科/类别筛）；铁则要求"界面必须能看见"，不许拿日志文件当交付。
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import LedgerAlerts, { LedgerEntry } from "../components/LedgerAlerts";

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
      <h1>总账（一切显性 · R39 铁则）</h1>
      <div className="card">
        <div className="dim" style={{ fontSize: 13 }}>
          铁则：程序任何时候"没有按用户以为的方式使用他的输入/产出"，都必须被记录、并可见。
          这里是一处看全部的地方——材料吸纳 / 生成与校验 / 模型调用 / 覆盖 / 其它（学科停用、内容被
          纠错替换、复习降级回炉、提示词改动…）。就地提示在各学科页也有。
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
        <h2>账目（{data?.count ?? 0} 条，时间倒序）</h2>
        {data && data.entries.length === 0 && (
          <p className="empty">
            当前筛选下没有账目。这通常意味着：没有发生丢弃/截断/降级/失败（也可能是筛选条件太窄）。
          </p>
        )}
        {data && data.entries.length > 0 && (
          <div>
            {data.entries.map((e) => (
              <div
                key={e.id ?? `${e.at}-${e.object}`}
                style={{ padding: "6px 0", borderBottom: "1px solid #eef2f6" }}
              >
                <div className="dim" style={{ fontSize: 12 }}>
                  {e.at ? e.at.replace("T", " ").replace("+00:00", " UTC") : ""}
                  {e.subject_id ? ` · 学科 ${e.subject_id}` : ""}
                  {e.unit_id ? ` · 单元 ${e.unit_id}` : ""}
                </div>
                <LedgerAlerts entries={[e]} title="账目" compact />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
