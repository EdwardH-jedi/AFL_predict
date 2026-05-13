import { Sparkline } from "./Sparkline";

type Tone = "neutral" | "positive" | "negative" | "accent";

interface StatTileProps {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
  sparkline?: number[];
  trendValue?: number;
}

const TONE_COLOR: Record<Tone, string> = {
  neutral: "#e6ecf7",
  positive: "#10b981",
  negative: "#ef4444",
  accent: "#7dd3fc",
};

export function StatTile({
  label,
  value,
  sub,
  tone = "neutral",
  sparkline,
  trendValue,
}: StatTileProps) {
  const toneColor = TONE_COLOR[tone];
  return (
    <div className="card" style={{ padding: 16 }}>
      <div
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--text-mute)",
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginTop: 6,
          gap: 8,
        }}
      >
        <div
          className="mono"
          style={{
            fontSize: 26,
            fontWeight: 600,
            color: toneColor,
            lineHeight: 1.1,
            letterSpacing: "-0.02em",
          }}
        >
          {value}
        </div>
        {sparkline && sparkline.length >= 2 && (
          <Sparkline data={sparkline} color={toneColor} />
        )}
      </div>
      {sub && (
        <div
          style={{
            marginTop: 6,
            fontSize: 12,
            color: "var(--text-dim)",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          {trendValue != null && (
            <span
              className="mono"
              style={{
                color: trendValue >= 0 ? "var(--green)" : "var(--red)",
                fontWeight: 600,
              }}
            >
              {trendValue >= 0 ? "▲" : "▼"} {Math.abs(trendValue).toFixed(1)}%
            </span>
          )}
          <span>{sub}</span>
        </div>
      )}
    </div>
  );
}
