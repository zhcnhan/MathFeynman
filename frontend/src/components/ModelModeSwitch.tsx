// R12：模型模式即时切换条（设置页 / 会话页头部共用）
import { ModelMode, MODE_OPTIONS } from "./ModelMode";

interface Props {
  value: ModelMode;
  onChange: (mode: ModelMode) => void;
  disabled?: boolean;
}

export default function ModelModeSwitch({ value, onChange, disabled }: Props) {
  return (
    <div className="mode-switch" role="group" aria-label="模型模式">
      {MODE_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`seg ${value === opt.value ? "active" : ""}`}
          disabled={disabled}
          title={opt.title}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
