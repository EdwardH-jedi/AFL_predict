import type { TooltipProps } from "recharts";

interface Props extends TooltipProps<number, string> {
  formatter?: (value: number, name?: string) => string;
  labelFormatter?: (label: string | number) => string;
}

export function ChartTooltip({
  active,
  payload,
  label,
  formatter,
  labelFormatter,
}: Props) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div
      style={{
        background: "rgba(11, 18, 32, 0.96)",
        border: "1px solid var(--line-strong)",
        borderRadius: 8,
        padding: "8px 10px",
        fontSize: 12,
        boxShadow: "0 8px 20px rgba(0,0,0,0.4)",
        backdropFilter: "blur(8px)",
      }}
    >
      <div
        style={{
          color: "var(--text-mute)",
          fontSize: 11,
          marginBottom: 4,
          fontFamily: "JetBrains Mono, monospace",
        }}
      >
        {labelFormatter ? labelFormatter(label as string | number) : String(label ?? "")}
      </div>
      {payload.map((p, i) => (
        <div
          key={i}
          className="hstack gap-2"
          style={{ fontFamily: "JetBrains Mono, monospace" }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 2,
              background: (p.color as string) || (p.payload as { fill?: string }).fill || "#7dd3fc",
            }}
          />
          <span style={{ color: "var(--text-dim)" }}>{p.name}</span>
          <span
            style={{ color: "var(--text)", fontWeight: 600, marginLeft: "auto" }}
          >
            {formatter ? formatter(p.value as number, p.name as string) : String(p.value)}
          </span>
        </div>
      ))}
    </div>
  );
}
