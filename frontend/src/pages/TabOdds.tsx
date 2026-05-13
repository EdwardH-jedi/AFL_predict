import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartTooltip } from "@/components/ChartTooltip";
import { Crest } from "@/components/Crest";
import { SectionHeader } from "@/components/SectionHeader";
import { useApi } from "@/hooks/useApi";
import { normaliseOddsMovement, pseudoSportsbet } from "@/lib/mock";
import { teamBrand } from "@/lib/teams";

export function TabOdds() {
  const { data, isLoading, error } = useApi("/api/dashboard/odds-tracker");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (isLoading && !data)
    return (
      <div className="card" style={{ padding: 20, color: "var(--text-mute)" }}>
        Loading odds data…
      </div>
    );
  if (error)
    return (
      <div className="card" style={{ padding: 20, color: "var(--red)" }}>
        Error: {String(error)}
      </div>
    );
  if (!data) return null;

  const activeId = selectedId ?? data.matches[0]?.match_id ?? null;
  const selected = data.matches.find((m) => m.match_id === activeId) ?? null;

  const rows = useMemo(
    () =>
      data.matches.map((m) => {
        const sbHome = m.tab_home_odds != null ? pseudoSportsbet(m.tab_home_odds, 1) : null;
        const sbAway = m.tab_away_odds != null ? pseudoSportsbet(m.tab_away_odds, 2) : null;
        const modelHomeOdds =
          m.model_home_prob && m.model_home_prob > 0 ? 1 / m.model_home_prob : null;
        const modelAwayOdds =
          m.model_away_prob && m.model_away_prob > 0 ? 1 / m.model_away_prob : null;
        const divergence = computeDivergence(
          m.tab_home_odds,
          m.tab_away_odds,
          modelHomeOdds,
          modelAwayOdds,
        );
        return {
          ...m,
          sbHome,
          sbAway,
          modelHomeOdds,
          modelAwayOdds,
          divergence,
        };
      }),
    [data.matches],
  );

  const movement =
    selected != null
      ? normaliseOddsMovement(
          selected.history,
          selected.tab_home_odds,
          selected.tab_away_odds,
        )
      : [];

  const modelImpliedHomeOdds =
    selected && selected.model_home_prob && selected.model_home_prob > 0
      ? 1 / selected.model_home_prob
      : null;

  return (
    <div className="vstack gap-6 fade-up">
      <div>
        <SectionHeader
          title={`${data.round_label ?? "Current Round"} · Odds Comparison`}
          subtitle={`${data.n_matches} match${data.n_matches === 1 ? "" : "es"} — TAB (live), Sportsbet (estimated), and model-implied prices. Click a row for price movement.`}
        />
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th style={{ paddingLeft: 20 }}>Match</th>
                  <th style={{ textAlign: "right" }}>TAB</th>
                  <th style={{ textAlign: "right" }}>Sportsbet*</th>
                  <th style={{ textAlign: "right" }}>Model</th>
                  <th style={{ textAlign: "right", paddingRight: 20 }}>
                    Divergence
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => {
                  const isSelected = o.match_id === activeId;
                  const isBig = o.divergence > 0.06;
                  return (
                    <tr
                      key={o.match_id}
                      onClick={() => setSelectedId(o.match_id)}
                      style={{
                        cursor: "pointer",
                        background: isSelected
                          ? "rgba(125, 211, 252, 0.06)"
                          : undefined,
                        borderLeft: isSelected
                          ? "2px solid var(--accent)"
                          : "2px solid transparent",
                      }}
                    >
                      <td style={{ paddingLeft: 18 }}>
                        <div className="hstack gap-2">
                          <Crest code={o.home_team} size={24} />
                          <span style={{ fontSize: 12 }}>vs</span>
                          <Crest code={o.away_team} size={24} />
                          <div
                            style={{
                              marginLeft: 8,
                              fontSize: 11.5,
                              color: "var(--text-mute)",
                            }}
                          >
                            {o.match_time ? formatShortTime(o.match_time) : ""}
                          </div>
                        </div>
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>
                        {renderOddsPair(o.tab_home_odds, o.tab_away_odds, "var(--text)")}
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>
                        {renderOddsPair(o.sbHome, o.sbAway, "var(--text-dim)")}
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>
                        {renderOddsPair(o.modelHomeOdds, o.modelAwayOdds, "var(--accent)")}
                      </td>
                      <td
                        className="mono"
                        style={{ textAlign: "right", paddingRight: 20 }}
                      >
                        <div
                          className="hstack gap-2"
                          style={{ justifyContent: "flex-end" }}
                        >
                          <div className="bar" style={{ width: 60, height: 4 }}>
                            <span
                              style={{
                                width: `${Math.min(100, o.divergence * 500)}%`,
                                background: isBig
                                  ? "var(--fire)"
                                  : "var(--text-mute)",
                              }}
                            />
                          </div>
                          <span
                            style={{
                              color: isBig ? "var(--fire)" : "var(--text-dim)",
                              fontWeight: isBig ? 600 : 400,
                              minWidth: 46,
                              fontSize: 12,
                            }}
                          >
                            {(o.divergence * 100).toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      style={{
                        textAlign: "center",
                        color: "var(--text-mute)",
                        padding: 24,
                      }}
                    >
                      No upcoming matches with odds.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-mute)",
            marginTop: 6,
          }}
        >
          * Sportsbet column is a ±3% synthetic until the second bookmaker is
          ingested.
        </div>
      </div>

      {selected && (
        <div className="card" style={{ padding: 20 }}>
          <SectionHeader
            title={`Price Movement · ${selected.home_team} vs ${selected.away_team}`}
            subtitle="TAB snapshots sampled hourly from open to close"
            right={
              <div className="hstack gap-3" style={{ fontSize: 11.5 }}>
                <span className="hstack gap-1">
                  <span
                    style={{
                      width: 10,
                      height: 2,
                      background: resolveLineColor(selected.home_team, true),
                      display: "inline-block",
                    }}
                  />{" "}
                  {selected.home_team}
                </span>
                <span className="hstack gap-1">
                  <span
                    style={{
                      width: 10,
                      height: 2,
                      background: "#ef4444",
                      display: "inline-block",
                    }}
                  />{" "}
                  {selected.away_team}
                </span>
              </div>
            }
          />
          <div style={{ height: 260 }}>
            {movement.length < 2 ? (
              <div
                style={{
                  height: 260,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--text-mute)",
                  fontSize: 13,
                }}
              >
                Not enough snapshot history to draw a curve yet.
              </div>
            ) : (
              <ResponsiveContainer>
                <LineChart
                  data={movement}
                  margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                >
                  <CartesianGrid
                    stroke="#1f2a44"
                    strokeDasharray="2 4"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="t"
                    stroke="#5a6782"
                    tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
                    tickLine={false}
                  />
                  <YAxis
                    stroke="#5a6782"
                    tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                    tickLine={false}
                    tickFormatter={(v) => Number(v).toFixed(2)}
                    domain={["dataMin - 0.1", "dataMax + 0.1"]}
                  />
                  <Tooltip
                    content={
                      <ChartTooltip formatter={(v) => Number(v).toFixed(2)} />
                    }
                  />
                  {modelImpliedHomeOdds != null && (
                    <ReferenceLine
                      y={modelImpliedHomeOdds}
                      stroke="#10b981"
                      strokeDasharray="3 3"
                      label={{
                        value: `Model (home) ${modelImpliedHomeOdds.toFixed(2)}`,
                        fill: "#10b981",
                        fontSize: 10,
                        position: "insideTopLeft",
                      }}
                    />
                  )}
                  <Line
                    type="monotone"
                    dataKey="tab_home"
                    stroke={resolveLineColor(selected.home_team, true)}
                    strokeWidth={2.5}
                    dot={{ r: 3, strokeWidth: 0 }}
                    activeDot={{ r: 5 }}
                    name={`${selected.home_team} (home)`}
                  />
                  <Line
                    type="monotone"
                    dataKey="tab_away"
                    stroke="#ef4444"
                    strokeWidth={2.5}
                    dot={{ r: 3, strokeWidth: 0 }}
                    activeDot={{ r: 5 }}
                    name={`${selected.away_team} (away)`}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function computeDivergence(
  tabHome: number | null,
  tabAway: number | null,
  modelHomeOdds: number | null,
  modelAwayOdds: number | null,
): number {
  if (!tabHome || !tabAway || !modelHomeOdds || !modelAwayOdds) return 0;
  return Math.max(
    Math.abs(1 / tabHome - 1 / modelHomeOdds),
    Math.abs(1 / tabAway - 1 / modelAwayOdds),
  );
}

function renderOddsPair(
  home: number | null,
  away: number | null,
  mainColor: string,
) {
  if (home == null && away == null) {
    return <span style={{ color: "var(--text-mute)" }}>—</span>;
  }
  return (
    <>
      <span style={{ color: mainColor }}>
        {home != null ? home.toFixed(2) : "—"}
      </span>
      <span style={{ color: "var(--text-mute)", margin: "0 6px" }}>/</span>
      <span style={{ color: mainColor }}>
        {away != null ? away.toFixed(2) : "—"}
      </span>
    </>
  );
}

function resolveLineColor(teamCode: string, fallbackAccent: boolean): string {
  const brand = teamBrand(teamCode);
  if (brand.color === "#000000" || brand.color === "#111111") {
    return fallbackAccent ? "#7dd3fc" : brand.color;
  }
  return brand.color;
}

function formatShortTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}
