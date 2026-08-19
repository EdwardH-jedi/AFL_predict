import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ReferenceArea,
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
import { BACKTEST_METRICS, DRAWDOWN, LONG_BANKROLL, SEASON_ROI } from "@/lib/mock";

// The /api/dashboard/backtest-summary endpoint exposes the latest artifact
// and ensemble weights but not the multi-season history.  We hydrate the
// ensemble weights and season ROI card from real data when available and
// fall back to the design's mock horizon for visual parity.

const WEIGHT_COLORS: Record<string, string> = {
  xgboost: "#10b981",
  logistic: "#38bdf8",
  elo: "#7dd3fc",
  poisson: "#a78bfa",
  bookmaker: "#f59e0b",
};

export function TabBacktest() {
  const { data, isLoading, error } = useApi("/api/dashboard/backtest-summary");

  if (isLoading && !data)
    return (
      <div className="card" style={{ padding: 20, color: "var(--text-mute)" }}>
        Loading backtest summary…
      </div>
    );
  if (error)
    return (
      <div className="card" style={{ padding: 20, color: "var(--red)" }}>
        Error: {String(error)}
      </div>
    );
  if (!data) return null;

  // Ensemble pie data — real weights from the backend.
  const weights = data.ensemble_weights;
  const totalWeight =
    weights.logistic +
      weights.xgboost +
      weights.poisson +
      weights.elo +
      weights.bookmaker || 1;
  const ensembleData = [
    { name: "XGBoost", value: pct(weights.xgboost, totalWeight), color: WEIGHT_COLORS.xgboost },
    { name: "Logistic", value: pct(weights.logistic, totalWeight), color: WEIGHT_COLORS.logistic },
    { name: "Poisson", value: pct(weights.poisson, totalWeight), color: WEIGHT_COLORS.poisson },
    { name: "ELO", value: pct(weights.elo, totalWeight), color: WEIGHT_COLORS.elo },
    { name: "Bookmaker", value: pct(weights.bookmaker, totalWeight), color: WEIGHT_COLORS.bookmaker },
  ].filter((d) => d.value > 0);

  const sampled = LONG_BANKROLL.filter(
    (_, i) => i % 4 === 0 || i === LONG_BANKROLL.length - 1,
  );
  const ddStart =
    DRAWDOWN.startIdx != null ? LONG_BANKROLL[DRAWDOWN.startIdx] : null;
  const ddEnd = DRAWDOWN.endIdx != null ? LONG_BANKROLL[DRAWDOWN.endIdx] : null;

  // Header metrics — use real season ROI from backend when non-null.
  const seasonRoi = data.season_roi_pct;

  return (
    <div className="vstack gap-6 fade-up">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: 12,
        }}
      >
        <StatTile
          label="Total Bets"
          value={BACKTEST_METRICS.totalBets.toLocaleString()}
          sub="2015 – 2025 seasons (mock)"
          tone="neutral"
        />
        <StatTile
          label="Win Rate"
          value={`${BACKTEST_METRICS.winRate}%`}
          sub="Above 52.4% breakeven"
          tone="positive"
        />
        <StatTile
          label="Avg Edge"
          value={`+${BACKTEST_METRICS.avgEdge}%`}
          sub="Per bet placed"
          tone="accent"
        />
        <StatTile
          label="Sharpe"
          value={BACKTEST_METRICS.sharpe.toFixed(2)}
          sub="Risk-adjusted returns"
          tone="positive"
        />
        <StatTile
          label="Season ROI"
          value={
            seasonRoi != null
              ? `${seasonRoi >= 0 ? "+" : ""}${seasonRoi.toFixed(1)}%`
              : `$${BACKTEST_METRICS.finalBankroll.toLocaleString()}`
          }
          sub={
            seasonRoi != null
              ? "This season (live)"
              : `Mock final · start $${BACKTEST_METRICS.startBankroll}`
          }
          tone={seasonRoi != null && seasonRoi < 0 ? "negative" : "positive"}
          trendValue={seasonRoi ?? 84.7}
        />
      </div>

      <div className="card" style={{ padding: 20 }}>
        <SectionHeader
          title="11-Season Bankroll Simulation"
          subtitle={`$1,000 start → $${BACKTEST_METRICS.finalBankroll.toLocaleString()} · max drawdown ${DRAWDOWN.pct}% highlighted in red`}
          right={
            <span className="chip mono" style={{ color: "var(--fire)" }}>
              DD {DRAWDOWN.pct}%
            </span>
          }
        />
        <div style={{ height: 280 }}>
          <ResponsiveContainer>
            <AreaChart
              data={sampled}
              margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="bankFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
                  <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
                </linearGradient>
              </defs>
              <CartesianGrid
                stroke="#1f2a44"
                strokeDasharray="2 4"
                vertical={false}
              />
              <XAxis
                dataKey="year"
                stroke="#5a6782"
                tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                tickLine={false}
                interval="preserveStartEnd"
                ticks={[2015, 2017, 2019, 2021, 2023, 2025]}
              />
              <YAxis
                stroke="#5a6782"
                tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                tickLine={false}
                tickFormatter={(v) => `$${(Number(v) / 1000).toFixed(1)}k`}
                domain={["dataMin - 50", "dataMax + 50"]}
              />
              <Tooltip
                content={
                  <ChartTooltip
                    formatter={(v) => `$${Number(v).toLocaleString()}`}
                    labelFormatter={(v) => `${v}`}
                  />
                }
              />
              <ReferenceLine y={1000} stroke="#5a6782" strokeDasharray="3 3" />
              {ddStart && ddEnd && (
                <ReferenceArea
                  x1={ddStart.year}
                  x2={ddEnd.year}
                  y1={0}
                  y2={ddStart.bankroll}
                  fill="#ef4444"
                  fillOpacity={0.08}
                  stroke="#ef4444"
                  strokeOpacity={0.3}
                />
              )}
              <Area
                type="monotone"
                dataKey="bankroll"
                stroke="#10b981"
                strokeWidth={2}
                fill="url(#bankFill)"
                name="Bankroll"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: 12,
        }}
      >
        <div className="card" style={{ padding: 20 }}>
          <SectionHeader
            title="Season ROI"
            subtitle="Per-season return · 2 losing years out of 11"
          />
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <BarChart
                data={SEASON_ROI}
                margin={{ top: 8, right: 12, left: -12, bottom: 0 }}
              >
                <CartesianGrid
                  stroke="#1f2a44"
                  strokeDasharray="2 4"
                  vertical={false}
                />
                <XAxis
                  dataKey="year"
                  stroke="#5a6782"
                  tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                />
                <YAxis
                  stroke="#5a6782"
                  tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                  tickFormatter={(v) => `${v}%`}
                />
                <Tooltip
                  content={
                    <ChartTooltip
                      formatter={(v) => `${Number(v) > 0 ? "+" : ""}${Number(v)}%`}
                    />
                  }
                  cursor={{ fill: "rgba(125,211,252,0.04)" }}
                />
                <ReferenceLine y={0} stroke="#5a6782" />
                <Bar dataKey="roi" radius={[4, 4, 0, 0]}>
                  {SEASON_ROI.map((s, i) => (
                    <Cell
                      key={i}
                      fill={s.roi >= 0 ? "#10b981" : "#ef4444"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <SectionHeader
            title="Ensemble Weights"
            subtitle={
              data.available
                ? "Live weights from config"
                : "Config weights (latest artifact unavailable)"
            }
          />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "200px 1fr",
              gap: 20,
              alignItems: "center",
            }}
          >
            <div style={{ height: 200, position: "relative" }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={ensembleData}
                    dataKey="value"
                    innerRadius={50}
                    outerRadius={80}
                    paddingAngle={2}
                    startAngle={90}
                    endAngle={-270}
                  >
                    {ensembleData.map((w, i) => (
                      <Cell
                        key={i}
                        fill={w.color}
                        stroke="var(--bg-1)"
                        strokeWidth={2}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    content={
                      <ChartTooltip formatter={(v) => `${Number(v).toFixed(1)}%`} />
                    }
                  />
                </PieChart>
              </ResponsiveContainer>
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  pointerEvents: "none",
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--text-mute)",
                    letterSpacing: "0.1em",
                  }}
                >
                  MODELS
                </div>
                <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>
                  {ensembleData.length}
                </div>
              </div>
            </div>
            <div className="vstack gap-2">
              {ensembleData.map((w) => (
                <div
                  key={w.name}
                  className="hstack"
                  style={{ justifyContent: "space-between", gap: 10 }}
                >
                  <div className="hstack gap-2">
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 2,
                        background: w.color,
                      }}
                    />
                    <span style={{ fontSize: 13 }}>{w.name}</span>
                  </div>
                  <span
                    className="mono"
                    style={{ fontWeight: 600, fontSize: 13 }}
                  >
                    {w.value.toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function pct(n: number, total: number): number {
  if (!total) return 0;
  return (n / total) * 100;
}
