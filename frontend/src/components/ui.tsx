// 界面基础件（R61 任务 0）：折叠区 / 卡片 / 空状态 / 加载 / 图例 / 进度。
// 说明：这里只有"版式与可读性"的东西，没有任何业务判断——
// 页面上的**功能与行为**保持原样，只是把"默认露在外面的东西"收进折叠区与设置开关。
import { ReactNode, useCallback, useState } from "react";

// ---------------------------------------------------------------- 折叠区
const FOLD_PREFIX = "yanhui:fold:";

function readFold(id: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(FOLD_PREFIX + id);
    return raw === null ? fallback : raw === "1";
  } catch {
    return fallback;
  }
}

/**
 * 折叠区：默认只给一行摘要，点开才展开（展开状态记在本机，同一会话/下次打开都记得）。
 *
 * - 子内容**始终挂载**、只是被隐藏 ⇒ 表单里已经填的字、已经加载的数据都**不会丢**；
 * - `summary` 是收起时那一行字（回答"这里有什么、现在什么状态"）；
 * - 折叠**只减少默认噪音**：功能一个不少，展开就能用。
 */
export function Collapsible({
  id, title, summary, defaultOpen = false, children,
}: {
  id: string;
  title: string;
  summary?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(() => readFold(id, defaultOpen));
  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(FOLD_PREFIX + id, next ? "1" : "0");
      } catch {
        /* 隐私模式下写不了就只在本次会话里记 */
      }
      return next;
    });
  }, [id]);

  return (
    <section className={"collapse" + (open ? " open" : "")} data-hidden={open ? "0" : "1"}>
      <button type="button" className="collapse-head" aria-expanded={open} onClick={toggle}>
        <span className="chev" aria-hidden="true">▶</span>
        <span className="collapse-title">{title}</span>
        {summary !== undefined && <span className="collapse-summary">{summary}</span>}
        <span className="badge">{open ? "收起" : "展开"}</span>
      </button>
      <div className="collapse-body">{children}</div>
    </section>
  );
}

// ------------------------------------------------------------------ 卡片
export function Card({
  title, sub, actions, children, className = "", id,
}: {
  title?: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`card ${className}`.trim()} id={id}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <div className="card-sub">{sub}</div>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHead({
  crumb, title, sub, actions,
}: {
  crumb?: ReactNode;
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      {crumb && <div className="crumb">{crumb}</div>}
      <div className="row-between">
        <div>
          <h1>{title}</h1>
          {sub && <div className="sub">{sub}</div>}
        </div>
        {actions && <div className="row">{actions}</div>}
      </div>
    </header>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <div className="section-title">{children}</div>;
}

// -------------------------------------------------------- 空状态 / 加载
export function EmptyState({
  title, hint, action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="big">{title}</div>
      {hint && <div>{hint}</div>}
      {action && <div className="actions" style={{ justifyContent: "center" }}>{action}</div>}
    </div>
  );
}

export function Loading({ what = "正在读取…" }: { what?: string }) {
  return <div className="loading">{what}</div>;
}

// -------------------------------------------------------------- 状态与图例
export const STATE_COLOR: Record<string, string> = {
  locked: "#b7c0cb",
  available: "#2f6fd0",
  learning: "#d99a1f",
  mastered: "#2e7d4f",
  reviewing: "#c96a1b",
  done: "#2e7d4f",
  todo: "#b7c0cb",
};

export const STATE_ZH: Record<string, string> = {
  locked: "还不到时候",
  available: "可以学",
  learning: "正在学",
  mastered: "已掌握",
  reviewing: "该复习了",
  todo: "还没开始",
};

export const STATE_ORDER = ["mastered", "learning", "available", "reviewing", "locked"] as const;

export function stateColor(state: string): string {
  return STATE_COLOR[state] ?? "#b7c0cb";
}

export function Legend({ states = STATE_ORDER as unknown as string[] }: { states?: string[] }) {
  return (
    <div className="map-legend">
      {states.map((s) => (
        <span key={s}><i style={{ background: stateColor(s) }} />{STATE_ZH[s] ?? s}</span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ 进度
export function Progress({ done, total, label }: { done: number; total: number; label?: string }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div>
      <div className="row-between">
        <span className="muted">{label ?? `${done} / ${total}`}</span>
        <span className="muted">{pct}%</span>
      </div>
      <div className="track"><span style={{ width: `${pct}%` }} /></div>
    </div>
  );
}
