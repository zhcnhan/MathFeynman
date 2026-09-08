// R12：全局模型模式三档即时切换（⚡快 light / 自动 smart / 🧠深度 deep）
// 也导出策略档标签（fast→⚡快 / think→🧠深度），供评分卡/讲解/答疑标注。

export type ModelMode = "smart" | "light" | "deep";

export const MODE_OPTIONS: { value: ModelMode; label: string; title: string }[] = [
  { value: "light", label: "⚡ 快", title: "关闭自动升级触发，省时省钱（college/AI 仍用深度档）" },
  { value: "smart", label: "自动", title: "默认：基础快模型，边缘分/轮次≥2/超纲答疑时自动切深度" },
  { value: "deep", label: "🧠 深度", title: "全部环节使用深度推理模型" },
];

export function modeLabel(mode: ModelMode): string {
  return MODE_OPTIONS.find((m) => m.value === mode)?.label ?? mode;
}

export function tierLabel(strategy?: string | null): string {
  if (strategy === "think") return "🧠 深度";
  if (strategy === "fast") return "⚡ 快";
  return strategy ? `档位 ${strategy}` : "";
}
