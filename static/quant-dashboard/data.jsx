// Seeded RNG so all "random" data is stable across renders.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function() {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rng = mulberry32(424242);
const rnd = (a, b) => a + (b - a) * rng();
const irnd = (a, b) => Math.floor(rnd(a, b + 1));

// AFL teams w/ accent colors for chips
const TEAMS = [
  { code: "ADE", name: "Adelaide", c: "#1c4eb8" },
  { code: "BRL", name: "Brisbane", c: "#a30046" },
  { code: "CAR", name: "Carlton", c: "#0a1f3a" },
  { code: "COL", name: "Collingwood", c: "#7c8089" },
  { code: "ESS", name: "Essendon", c: "#cc2031" },
  { code: "FRE", name: "Fremantle", c: "#3b1f6b" },
  { code: "GEE", name: "Geelong", c: "#1f4d8c" },
  { code: "GCS", name: "Gold Coast", c: "#d4a017" },
  { code: "GWS", name: "GWS Giants", c: "#e87722" },
  { code: "HAW", name: "Hawthorn", c: "#54350f" },
  { code: "MEL", name: "Melbourne", c: "#0a2b5c" },
  { code: "NTH", name: "North Melb.", c: "#1d4cb3" },
  { code: "PTA", name: "Port Adelaide", c: "#0aa1c4" },
  { code: "RIC", name: "Richmond", c: "#f0c419" },
  { code: "STK", name: "St Kilda", c: "#c8102e" },
  { code: "SYD", name: "Sydney", c: "#e1261c" },
  { code: "WCE", name: "West Coast", c: "#003087" },
  { code: "WBD", name: "W. Bulldogs", c: "#c8102e" },
];

// === time series ===
function makeTimeSeries(n, start, vol, drift = 0) {
  const out = [];
  let v = start;
  for (let i = 0; i < n; i++) {
    v += (rng() - 0.5) * vol + drift;
    out.push(v);
  }
  return out;
}

// Accuracy over time (around 0.62)
const ACCURACY_SERIES = (() => {
  const out = [];
  let v = 0.585;
  for (let i = 0; i < 28; i++) {
    v += (rng() - 0.5) * 0.025 + 0.0015;
    out.push(Math.max(0.50, Math.min(0.72, v)));
  }
  return out;
})();

// ROI series (%)
const ROI_SERIES = (() => {
  const out = []; let v = 1.5;
  for (let i = 0; i < 28; i++) {
    v += (rng() - 0.5) * 1.7 + 0.12;
    out.push(v);
  }
  return out;
})();

// Cumulative profit (units)
const CUM_PROFIT = (() => {
  const out = []; let v = 0;
  for (let i = 0; i < 90; i++) {
    v += (rng() - 0.45) * 8 + 0.6;
    out.push(v);
  }
  return out;
})();

// Bankroll curve ($)
const BANKROLL = (() => {
  const out = []; let v = 10000;
  for (let i = 0; i < 90; i++) {
    v += (rng() - 0.45) * 220 + 18;
    out.push(v);
  }
  return out;
})();

// Predicted prob distribution (histogram, 20 bins 0..1)
const PROB_DIST = (() => {
  const bins = new Array(20).fill(0);
  // Bell-ish around 0.5 with two humps near 0.35 and 0.7
  for (let i = 0; i < 1800; i++) {
    const u = rng();
    let x;
    if (u < 0.5) x = 0.35 + (rng() - 0.5) * 0.35;
    else x = 0.65 + (rng() - 0.5) * 0.32;
    x = Math.max(0.02, Math.min(0.98, x));
    const idx = Math.min(19, Math.floor(x * 20));
    bins[idx] += 1;
  }
  return bins;
})();

// Calibration curve: predicted vs observed (10 bins)
const CALIBRATION = (() => {
  const out = [];
  for (let i = 0; i < 10; i++) {
    const p = (i + 0.5) / 10;
    // observed close to p with slight under-confidence above 0.6
    const obs = Math.max(0, Math.min(1, p + (rng() - 0.5) * 0.06 - (p > 0.6 ? 0.02 : -0.01)));
    out.push({ p, obs, n: irnd(40, 220) });
  }
  return out;
})();

// Confidence buckets (low / med / high)
const CONF_BUCKETS = [
  { label: "50–55%", acc: 0.51, n: 412, roi: -0.6 },
  { label: "55–60%", acc: 0.57, n: 538, roi: 1.2 },
  { label: "60–65%", acc: 0.63, n: 471, roi: 4.4 },
  { label: "65–70%", acc: 0.68, n: 312, roi: 7.1 },
  { label: "70–75%", acc: 0.74, n: 184, roi: 9.8 },
  { label: "75–80%", acc: 0.79, n: 96,  roi: 12.4 },
  { label: "80%+",   acc: 0.83, n: 41,  roi: 14.6 },
];

