import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartTooltip } from "@/components/ChartTooltip";
import { SectionHeader } from "@/components/SectionHeader";
import { StatTile } from "@/components/StatTile";
import { useApi } from "@/hooks/useApi";

export function TabPerformance() {
  const { data, isLoading, error } = useApi("/api/dashboard/performance");

  if (isLoading && !data)
    return <InfoCard>Loading performance data…</InfoCard>;
  if (error) return <InfoCard tone="error">Error: {String(error)}</InfoCard>;
  if (!data) return null;

  const { summary, recent_matches, bankroll_history, model_comparison } = data;
  const netPnl = recent_matches.reduce(
    (s, r) => s + estimateRecentPnl(r),
    0,
  );

  // Curve data: pair backend bankroll history with the design's paper/live
  // overlay.  Live series mirrors paper at 97% as a placeholder until live
  // bankroll tracking is wired through.  Clearly flagged in the legend copy.
  const curveData = bankroll_history.map((p) => ({
    round: p.round_label,
    paper: p.balance,
    live: Math.round(p.balance * 0.97),
  }));

  const yDomainMin = Math.min(
    1000,
    ...curveData.map((p) => Math.min(p.paper, p.live)),
  );

  return (
    <div className="vstack gap-6 fade-up">
      <div>
        <SectionHeader
          title="Season Summary"
          subtitle="Paper-trade performance across all settled recommendations"
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 12,
          }}
        >
          <StatTile
            label="Record"
            value={`${summary.wins}–${summary.losses}`}
            sub={`${summary.settled} settled · ${formatPct(summary.win_rate_pct)} win rate`}
            tone="neutral"
          />
          <StatTile
            label="Accuracy"
            value={formatPct(summary.win_rate_pct)}
            sub="Pick accuracy across settled bets"
            tone="positive"
          />
          <StatTile
            label="Brier Score"
            value={summary.brier_best != null ? summary.brier_best.toFixed(3) : "—"}
            sub="Best model · target < 0.20"
            tone="accent"
          />
          <StatTile
            label="ROI"
            value={summary.roi_pct != null ? `${summary.roi_pct >= 0 ? "+" : ""}${summary.roi_pct}%` : "—"}
            sub={`Net ${summary.total_pl_units >= 0 ? "+" : ""}${summary.total_pl_units.toFixed(2)} units`}
            tone={summary.roi_pct != null && summary.roi_pct >= 0 ? "positive" : "negative"}
            trendValue={summary.roi_pct ?? undefined}
          />
        </div>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <SectionHeader
          title="Bankroll Curve"
          subtitle="Paper bankroll per round (live overlay is a 97% placeholder until live data is wired)"
          right={
            <div className="hstack gap-3" style={{ fontSize: 11.5 }}>
              <span className="hstack gap-1">
                <span
                  style={{
                    width: 10,
                    height: 2,
                    background: "#10b981",
                    display: "inline-block",
                  }}
                />{" "}
                Paper
              </span>
              <span className="hstack gap-1">
                <span
                  style={{
                    width: 10,
                    height: 2,
                    background: "#7dd3fc",
                    display: "inline-block",
                  }}
                />{" "}
                Live (est.)
              </span>
            </div>
          }
        />
        <div style={{ height: 240 }}>
          {curveData.length === 0 ? (
            <EmptyChart label="No bankroll history yet." />
          ) : (
            <ResponsiveContainer>
              <LineChart
                data={curveData}
                margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
              >
                <CartesianGrid
                  stroke="#1f2a44"
                  strokeDasharray="2 4"
                  vertical={false}
                />
                <XAxis
                  dataKey="round"
                  stroke="#5a6782"
                  tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                />
                <YAxis
                  stroke="#5a6782"
                  tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                  domain={[yDomainMin, "auto"]}
                  tickFormatter={(v) => `$${v}`}
                />
                <Tooltip
                  content={
                    <ChartTooltip formatter={(v) => `$${Number(v).toLocaleString()}`} />
                  }
                />
                <ReferenceLine
                  y={1000}
                  stroke="#5a6782"
                  strokeDasharray="3 3"
                  label={{
                    value: "Start",
                    fill: "#5a6782",
                    fontSize: 10,
                    position: "insideRight",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="paper"
                  stroke="#10b981"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "#10b981", strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
                  name="Paper"
                />
                <Line
                  type="monotone"
                  dataKey="live"
                  stroke="#7dd3fc"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "#7dd3fc", strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
                  name="Live"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 12,
        }}
      >
        <div className="card" style={{ padding: 20 }}>
          <SectionHeader
            title="Model Accuracy"
            subtitle="Pick accuracy across ensemble components"
          />
          {model_comparison.length === 0 ? (
            <EmptyChart label="No model runs yet." />
          ) : (
            <>
              <div style={{ height: 260 }}>
                <ResponsiveContainer>
                  <BarChart
                    data={model_comparison.map((m) => ({
                      name: m.model_name,
                      accuracy: m.accuracy != null ? +(m.accuracy * 100).toFixed(1) : 0,
                      brier: m.brier,
                    }))}
                    margin={{ top: 8, right: 12, left: -12, bottom: 0 }}
                  >
                    <CartesianGrid
                      stroke="#1f2a44"
                      strokeDasharray="2 4"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="name"
                      stroke="#5a6782"
                      tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                      tickLine={false}
                    />
                    <YAxis
                      stroke="#5a6782"
                      tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                      tickLine={false}
                      domain={[50, 80]}
                      tickFormatter={(v) => `${v}%`}
                    />
                    <Tooltip
                      content={<ChartTooltip formatter={(v) => `${v}%`} />}
                      cursor={{ fill: "rgba(125,211,252,0.04)" }}
                    />
                    <Bar dataKey="accuracy" radius={[6, 6, 0, 0]}>
                      {model_comparison.map((m, i) => (
                        <Cell
                          key={i}
                          fill={
                            m.model_name.toLowerCase().includes("ensemble")
                              ? "#10b981"
                              : "#2a3a5c"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: `repeat(${model_comparison.length}, 1fr)`,
                  gap: 6,
                  marginTop: 12,
                  fontSize: 10.5,
                }}
              >
                {model_comparison.map((m) => (
                  <div key={m.model_name} style={{ textAlign: "center" }}>
                    <div style={{ color: "var(--text-mute)" }}>Brier</div>
                    <div
                      className="mono"
                      style={{
                        color: m.model_name.toLowerCase().includes("ensemble")
                          ? "var(--green)"
                          : "var(--text)",
                        fontWeight: 600,
                      }}
                    >
                      {m.brier != null ? m.brier.toFixed(3) : "—"}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="card" style={{ padding: 20 }}>
          <SectionHeader
            title={`Recent ${recent_matches.length} Predictions`}
            subtitle={netPnl !== 0 ? `Net ${netPnl >= 0 ? "+" : ""}${netPnl.toFixed(2)} units` : "No settled recent picks"}
            right={
              <span
                className="chip mono"
                style={{ color: netPnl >= 0 ? "var(--green)" : "var(--red)" }}
              >
                {netPnl >= 0 ? "+" : ""}
                {netPnl.toFixed(2)}u
              </span>
            }
          />
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>R</th>
                  <th>Match</th>
                  <th>Pick</th>
                  <th className="hide-mobile">Result</th>
                  <th style={{ textAlign: "right" }}>Correct</th>
                </tr>
              </thead>
              <tbody>
                {recent_matches.map((r) => (
                  <tr key={r.match_id}>
                    <td className="mono" style={{ color: "var(--text-mute)" }}>
                      {r.round_label?.replace("Round ", "R") ?? "—"}
                    </td>
                    <td style={{ fontSize: 12 }}>
                      {r.home_team} vs {r.away_team}
                    </td>
                    <td className="mono" style={{ fontWeight: 600 }}>
                      {r.predicted_side === "home" ? r.home_team : r.away_team}
                      <span
                        style={{
                          marginLeft: 6,
                          color: "var(--text-mute)",
                          fontWeight: 400,
                        }}
                      >
                        {(r.predicted_prob * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="hide-mobile">
                      <span
                        className="mono"
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          color:
                            r.correct == null
                              ? "var(--text-mute)"
                              : r.correct
                                ? "var(--green)"
                                : "var(--red)",
                          fontWeight: 600,
                        }}
                      >
                        {r.actual_result == null
                          ? "—"
                          : r.correct
                            ? `✓ ${r.actual_result === "home" ? r.home_team : r.away_team}`
                            : `✗ ${r.actual_result === "home" ? r.home_team : r.away_team}`}
                      </span>
                    </td>
                    <td
                      className="mono"
                      style={{
                        textAlign: "right",
                        color:
                          r.correct == null
                            ? "var(--text-mute)"
                            : r.correct
                              ? "var(--green)"
                              : "var(--red)",
                        fontWeight: 600,
                      }}
                    >
                      {r.correct == null ? "pending" : r.correct ? "hit" : "miss"}
                    </td>
                  </tr>
                ))}
                {recent_matches.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      style={{
                        textAlign: "center",
                        color: "var(--text-mute)",
                        padding: 20,
                      }}
                    >
                      No settled matches yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function estimateRecentPnl(r: {
  correct: boolean | null;
  predicted_prob: number;
}): number {
  // Backend doesn't expose per-pick P/L; approximate 1-unit bets so the header
  // net units number stays directional.  Replace when bet_outcome linkage is
  // surfaced on /performance.
  if (r.correct == null) return 0;
  if (r.correct) return 1 / r.predicted_prob - 1;
  return -1;
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v.toFixed(1)}%`;
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div
      style={{
        height: 240,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--text-mute)",
        fontSize: 13,
      }}
    >
      {label}
    </div>
  );
}

function InfoCard({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "error";
}) {
  return (
    <div
      className="card"
      style={{
        padding: 20,
        color: tone === "error" ? "var(--red)" : "var(--text-mute)",
      }}
    >
      {children}
    </div>
  );
}
