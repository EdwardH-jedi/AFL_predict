import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { Crest } from "@/components/Crest";
import { SectionHeader } from "@/components/SectionHeader";
import { StatTile } from "@/components/StatTile";
import { REFRESH_TODAY_MS, useApi } from "@/hooks/useApi";
import { edgeToConfidence, type ConfidenceLevel } from "@/lib/confidence";
import { teamBrand } from "@/lib/teams";
import type { PickMatch, TodayPicksResponse } from "@/types";

const ACCENT_COLOR: Record<ConfidenceLevel, string> = {
  strong: "#fb923c",
  moderate: "#10b981",
  marginal: "#f59e0b",
  none: "transparent",
};

export function TabPicks() {
  const { data, isLoading, error } = useApi("/api/dashboard/today-picks", {
    refreshInterval: REFRESH_TODAY_MS,
  });

  if (isLoading && !data) return <LoadingState label="Loading today's picks…" />;
  if (error) return <ErrorState message={String(error)} />;
  if (!data) return null;

  const betMatches = data.picks.filter((p) => p.recommendation);
  const noBetMatches = data.picks.filter((p) => !p.recommendation);

  const totalStake = betMatches.reduce(
    (s, m) => s + (m.recommendation?.suggested_stake_aud ?? 0),
    0,
  );
  const potentialReturn = betMatches.reduce((s, m) => {
    const rec = m.recommendation!;
    const stake = rec.suggested_stake_aud ?? 0;
    return s + stake * rec.recommended_odds;
  }, 0);

  const bankroll = data.bankroll.live_balance_aud ?? data.bankroll.paper_balance;
  const bankrollRisk = bankroll > 0 ? (totalStake / bankroll) * 100 : 0;
  const netIfAllHit = potentialReturn - totalStake;

  return (
    <div className="vstack gap-6 fade-up">
      {/* Top summary */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
        }}
      >
        <StatTile
          label="Bankroll"
          value={`$${Math.round(bankroll).toLocaleString()}`}
          sub="Paper trade balance"
          tone="positive"
          trendValue={data.bankroll.paper_return_pct ?? undefined}
        />
        <StatTile
          label="Today's Stake"
          value={`$${Math.round(totalStake)}`}
          sub={`${betMatches.length} recommended bet${betMatches.length === 1 ? "" : "s"}`}
          tone="accent"
        />
        <StatTile
          label="Potential Return"
          value={`$${Math.round(potentialReturn)}`}
          sub={`Net profit +$${Math.round(netIfAllHit)} if all hit`}
          tone="positive"
        />
        <StatTile
          label="Bankroll Risk"
          value={`${bankrollRisk.toFixed(1)}%`}
          sub={bankrollRisk < 15 ? "Well under 15% ceiling" : "Above the 15% ceiling"}
          tone={bankrollRisk < 15 ? "neutral" : "negative"}
        />
      </div>

      <PicksSection
        title={`Recommended Bets${data.next_match_minutes != null ? ` · next in ${Math.max(0, data.next_match_minutes)}m` : ""}`}
        subtitle={`${data.n_matches} match${data.n_matches === 1 ? "" : "es"} in window · edge on ${betMatches.length}`}
        matches={betMatches}
        emptyCopy="No recommendations meet the edge threshold yet."
        right={
          <span className="chip chip-dot" style={{ color: "var(--green)" }}>
            <span className="live-dot" />
            Live model
          </span>
        }
      />

      <PicksSection
        title="Other Matches"
        subtitle="Tracked but no edge meets our threshold"
        matches={noBetMatches}
        emptyCopy="No other matches in the lookahead window."
      />
    </div>
  );
}