// Edge vs return scatter
const EDGE_RETURN = (() => {
  const pts = [];
  for (let i = 0; i < 140; i++) {
    const edge = (rng() - 0.4) * 18;     // -7.2 .. 10.8
    const ret  = edge * 0.7 + (rng() - 0.5) * 24; // correlated
    pts.push({ x: edge, y: ret, r: 2 + rng() * 3 });
  }
  return pts;
})();

// Performance by odds range
const ODDS_RANGE = [
  { range: "1.20–1.50", roi: -2.1, n: 88,  acc: 0.78 },
  { range: "1.50–1.80", roi: 0.8,  n: 154, acc: 0.66 },
  { range: "1.80–2.10", roi: 4.2,  n: 312, acc: 0.55 },
  { range: "2.10–2.50", roi: 6.7,  n: 248, acc: 0.49 },
  { range: "2.50–3.00", roi: 8.4,  n: 132, acc: 0.42 },
  { range: "3.00–4.00", roi: 3.1,  n: 86,  acc: 0.32 },
  { range: "4.00+",     roi: -3.6, n: 34,  acc: 0.18 },
];

// Performance by market type
const MARKETS = [
  { name: "Head to head",   roi: 6.2, n: 612, c: "#5ef0b7" },
  { name: "Line (handicap)",roi: 3.4, n: 488, c: "#6cb6ff" },
  { name: "Total points",   roi: 1.1, n: 322, c: "#a78bfa" },
  { name: "First scorer",   roi: -2.1,n: 84,  c: "#f5c45e" },
  { name: "Margin band",    roi: 4.7, n: 146, c: "#5ed8e6" },
];

// Win rate by confidence
const WIN_BY_CONF = (() => {
  const pts = [];
  for (let i = 0; i < 12; i++) {
    const c = 0.50 + i * 0.025;
    const wr = c + (rng() - 0.5) * 0.05;
    pts.push({ c, wr, n: irnd(30, 220) });
  }
  return pts;
})();

// Strategies
const STRATEGIES = [
  { name: "Flat $50",        pl: 1842,  roi: 3.1, n: 612, sharpe: 0.84 },
  { name: "Kelly ¼",         pl: 4218,  roi: 7.4, n: 612, sharpe: 1.42 },
  { name: "Kelly ½",         pl: 6904,  roi: 11.2,n: 612, sharpe: 1.18 },
  { name: "Edge-gated 3%",   pl: 5310,  roi: 9.6, n: 388, sharpe: 1.61 },
  { name: "Top-conf only",   pl: 3124,  roi: 12.8,n: 184, sharpe: 1.49 },
  { name: "Anti-public fade",pl: -612,  roi: -1.4,n: 142, sharpe: -0.21 },
];

// Segments — by team
const TEAM_PERF = TEAMS.map(t => {
  const acc = 0.50 + (rng() - 0.45) * 0.18;
  const roi = (rng() - 0.4) * 14;
  return { ...t, acc, roi, n: irnd(28, 64) };
}).sort((a,b) => b.roi - a.roi);

// Home vs away
const HOME_AWAY = [
  { label: "Home", acc: 0.642, roi: 5.8, n: 612 },
  { label: "Away", acc: 0.586, roi: 2.1, n: 612 },
  { label: "Neutral", acc: 0.601, roi: 3.7, n: 84 },
];

// Venues (top 8)
const VENUES = [
  { name: "MCG",            acc: 0.66, roi: 7.4, n: 184 },
  { name: "Marvel Stadium", acc: 0.61, roi: 4.1, n: 162 },
  { name: "Adelaide Oval",  acc: 0.63, roi: 3.6, n: 86 },
  { name: "Optus Stadium",  acc: 0.59, roi: 1.8, n: 78 },
  { name: "GMHBA Stadium",  acc: 0.71, roi: 9.2, n: 42 },
  { name: "SCG",            acc: 0.57, roi: -1.2,n: 54 },
  { name: "Gabba",          acc: 0.64, roi: 4.8, n: 62 },
  { name: "Engie Stadium",  acc: 0.55, roi: -2.4,n: 38 },
];

// Rounds (24)
const ROUND_PERF = (() => {
  const out = [];
  for (let r = 1; r <= 24; r++) {
    out.push({ r, acc: 0.55 + (rng() - 0.5) * 0.18, roi: (rng() - 0.45) * 12, n: irnd(8, 12) });
  }
  return out;
})();

