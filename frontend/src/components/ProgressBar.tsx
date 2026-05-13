interface ProgressBarProps {
  value: number;
  max?: number;
  color?: string;
  showPct?: boolean;
  height?: number;
}

export function ProgressBar({
  value,
  max = 1,
  color = "#10b981",
  showPct = true,
  height = 6,
}: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="hstack gap-2" style={{ width: "100%" }}>
      <div className="bar" style={{ flex: 1, height }}>
        <span
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${color}, ${color}dd)`,
          }}
        />
      </div>
      {showPct && (
        <span
          className="mono"
          style={{
            fontSize: 11,
            color: "var(--text-dim)",
            minWidth: 38,
            textAlign: "right",
          }}
        >
          {pct.toFixed(0)}%
        </span>
      )}
    </div>
  );
}