function PicksSection({
  title,
  subtitle,
  matches,
  emptyCopy,
  right,
}: {
  title: string;
  subtitle: string;
  matches: PickMatch[];
  emptyCopy: string;
  right?: React.ReactNode;
}) {
  return (
    <div>
      <SectionHeader title={title} subtitle={subtitle} right={right} />
      {matches.length === 0 ? (
        <div
          className="card"
          style={{ padding: 20, color: "var(--text-mute)", fontSize: 13 }}
        >
          {emptyCopy}
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
            gap: 12,
          }}
        >
          {matches.map((m) => (
            <MatchCard key={m.match_id} match={m} />
          ))}
        </div>
      )}
    </div>
  );
}

function MatchCard({ match }: { match: PickMatch }) {
  const home = teamBrand(match.home_team);
  const away = teamBrand(match.away_team);
  const rec = match.recommendation;
  const hasBet = rec != null;
  const level: ConfidenceLevel = rec ? edgeToConfidence(rec.edge) : "none";

  const modelHomePct = Math.round(match.home_win_prob * 100);
  const modelAwayPct = Math.round(match.away_win_prob * 100);

  const impliedHome = rec
    ? (1 - (rec.edge ?? 0) / 1) // fallback; below we compute properly from odds when available
    : null;

  // implied probabilities from the recommended odds (inverse); only reliable for
  // the bet side.  For display parity with the design we reconstruct both
  // sides from the provided model probabilities (no implied markers if absent).
  const impliedHomeProb =
    rec && rec.side === "home" && rec.recommended_odds > 0
      ? 1 / rec.recommended_odds
      : impliedHome;

  const timeLabel = match.match_time ? formatMatchTime(match.match_time) : null;

  return (
    <div
      className="card"
      style={{
        padding: 18,
        position: "relative",
        overflow: "hidden",
        opacity: hasBet ? 1 : 0.78,
      }}
    >
      {hasBet && (
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: 3,
            background: ACCENT_COLOR[level],
          }}
        />
      )}

      <div
        className="hstack"
        style={{ justifyContent: "space-between", marginBottom: 14 }}
      >
        <div
          className="hstack gap-2"
          style={{ fontSize: 11.5, color: "var(--text-mute)" }}
        >
          {timeLabel && <span className="mono">{timeLabel}</span>}
          {timeLabel && match.venue && <span style={{ opacity: 0.4 }}>·</span>}
          {match.venue && <span>{match.venue}</span>}
          {match.round_label && (
            <>
              <span style={{ opacity: 0.4 }}>·</span>
              <span className="mono">{match.round_label}</span>
            </>
          )}
        </div>
        <ConfidenceBadge level={level} />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto 1fr",
          alignItems: "center",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <TeamLine
          brand={home}
          modelPct={modelHomePct}
          tabOdds={rec && rec.side === "home" ? rec.recommended_odds : null}
          highlight={hasBet && rec!.side === "home"}
          align="left"
        />
        <div
          className="mono"
          style={{ fontSize: 11, color: "var(--text-mute)", padding: "0 6px" }}
        >
          vs
        </div>
        <TeamLine
          brand={away}
          modelPct={modelAwayPct}
          tabOdds={rec && rec.side === "away" ? rec.recommended_odds : null}
          highlight={hasBet && rec!.side === "away"}
          align="right"
        />
      </div>

      <div style={{ marginBottom: hasBet ? 16 : 0 }}>
        <div
          className="hstack"
          style={{ justifyContent: "space-between", marginBottom: 5 }}
        >
          <span
            className="mono"
            style={{ fontSize: 11, color: "var(--text-dim)" }}
          >
            Model win probability
          </span>
          {impliedHomeProb != null && (
            <span
              className="mono"
              style={{ fontSize: 11, color: "var(--text-mute)" }}
            >
              TAB implied {Math.round(impliedHomeProb * 100)} /{" "}
              {Math.round((1 - impliedHomeProb) * 100)}
            </span>
          )}
        </div>
        <div
          style={{
            height: 8,
            borderRadius: 4,
            background: "var(--bg-3)",
            display: "flex",
            overflow: "hidden",
            position: "relative",
          }}
        >
          <div
            style={{
              width: `${modelHomePct}%`,
              background: `linear-gradient(90deg, ${home.color}cc, ${home.color})`,
              transition: "width 600ms cubic-bezier(0.16,1,0.3,1)",
            }}
          />
          <div
            style={{
              width: `${modelAwayPct}%`,
              background: `linear-gradient(90deg, ${away.color}, ${away.color}cc)`,
            }}
          />
          {impliedHomeProb != null && (
            <div
              title="TAB implied (home)"
              style={{
                position: "absolute",
                top: -2,
                bottom: -2,
                left: `${impliedHomeProb * 100}%`,
                width: 2,
                background: "#e6ecf7",
                opacity: 0.5,
              }}
            />
          )}
        </div>
        <div
          className="hstack"
          style={{ justifyContent: "space-between", marginTop: 4 }}
        >
          <span
            className="mono"
            style={{ fontSize: 11, color: "var(--text)", fontWeight: 600 }}
          >
            {modelHomePct}%
          </span>
          <span
            className="mono"
            style={{ fontSize: 11, color: "var(--text)", fontWeight: 600 }}
          >
            {modelAwayPct}%
          </span>
        </div>
      </div>

      {hasBet && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 1,
            background: "var(--line)",
            borderRadius: 10,
            overflow: "hidden",
            border: "1px solid var(--line)",
          }}
        >
          <BetStat
            label="Edge"
            value={rec!.edge != null ? `+${(rec!.edge * 100).toFixed(1)}%` : "—"}
            tone="positive"
          />
          <BetStat
            label="Kelly"
            value={`${(rec!.kelly_fraction * 100).toFixed(1)}%`}
            tone="neutral"
          />
          <BetStat
            label="Stake"
            value={
              rec!.suggested_stake_aud != null
                ? `$${Math.round(rec!.suggested_stake_aud)}`
                : "—"
            }
            tone="accent"
          />
        </div>
      )}
    </div>
  );
}

