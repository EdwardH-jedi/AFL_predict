// live-data.jsx — overlays real AFL_predict API data on top of the mock
// dataset shipped with the Claude Design prototype.
//
// Strategy: the mock data in `data.jsx` paints the design instantly, then this
// module fetches the existing FastAPI endpoints, maps each response onto the
// fields used by the design's components, and dispatches `aflDataUpdate` so
// the React tree re-renders. Anything we cannot resolve from the API stays on
// the mock value and is flagged with a TODO below for follow-up wiring.
//
// Endpoints consumed (all read-only GET):
//   /dashboard/performance      — bets, summary, model_runs
//   /dashboard/bankroll         — series + current/peak/drawdown
//   /dashboard/recommendations  — latest recs (for the predictions table)
//   /dashboard/freshness        — odds / fixture data freshness
//   /dashboard/readiness        — live-readiness check report
//   /dashboard/clv              — closing line value summary
//   /discord/status             — Discord notification config + reachability
//
// This file deliberately avoids mutating any predictions, bankroll or model
// state — it is purely a read-only adapter for the dashboard UI.

const API_BASE = ""; // same-origin; mount lives under /static so the FastAPI host serves both.

const STATUS = {
  loading: true,
  errors: {},          // endpointName -> message
  freshness: null,     // { odds_age_hours, afl_age_hours, warnings: [] }
  readiness: null,     // { overall, checks: [...] }
  discord: null,       // { configured, reachable, error? }
  performance: null,   // raw summary block
  bankroll: null,      // { current, peak, drawdown }
  clv: null,           // { beat_closing_line, avg_clv_pct, median_clv_pct }
  lastSyncAt: null,    // Date
  liveCardsApplied: [] // which AFLData keys we successfully overrode
};

window.AFLLive = STATUS;

// ---- helpers -------------------------------------------------------------

