import { SectionHeader } from "@/components/SectionHeader";
import { REFRESH_STATUS_MS, useApi } from "@/hooks/useApi";
import type { JobStatus, SystemStatusResponse } from "@/types";

const CORE_JOB_LABEL: Record<string, string> = {
  ingest_afl: "AFL ingestion",
  ingest_tab_odds: "TAB odds ingestion",
  build_features: "Feature build",
  generate_recommendations: "Recommendation engine",
  settle_results: "Result settlement",
};

export function TabStatus() {
  const { data, isLoading, error } = useApi("/api/dashboard/system-status", {
    refreshInterval: REFRESH_STATUS_MS,
  });

  if (isLoading && !data)
    return (
      <div className="card" style={{ padding: 20, color: "var(--text-mute)" }}>
        Loading system status…
      </div>
    );
  if (error)
    return (
      <div className="card" style={{ padding: 20, color: "var(--red)" }}>
        Error: {String(error)}
      </div>
    );
  if (!data) return null;

  const oddsApi = data.odds_api;
  const oddsApiPct =
    oddsApi.monthly_limit > 0
      ? (oddsApi.monthly_used_estimate / oddsApi.monthly_limit) * 100
      : 0;

  const phaseBlocks = derivePhaseBlocks(data);

  return (
    <div className="vstack gap-6 fade-up">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: 12,
        }}
      >
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div
            style={{
              padding: "16px 18px",
              borderBottom: "1px solid var(--line)",
            }}
          >
            <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
              Data Pipeline
            </h2>
            <div
              style={{
                fontSize: 12,
                color: "var(--text-mute)",
                marginTop: 2,
              }}
            >
              Node role: {data.node_role} · {data.jobs.length} core jobs tracked
            </div>
          </div>
          {data.jobs.map((job) => (
            <JobRow key={job.job_name} job={job} />
          ))}
        </div>

        <div className="card" style={{ padding: 20 }}>
          <SectionHeader
            title="Odds API Credits"
            subtitle={`Month ${oddsApi.month} · estimated from successful ingest runs`}
          />
          <div
            className="hstack"
            style={{
              alignItems: "baseline",
              gap: 6,
              marginTop: 10,
              marginBottom: 14,
            }}
          >
            <span
              className="mono"
              style={{
                fontSize: 34,
                fontWeight: 600,
                letterSpacing: "-0.02em",
              }}
            >
              {oddsApi.monthly_remaining_estimate}
            </span>
            <span
              className="mono"
              style={{ fontSize: 16, color: "var(--text-mute)" }}
            >
              / {oddsApi.monthly_limit} remaining
            </span>
          </div>
          <div className="bar" style={{ height: 10, marginBottom: 8 }}>
            <span
              style={{
                width: `${Math.max(0, Math.min(100, 100 - oddsApiPct))}%`,
                background:
                  oddsApiPct > 85
                    ? "var(--red)"
                    : oddsApiPct > 65
                      ? "var(--amber)"
                      : "var(--green)",
              }}
            />
          </div>
          <div
            className="hstack"
            style={{
              justifyContent: "space-between",
              fontSize: 11,
              color: "var(--text-mute)",
            }}
          >
            <span className="mono">Used: {oddsApi.monthly_used_estimate}</span>
            <span className="mono">{oddsApi.note}</span>
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <SectionHeader
          title="Rollout Phase"
          subtitle="Gated progression toward live TAB execution"
        />
        <div className="hstack gap-4" style={{ flexWrap: "wrap" }}>
          {phaseBlocks.map((p, i) => (
            <PhasePill
              key={p.id}
              phase={p}
              idx={i}
              total={phaseBlocks.length}
            />
          ))}
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
            title="Live-Readiness Check"
            subtitle={`Overall: ${data.readiness_overall.toUpperCase()}`}
          />
          <div className="vstack gap-2">
            {data.readiness_checks.map((c) => (
              <ReadinessRow key={c.name} check={c} />
            ))}
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <SectionHeader
            title="Database"
            subtitle="Row counts per primary table"
          />
          <div className="vstack gap-2">
            {Object.entries(data.db_rows).map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  alignItems: "baseline",
                  padding: "12px 14px",
                  background: "var(--bg-2)",
                  borderRadius: 8,
                  border: "1px solid var(--line)",
                }}
              >
                <div>
                  <div
                    className="mono"
                    style={{ fontSize: 12, color: "var(--text-dim)" }}
                  >
                    {k}
                  </div>
                  <div
                    style={{
                      fontSize: 10.5,
                      color: "var(--text-mute)",
                      marginTop: 2,
                    }}
                  >
                    {describeTable(k)}
                  </div>
                </div>
                <div
                  className="mono"
                  style={{
                    fontSize: 20,
                    fontWeight: 600,
                    letterSpacing: "-0.01em",
                  }}
                >
                  {v.toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function JobRow({ job }: { job: JobStatus }) {
  const label = CORE_JOB_LABEL[job.job_name] ?? job.job_name;
  const healthy =
    job.last_status === "success" && (job.age_hours ?? Infinity) < 48;
  const stale =
    job.last_status === "success" && (job.age_hours ?? 0) >= 48;

  const dotColor = healthy
    ? "var(--green)"
    : stale
      ? "var(--amber)"
      : job.last_status == null
        ? "var(--text-mute)"
        : "var(--red)";
  const ringColor = healthy
    ? "rgba(16,185,129,0.15)"
    : stale
      ? "rgba(245,158,11,0.15)"
      : job.last_status == null
        ? "rgba(90,103,130,0.15)"
        : "rgba(239,68,68,0.15)";

  return (
    <div
      className="hstack"
      style={{
        justifyContent: "space-between",
        padding: "14px 16px",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <div className="hstack gap-3">
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: 50,
            background: dotColor,
            boxShadow: `0 0 0 4px ${ringColor}`,
            animation: healthy ? "pulse-dot 2s ease-in-out infinite" : "none",
          }}
        />
        <div>
          <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
          <div
            className="mono"
            style={{
              fontSize: 11,
              color: "var(--text-mute)",
              marginTop: 2,
            }}
          >
            {job.job_name} · retries {job.retry_count ?? 0}
          </div>
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-mute)",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
          }}
        >
          Last run
        </div>
        <div
          className="mono"
          style={{
            fontSize: 12,
            color: healthy ? "var(--text)" : stale ? "var(--amber)" : "var(--red)",
            fontWeight: 600,
            marginTop: 2,
          }}
        >
          {job.age_hours == null
            ? "—"
            : job.age_hours < 1
              ? `${Math.round(job.age_hours * 60)} min ago`
              : `${job.age_hours.toFixed(1)}h ago`}
        </div>
      </div>
    </div>
  );
}