function TeamLine({
  brand,
  modelPct: _modelPct,
  tabOdds,
  highlight,
  align,
}: {
  brand: { abbr: string; name: string; color: string; accent: string };
  modelPct: number;
  tabOdds: number | null;
  highlight: boolean;
  align: "left" | "right";
}) {
  return (
    <div
      className="hstack gap-3"
      style={{ flexDirection: align === "right" ? "row-reverse" : "row" }}
    >
      <Crest code={brand.abbr} size={36} />
      <div style={{ textAlign: align, minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: highlight ? "var(--accent)" : "var(--text)",
            lineHeight: 1.2,
          }}
        >
          {brand.name}
        </div>
        {tabOdds != null && (
          <div
            className="mono"
            style={{ fontSize: 11, color: "var(--text-mute)", marginTop: 2 }}
          >
            TAB {tabOdds.toFixed(2)}
          </div>
        )}
      </div>
    </div>
  );
}

function BetStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "positive" | "negative" | "accent" | "neutral";
}) {
  const color = {
    positive: "var(--green)",
    negative: "var(--red)",
    accent: "var(--accent)",
    neutral: "var(--text)",
  }[tone];
  return (
    <div style={{ padding: "10px 12px", background: "var(--bg-2)" }}>
      <div
        style={{
          fontSize: 10.5,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--text-mute)",
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        className="mono"
        style={{
          fontSize: 16,
          fontWeight: 600,
          color,
          marginTop: 3,
          letterSpacing: "-0.01em",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function formatMatchTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="card" style={{ padding: 20, color: "var(--text-mute)" }}>
      {label}
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div
      className="card"
      style={{ padding: 20, color: "var(--red)", fontSize: 13 }}
    >
      Error loading data: {message}
    </div>
  );
}

export function useTodayPicksForHeader(): TodayPicksResponse | undefined {
  return useApi("/api/dashboard/today-picks", {
    refreshInterval: REFRESH_TODAY_MS,
  }).data;
}
