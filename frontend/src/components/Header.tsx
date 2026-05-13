import type { OddsTrackerResponse, TodayPicksResponse } from "@/types";

interface HeaderProps {
  picks: TodayPicksResponse | undefined;
  odds: OddsTrackerResponse | undefined;
}

export function Header({ picks, odds }: HeaderProps) {
  const bankroll = picks?.bankroll.live_balance_aud ?? picks?.bankroll.paper_balance;
  const round = odds?.round_number ?? null;

  return (
    <header
      style={{
        borderBottom: "1px solid var(--line)",
        background:
          "linear-gradient(180deg, rgba(15,22,40,0.9), rgba(7,11,20,0.7))",
        backdropFilter: "blur(12px)",
        position: "sticky",
        top: 0,
        zIndex: 20,
      }}
    >
      <div
        style={{
          maxWidth: 1320,
          margin: "0 auto",
          padding: "14px 24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 20,
        }}
      >
        <div className="hstack gap-3">
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 9,
              background: "linear-gradient(135deg, #10b981, #059669)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#02140c",
              fontWeight: 700,
              fontSize: 15,
              fontFamily: "JetBrains Mono, monospace",
              boxShadow: "0 4px 16px rgba(16,185,129,0.3)",
            }}
          >
            AP
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-0.01em" }}>
              AFL Predict
            </div>
            <div
              className="mono"
              style={{ fontSize: 11, color: "var(--text-mute)" }}
            >
              v2.1.0 · Ensemble{round != null ? ` · Round ${round}` : ""}
            </div>
          </div>
        </div>

        <div className="hstack gap-4 hide-mobile">
          <div style={{ textAlign: "right" }}>
            <div
              style={{
                fontSize: 10.5,
                color: "var(--text-mute)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              Bankroll
            </div>
            <div
              className="mono"
              style={{ fontSize: 15, fontWeight: 600, color: "var(--green)" }}
            >
              {bankroll != null ? `$${Math.round(bankroll).toLocaleString()}` : "—"}
            </div>
          </div>
          <div style={{ width: 1, height: 28, background: "var(--line)" }} />
          <span className="chip chip-dot" style={{ color: "var(--green)" }}>
            <span className="live-dot" />
            Paper Trade
          </span>
        </div>
      </div>
    </header>
  );
}