type PhaseBlock = {
  id: number;
  label: string;
  status: "done" | "active" | "pending";
  note: string;
};

function derivePhaseBlocks(s: SystemStatusResponse): PhaseBlock[] {
  const { phase, readiness_overall, db_rows, readiness_checks } = s;
  const settled = readiness_checks.find((c) => c.name === "sample_size");
  const settledNote = settled?.detail ?? `${db_rows.bet_outcomes} settled bets`;

  return [
    {
      id: 1,
      label: "Backtest",
      status: "done",
      note: `${db_rows.matches.toLocaleString()} matches · ${db_rows.predictions.toLocaleString()} predictions`,
    },
    {
      id: 2,
      label: "Paper Trade",
      status: phase === "live_trial_candidate" ? "done" : "active",
      note: settledNote,
    },
    {
      id: 3,
      label: "TAB Live",
      status:
        readiness_overall === "ready"
          ? "active"
          : phase === "live_trial_candidate"
            ? "active"
            : "pending",
      note:
        readiness_overall === "ready"
          ? "All readiness checks passing"
          : "Unlocks when live-readiness = ready",
    },
  ];
}

function PhasePill({
  phase,
  idx,
  total,
}: {
  phase: PhaseBlock;
  idx: number;
  total: number;
}) {
  const cfg = {
    done: {
      icon: "✓",
      bg: "rgba(16,185,129,0.1)",
      border: "rgba(16,185,129,0.4)",
      fg: "#10b981",
      label: "Complete",
    },
    active: {
      icon: "◐",
      bg: "rgba(125,211,252,0.1)",
      border: "rgba(125,211,252,0.4)",
      fg: "#7dd3fc",
      label: "Active",
    },
    pending: {
      icon: "○",
      bg: "rgba(90,103,130,0.08)",
      border: "rgba(90,103,130,0.3)",
      fg: "#5a6782",
      label: "Locked",
    },
  }[phase.status];

  return (
    <div style={{ flex: 1, position: "relative", minWidth: 240 }}>
      <div
        style={{
          padding: 14,
          background: cfg.bg,
          border: `1px solid ${cfg.border}`,
          borderRadius: 10,
        }}
      >
        <div
          className="hstack"
          style={{ justifyContent: "space-between", marginBottom: 8 }}
        >
          <div className="hstack gap-2">
            <div
              style={{
                width: 22,
                height: 22,
                borderRadius: 50,
                background: cfg.bg,
                border: `1px solid ${cfg.border}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
                color: cfg.fg,
                fontWeight: 600,
              }}
            >
              {cfg.icon}
            </div>
            <span
              className="mono"
              style={{
                fontSize: 10,
                color: "var(--text-mute)",
                letterSpacing: "0.08em",
              }}
            >
              PHASE {phase.id}
            </span>
          </div>
          <span
            style={{
              fontSize: 10.5,
              color: cfg.fg,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {cfg.label}
          </span>
        </div>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{phase.label}</div>
        <div
          className="mono"
          style={{
            fontSize: 11,
            color: "var(--text-dim)",
            marginTop: 4,
          }}
        >
          {phase.note}
        </div>
      </div>
      {idx < total - 1 && (
        <div
          style={{
            position: "absolute",
            right: -10,
            top: "50%",
            transform: "translateY(-50%)",
            color: "var(--text-mute)",
            fontSize: 16,
            zIndex: 2,
          }}
        >
          →
        </div>
      )}
    </div>
  );
}

function ReadinessRow({
  check,
}: {
  check: { name: string; status: string; detail: string };
}) {
  const color =
    check.status === "pass"
      ? "var(--green)"
      : check.status === "warn"
        ? "var(--amber)"
        : check.status === "fail"
          ? "var(--red)"
          : "var(--text-mute)";
  return (
    <div
      style={{
        padding: 14,
        background: "var(--bg-2)",
        borderRadius: 10,
        border: "1px solid var(--line)",
      }}
    >
      <div
        className="hstack"
        style={{ justifyContent: "space-between", marginBottom: 8 }}
      >
        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
          {check.name}
        </span>
        <span
          className="mono"
          style={{
            fontSize: 10.5,
            color,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            fontWeight: 600,
          }}
        >
          {check.status}
        </span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: "var(--text)",
        }}
      >
        {check.detail}
      </div>
    </div>
  );
}

function describeTable(name: string): string {
  switch (name) {
    case "matches":
      return "AFL fixtures + results";
    case "predictions":
      return "Per-match model outputs";
    case "recommendations":
      return "Paper-trade bets";
    case "odds_snapshots":
      return "TAB price history";
    case "bet_outcomes":
      return "Settled bet ledger";
    case "bankroll_logs":
      return "Bankroll movement log";
    default:
      return "";
  }
}
