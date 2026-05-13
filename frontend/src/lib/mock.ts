// Mock fallbacks for data points the Phase A backend does not yet expose.
// Each constant is tagged with a TODO so it can be replaced once the
// corresponding endpoint lands.

// TODO(backend): expose per-season ROI (e.g. /api/dashboard/backtest-summary.season_roi).
export const SEASON_ROI = [
  { year: 2015, roi: 4.2, bets: 89 },
  { year: 2016, roi: -2.1, bets: 94 },
  { year: 2017, roi: 8.4, bets: 102 },
  { year: 2018, roi: 11.3, bets: 98 },
  { year: 2019, roi: 6.8, bets: 105 },
  { year: 2020, roi: -5.6, bets: 62 },
  { year: 2021, roi: 9.1, bets: 108 },
  { year: 2022, roi: 13.7, bets: 114 },
  { year: 2023, roi: 7.2, bets: 111 },
  { year: 2024, roi: 15.4, bets: 119 },
  { year: 2025, roi: 12.8, bets: 117 },
];

// TODO(backend): expose long-horizon bankroll simulation curve.
export function buildLongBankroll(): {
  label: string;
  year: number;
  round: number;
  bankroll: number;
}[] {
  const pts: { label: string; year: number; round: number; bankroll: number }[] = [];
  let val = 1000;
  // Deterministic seed-free noise based on index (avoids SSR/hydration mismatch).
  const pseudo = (i: number) => {
    const x = Math.sin(i * 12.9898) * 43758.5453;
    return x - Math.floor(x); // 0..1
  };
  let step = 0;
  for (const s of SEASON_ROI) {
    const target = val * (1 + s.roi / 100);
    step = (target - val) / 22;
    for (let r = 1; r <= 22; r++) {
      const noise = (pseudo(pts.length) - 0.5) * Math.abs(step) * 0.8;
      const intermediate = val + step * r + (r < 22 ? noise : 0);
      pts.push({
        label: `${s.year} R${r}`,
        year: s.year,
        round: r,
        bankroll: Math.round(intermediate),
      });
    }
    val = target;
  }
  return pts;
}
export const LONG_BANKROLL = buildLongBankroll();

export function calcDrawdown(curve: { bankroll: number }[]): {
  pct: number;
  startIdx: number | null;
  endIdx: number | null;
} {
  let peak = -Infinity;
  let peakIdx = 0;
  let maxDd = 0;
  let ddStart: number | null = null;
  let ddEnd: number | null = null;
  curve.forEach((p, i) => {
    if (p.bankroll > peak) {
      peak = p.bankroll;
      peakIdx = i;
    }
    const dd = (peak - p.bankroll) / peak;
    if (dd > maxDd) {
      maxDd = dd;
      ddStart = peakIdx;
      ddEnd = i;
    }
  });
  return { pct: +(maxDd * 100).toFixed(1), startIdx: ddStart, endIdx: ddEnd };
}
export const DRAWDOWN = calcDrawdown(LONG_BANKROLL);

// TODO(backend): expose backtest summary metrics alongside /backtest-summary.
export const BACKTEST_METRICS = {
  totalBets: 1119,
  winRate: 54.2,
  avgEdge: 6.8,
  sharpe: 1.42,
  finalBankroll: 1847,
  startBankroll: 1000,
};

// TODO(backend): the /odds-tracker endpoint gives TAB snapshots only — add
// Sportsbet once a second bookmaker is ingested.  For now we derive a
// pseudo-Sportsbet line by ±3% around the TAB price.
export function pseudoSportsbet(tab: number, salt = 1): number {
  const jitter = (Math.sin(tab * salt * 11.7) * 0.03) + 0;
  return +(tab * (1 + jitter)).toFixed(2);
}

// TODO(backend): odds movement history is in /odds-tracker.matches[].history
// but the design expects a uniform 12-point open→close series.  This helper
// downsamples/pads when necessary.
export function normaliseOddsMovement(
  history: { at: string; home_odds: number | null; away_odds: number | null }[],
  anchorHome: number | null,
  anchorAway: number | null,
): { t: string; tab_home: number; tab_away: number }[] {
  if (!history.length && anchorHome != null && anchorAway != null) {
    // No snapshots: fabricate a flat line at the anchor price so the chart
    // still renders instead of collapsing.
    return Array.from({ length: 12 }, (_, i) => ({
      t: i === 0 ? "Open" : i === 11 ? "Close" : `-${(11 - i) * 4}h`,
      tab_home: anchorHome,
      tab_away: anchorAway,
    }));
  }
  const pts = history
    .filter((h) => h.home_odds != null && h.away_odds != null)
    .map((h) => ({
      t: h.at,
      tab_home: h.home_odds as number,
      tab_away: h.away_odds as number,
    }));
  if (pts.length <= 12) return pts;
  // Downsample uniformly to 12 points.
  const out: typeof pts = [];
  for (let i = 0; i < 12; i++) {
    const idx = Math.round((i / 11) * (pts.length - 1));
    out.push(pts[idx]);
  }
  return out;
}