// Seasons
const SEASON_PERF = [
  { y: "2021", acc: 0.581, roi: 1.4, n: 198 },
  { y: "2022", acc: 0.604, roi: 3.6, n: 207 },
  { y: "2023", acc: 0.618, roi: 5.1, n: 212 },
  { y: "2024", acc: 0.627, roi: 6.4, n: 218 },
  { y: "2025", acc: 0.638, roi: 7.8, n: 184 },
  { y: "2026", acc: 0.612, roi: 4.2, n: 92 },
];

// Model versions
const MODEL_VERSIONS = [
  { v: "v4.2.1", acc: 0.638, brier: 0.214, ll: 0.612, roi: 7.8, n: 1218, status: "current" },
  { v: "v4.1.0", acc: 0.621, brier: 0.226, ll: 0.638, roi: 5.4, n: 1180, status: "prod" },
  { v: "v4.0.0", acc: 0.612, brier: 0.231, ll: 0.651, roi: 4.1, n: 1102, status: "prod" },
  { v: "v3.8.2", acc: 0.598, brier: 0.244, ll: 0.672, roi: 2.8, n: 980,  status: "deprecated" },
  { v: "v3.5.0", acc: 0.581, brier: 0.258, ll: 0.694, roi: 1.2, n: 820,  status: "deprecated" },
];

// Recent predictions table (24 rows)
const PICKS = (() => {
  const out = [];
  const venues = ["MCG", "Marvel Stadium", "Adelaide Oval", "Optus Stadium", "GMHBA", "Gabba", "SCG"];
  const versions = ["v4.2.1", "v4.2.1", "v4.2.1", "v4.1.0"];
  for (let i = 0; i < 24; i++) {
    const a = TEAMS[irnd(0, TEAMS.length - 1)];
    let b = TEAMS[irnd(0, TEAMS.length - 1)];
    while (b.code === a.code) b = TEAMS[irnd(0, TEAMS.length - 1)];
    const pickHome = rng() > 0.45;
    const pred = 0.50 + rng() * 0.32;
    const odds = (1 / pred) * (1 + rng() * 0.16) ;
    const impl = 1 / odds;
    const edge = (pred - impl) * 100;
    const result = rng() < pred + 0.04 ? "W" : (rng() > 0.92 ? "P" : "L");
    const stake = 50;
    const pl = result === "W" ? +(stake * (odds - 1)).toFixed(2) :
               result === "L" ? -stake : 0;
    const conf = Math.min(5, Math.max(1, Math.round(pred * 6 - 1)));
    const d = new Date(2026, 4, 4 - Math.floor(i / 3), 19, [10,40,15,45][i%4]);
    out.push({
      date: d,
      home: a, away: b,
      pick: pickHome ? a : b,
      pred, odds, impl, edge,
      result, pl, conf,
      venue: venues[i % venues.length],
      version: versions[i % versions.length],
    });
  }
  return out;
})();

window.AFLData = {
  TEAMS, ACCURACY_SERIES, ROI_SERIES, CUM_PROFIT, BANKROLL,
  PROB_DIST, CALIBRATION, CONF_BUCKETS, EDGE_RETURN, ODDS_RANGE,
  MARKETS, WIN_BY_CONF, STRATEGIES, TEAM_PERF, HOME_AWAY, VENUES,
  ROUND_PERF, SEASON_PERF, MODEL_VERSIONS, PICKS, rng,
};

// =========================================================================
// predictions.json overlay
// -------------------------------------------------------------------------
// On boot, try to fetch a sibling `predictions.json` produced by
// `generate_predictions_json.py`. When the file is present, its `games[]`
// replace the mock PICKS table and its `performance`/`summary` blocks
// populate `window.AFLLive` so KpiStrip surfaces real numbers. When the
// fetch fails (404 / network error / parse error) we keep the mock data
// shipped above — the design still paints, just with dummy values.
// =========================================================================

const _PREDICTIONS_JSON_URL = "predictions.json"; // resolved relative to index.html
const _CONFIDENCE_TO_PIPS = { LOW: 2, MED: 3, MEDIUM: 3, HIGH: 5 };

function _findTeamRecord(name) {
  if (!name) return { code: "?", name: "?", c: "#8b95a7" };
  const needle = String(name).toLowerCase();
  return (
    TEAMS.find((t) =>
      t.name.toLowerCase() === needle ||
      t.code.toLowerCase() === needle ||
      t.name.toLowerCase().includes(needle) ||
      needle.includes(t.name.toLowerCase()),
    ) || { code: String(name).slice(0, 3).toUpperCase(), name, c: "#8b95a7" }
  );
}