async function _fetchJson(path) {
  try {
    const res = await fetch(API_BASE + path, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    STATUS.errors[path] = String(err && err.message ? err.message : err);
    return null;
  }
}

function _teamColor(shortName) {
  // Map team short_name -> color from the prototype's TEAMS array.
  if (!shortName) return "#8b95a7";
  const upper = String(shortName).toUpperCase();
  const team = (window.AFLData?.TEAMS || []).find(
    (t) => t.code.toUpperCase() === upper || t.name.toUpperCase().startsWith(upper),
  );
  return team ? team.c : "#8b95a7";
}

function _teamRecord(shortName) {
  if (!shortName) return { code: "?", name: shortName || "?", c: "#8b95a7" };
  const upper = String(shortName).toUpperCase();
  const team = (window.AFLData?.TEAMS || []).find(
    (t) => t.code.toUpperCase() === upper || t.name.toUpperCase().startsWith(upper),
  );
  return team ? team : { code: upper, name: shortName, c: "#8b95a7" };
}

// ---- shape adapters ------------------------------------------------------

function _adaptPicks(performanceData, recommendationsData) {
  // Prefer the recommendations endpoint because it ships home/away team ids
  // and bet outcomes already joined. Fall back to performance.bets which has
  // names but is also fine.
  const recs = recommendationsData?.recommendations || [];
  const out = [];

  // Build a teams map (id -> short_name + color) using the design's TEAMS list
  // is not enough — the API returns team ids, not codes. We do not currently
  // have an /api/teams endpoint, so we fall back to performance.bets (which
  // already strings the team names) for the table contents.
  // TODO: expose a /api/teams endpoint and resolve home_team / away_team ids
  // directly so that picks-from-recommendations also work.

  const bets = performanceData?.bets || [];
  // Walk newest-first; the design shows 24 rows.
  for (let i = bets.length - 1; i >= 0 && out.length < 24; i--) {
    const b = bets[i];
    if (!b) continue;
    const home = _teamRecord(b.home_team);
    const away = _teamRecord(b.away_team);
    const pickRec = b.side === "home" ? home : away;
    const pred = b.side === "home" ? (b.home_win_prob ?? 0.5) : (b.away_win_prob ?? 0.5);
    const odds = b.odds || 0;
    const impl = odds > 0 ? (1 / odds) : 0;
    const edge = b.edge != null ? b.edge * 100 : (pred - impl) * 100;
    let result = "P";
    let pl = 0;
    if (b.outcome && b.outcome.won != null) {
      result = b.outcome.won ? "W" : "L";
      pl = b.outcome.pl_units != null
        ? Number((b.outcome.pl_units * 50).toFixed(2))   // approx $ at 50u flat
        : 0;
    }
    const conf = Math.min(5, Math.max(1, Math.round(pred * 6 - 1)));
    const d = b.match_time ? new Date(b.match_time) : new Date(b.created_at);
    out.push({
      date: d,
      home, away,
      pick: pickRec,
      pred, odds, impl, edge,
      result, pl, conf,
      venue: b.venue || "",
      version: "live",
    });
  }
  return out.length ? out : null;
}

function _adaptModelVersions(performanceData) {
  const runs = performanceData?.model_runs || [];
  if (!runs.length) return null;
  return runs.map((r, idx) => ({
    v: r.model || `model-${idx}`,
    acc: r.accuracy ?? 0,
    brier: r.brier ?? 0,
    ll: r.log_loss ?? 0,
    roi: 0,           // TODO: per-model ROI is not exposed by /dashboard/performance yet
    n: 0,             // TODO: per-model bet count not exposed
    status: idx === 0 ? "current" : "prod",
  }));
}

function _adaptBankrollSeries(bankrollData) {
  const series = bankrollData?.series || [];
  if (!series.length) return null;
  return series.map((p) => p.balance);
}

function _adaptCumProfit(performanceData) {
  const cum = performanceData?.cumulative_pl || [];
  if (!cum.length) return null;
  return cum.map((p) => p.cumulative_pl);
}

// ---- main loader ---------------------------------------------------------

async function _refresh() {
  STATUS.loading = true;
  STATUS.errors = {};

  const [performance, bankroll, recommendations, freshness, readiness, clv, discord] = await Promise.all([
    _fetchJson("/dashboard/performance"),
    _fetchJson("/dashboard/bankroll?days=90"),
    _fetchJson("/dashboard/recommendations?limit=24"),
    _fetchJson("/dashboard/freshness"),
    _fetchJson("/dashboard/readiness"),
    _fetchJson("/dashboard/clv"),
    _fetchJson("/discord/status"),
  ]);

  STATUS.performance = performance?.summary || null;
  STATUS.bankroll = bankroll
    ? { current: bankroll.current, peak: bankroll.peak, drawdown: bankroll.drawdown }
    : null;
  STATUS.freshness = freshness;
  STATUS.readiness = readiness;
  STATUS.clv = clv?.clv || null;
  STATUS.discord = discord;
  STATUS.lastSyncAt = new Date();

  // Overlay onto window.AFLData where we have real data.
  const D = window.AFLData;
  const applied = [];

  const picks = _adaptPicks(performance, recommendations);
  if (picks && picks.length) {
    D.PICKS = picks;
    applied.push("PICKS");
  }

  const cum = _adaptCumProfit(performance);
  if (cum && cum.length) {
    D.CUM_PROFIT = cum;
    applied.push("CUM_PROFIT");
  }

  const bk = _adaptBankrollSeries(bankroll);
  if (bk && bk.length) {
    D.BANKROLL = bk;
    applied.push("BANKROLL");
  }

  const versions = _adaptModelVersions(performance);
  if (versions && versions.length) {
    D.MODEL_VERSIONS = versions;
    applied.push("MODEL_VERSIONS");
  }

  STATUS.liveCardsApplied = applied;
  STATUS.loading = false;

  // Notify the React tree.
  window.dispatchEvent(new CustomEvent("aflDataUpdate", { detail: { applied } }));
}

// Kick off after the rest of the bundle has registered (one tick after mount).
window.addEventListener("DOMContentLoaded", () => {
  // Defer one frame so React mounts first with mock data — render-first, fetch-after.
  requestAnimationFrame(() => { _refresh(); });
});

// Public API for manual refresh from the topbar later (no UI hook yet).
window.AFLLive.refresh = _refresh;

// ---- status banner component --------------------------------------------
//
// Rendered just under the dual-row topbar. Communicates whether the dashboard
// is showing live data, plus key operational state. Read-only by design.

function _ageLabel(hours) {
  if (hours == null) return "?";
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 48) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

function LiveStatusBanner() {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    const h = () => force((x) => x + 1);
    window.addEventListener("aflDataUpdate", h);
    return () => window.removeEventListener("aflDataUpdate", h);
  }, []);

  const s = window.AFLLive;
  const applied = s.liveCardsApplied || [];
  const isLive = applied.length > 0;
  const errCount = Object.keys(s.errors || {}).length;

  // Compose pills
  const pills = [];

  // Live vs Mock
  pills.push({
    key: "mode",
    label: isLive ? "LIVE DATA" : (s.loading ? "LOADING…" : "MOCK DATA"),
    tone: isLive ? "ok" : (s.loading ? "neutral" : "warn"),
    detail: isLive ? `overlay: ${applied.join(", ")}` : "demo dataset",
  });

  // Freshness
  if (s.freshness) {
    const stale = s.freshness.odds_stale || s.freshness.afl_stale;
    pills.push({
      key: "freshness",
      label: stale ? "DATA STALE" : "DATA FRESH",
      tone: stale ? "warn" : "ok",
      detail: `odds ${_ageLabel(s.freshness.odds_age_hours)} · fixtures ${_ageLabel(s.freshness.afl_age_hours)}`,
    });
  }

  // Readiness
  if (s.readiness) {
    const overall = (s.readiness.overall || "unknown").toLowerCase();
    pills.push({
      key: "readiness",
      label: `READINESS · ${overall.toUpperCase()}`,
      tone: overall === "ready" || overall === "pass" ? "ok" :
            overall === "warn" || overall === "marginal" ? "warn" : "neutral",
      detail: Array.isArray(s.readiness.checks) ? `${s.readiness.checks.length} checks` : "",
    });
  }

  // Discord
  if (s.discord) {
    const ok = s.discord.configured && s.discord.reachable;
    pills.push({
      key: "discord",
      label: `DISCORD · ${ok ? "OK" : (s.discord.configured ? "UNREACHABLE" : "OFF")}`,
      tone: ok ? "ok" : (s.discord.configured ? "warn" : "neutral"),
      detail: ok ? "webhook ready" : (s.discord.error || "set DISCORD_BOT_TOKEN + CHANNEL_ID"),
    });
  }

  // CLV — informational only
  if (s.clv && s.clv.avg_clv_pct != null) {
    pills.push({
      key: "clv",
      label: `CLV ${s.clv.avg_clv_pct >= 0 ? "+" : ""}${(s.clv.avg_clv_pct).toFixed(2)}%`,
      tone: s.clv.avg_clv_pct >= 0 ? "ok" : "warn",
      detail: `beats line ${((s.clv.beat_closing_line || 0) * 100).toFixed(0)}% of bets`,
    });
  }

  // Errors collapsed pill
  if (errCount > 0) {
    pills.push({
      key: "errors",
      label: `API · ${errCount} ERROR${errCount > 1 ? "S" : ""}`,
      tone: "warn",
      detail: Object.keys(s.errors).join(", "),
    });
  }

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        flexWrap: "wrap",
        alignItems: "center",
        padding: "8px 22px",
        borderBottom: "1px solid var(--line)",
        background: "var(--bg-1)",
        fontFamily: "var(--font-mono)",
        fontSize: 10,
      }}
    >
      {pills.map((p) => {
        const toneColor =
          p.tone === "ok" ? "var(--mint)" :
          p.tone === "warn" ? "var(--amber)" :
          "var(--ink-3)";
        const toneBg =
          p.tone === "ok" ? "rgba(94,240,183,0.06)" :
          p.tone === "warn" ? "rgba(245,196,94,0.06)" :
          "var(--bg-2)";
        return (
          <span
            key={p.key}
            title={p.detail}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 8px",
              borderRadius: 3,
              border: "1px solid " + (p.tone === "ok" ? "rgba(94,240,183,0.20)" : p.tone === "warn" ? "rgba(245,196,94,0.20)" : "var(--line)"),
              background: toneBg,
              color: toneColor,
              letterSpacing: "0.06em",
            }}
          >
            <span style={{ fontWeight: 600 }}>{p.label}</span>
            {p.detail && (
              <span style={{ color: "var(--ink-3)", fontWeight: 400 }}>{p.detail}</span>
            )}
          </span>
        );
      })}
      <span style={{ marginLeft: "auto", color: "var(--ink-3)" }}>
        {s.lastSyncAt ? `synced ${s.lastSyncAt.toLocaleTimeString()}` : "never synced"}
      </span>
    </div>
  );
}

window.LiveStatusBanner = LiveStatusBanner;
