import type { ConfidenceLevel } from "@/lib/confidence";

interface ConfidenceBadgeProps {
  level: ConfidenceLevel;
}

const CFG: Record<
  ConfidenceLevel,
  { icon: string; label: string; fg: string; bg: string; border: string }
> = {
  strong: {
    icon: "🔥",
    label: "Strong",
    fg: "#fb923c",
    bg: "rgba(251, 146, 60, 0.12)",
    border: "rgba(251, 146, 60, 0.3)",
  },
  moderate: {
    icon: "✓",
    label: "Moderate",
    fg: "#10b981",
    bg: "rgba(16, 185, 129, 0.12)",
    border: "rgba(16, 185, 129, 0.3)",
  },
  marginal: {
    icon: "⚡",
    label: "Marginal",
    fg: "#f59e0b",
    bg: "rgba(245, 158, 11, 0.12)",
    border: "rgba(245, 158, 11, 0.3)",
  },
  none: {
    icon: "—",
    label: "No Edge",
    fg: "#5a6782",
    bg: "rgba(90, 103, 130, 0.08)",
    border: "rgba(90, 103, 130, 0.2)",
  },
};

export function ConfidenceBadge({ level }: ConfidenceBadgeProps) {
  const cfg = CFG[level];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "4px 9px",
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        borderRadius: 6,
        color: cfg.fg,
        fontSize: 11.5,
        fontWeight: 600,
        letterSpacing: "0.01em",
      }}
    >
      <span>{cfg.icon}</span>
      <span>{cfg.label}</span>
    </span>
  );
}