function _gamesToPicks(games) {
  if (!Array.isArray(games)) return [];
  return games.map((g) => {
    const home = _findTeamRecord(g.home_team);
    const away = _findTeamRecord(g.away_team);
    const pickIsHome = g.model_prediction
      ? String(g.model_prediction).toLowerCase() === String(g.home_team || "").toLowerCase()
      : (g.home_win_prob ?? 0.5) >= 0.5;
    const pick = pickIsHome ? home : away;
    const pred = pickIsHome ? (g.home_win_prob ?? 0.5) : (1 - (g.home_win_prob ?? 0.5));
    const odds = Number(g.tab_odds) || 0;
    const impl = odds > 0 ? 1 / odds : 0;
    const edge = (pred - impl) * 100;
    const conf = _CONFIDENCE_TO_PIPS[String(g.confidence || "").toUpperCase()] ?? 3;
    let parsedDate = g.game_date ? new Date(g.game_date) : new Date();
    if (Number.isNaN(parsedDate.getTime())) parsedDate = new Date();
    return {
      date: parsedDate,
      home, away, pick, pred, odds, impl, edge,
      result: "P",     // upcoming game — no outcome yet
      pl: 0,
      conf,
      venue: g.venue || "",
      version: "current",
      bet_recommended: !!g.bet_recommended,
      bet_amount: Number(g.bet_amount) || 0,
      xgboost_prob: g.xgboost_prob ?? null,
      poisson_prob: g.poisson_prob ?? null,
      elo_prob: g.elo_prob ?? null,
    };
  });
}

async function _loadPredictionsJson() {
  try {
    const res = await fetch(_PREDICTIONS_JSON_URL, { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const payload = await res.json();

    // 1. Override the predictions table
    const picks = _gamesToPicks(payload.games);
    if (picks.length) {
      window.AFLData.PICKS = picks;
    }

    // 2. Populate window.AFLLive so KpiStrip + LiveStatusBanner can read it.
    //    Map predictions.json fields onto the shape KpiStrip already expects.
    window.AFLLive = window.AFLLive || {};
    const perf = payload.performance || {};
    const summary = payload.summary || {};

    // Demo payloads (written by `make demo`) replay completed matches from the
    // bundled sample file. Flag that so the status banner can say so instead of
    // claiming "LIVE DATA" over historical sample output.
    window.AFLLive.demoMode = payload.demo === true;
    window.AFLLive.demoNotice = payload.demo_notice || null;
    window.AFLLive.performance = {
      total_bets: perf.total_predictions ?? null,
      settled: perf.total_predictions ?? null,
      pending: summary.total_bets_today ?? null,
      wins: perf.correct ?? null,
      losses:
        perf.total_predictions != null && perf.correct != null
          ? perf.total_predictions - perf.correct
          : null,
      win_rate_pct: perf.accuracy != null ? Number(perf.accuracy) * 100 : null,
      total_pl_units: perf.total_pnl ?? null,
      roi_pct: null,        // not directly in predictions.json
      brier_best: null,     // not directly in predictions.json
    };
    window.AFLLive.bankroll = {
      current: summary.total_amount != null ? Number(summary.total_amount) : null,
      peak: null,
      drawdown: null,
    };
    window.AFLLive.lastSyncAt = payload.generated_at
      ? new Date(payload.generated_at)
      : new Date();
    window.AFLLive.predictionsMeta = {
      season: payload.season ?? null,
      round: payload.round ?? null,
      paper_trade: summary.paper_trade ?? null,
      current_streak: perf.current_streak ?? null,
      n_today: summary.total_bets_today ?? null,
      bet_total_today: summary.total_amount ?? null,
    };
    window.AFLLive.liveCardsApplied = Array.from(
      new Set([...(window.AFLLive.liveCardsApplied || []), "PICKS", "performance"]),
    );
    window.AFLLive.loading = false;

    // 3. Re-render the React tree
    window.dispatchEvent(
      new CustomEvent("aflDataUpdate", { detail: { source: "predictions.json" } }),
    );
  } catch (err) {
    // Silently keep the mock dataset — the dashboard still paints. We log to
    // the console so devs can see why the live overlay didn't apply.
    if (typeof console !== "undefined") {
      console.info(
        "[AFL_predict] predictions.json not loaded (" +
          (err && err.message ? err.message : err) +
          "). Using bundled dummy data as fallback.",
      );
    }
  }
}

// Kick the fetch one frame after mount so React paints with mock data first.
if (typeof window !== "undefined") {
  if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", () => requestAnimationFrame(_loadPredictionsJson));
  } else {
    requestAnimationFrame(_loadPredictionsJson);
  }
}
