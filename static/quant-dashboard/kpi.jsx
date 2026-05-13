// KPI strip — value strings come from window.AFLLive when available, else the
// mock fallbacks shipped in the design prototype.
const { Sparkline } = window.AFLCharts;

function KpiCard({ label, value, unit, sub, delta, deltaDir, spark, sparkColor }) {
  const arrow = deltaDir === "up" ? "▲" : deltaDir === "down" ? "▼" : "—";
  return (
    <div className="kpi">
      <div className="kpi-label">
        <span>{label}</span>
        {sub && <span className="muted" style={{textTransform:"none", letterSpacing:0, fontSize:10}}>{sub}</span>}
      </div>
      <div className="kpi-value">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      <div className="kpi-meta">
        <span className={`delta ${deltaDir}`}>{arrow} {delta}</span>
        {spark && <Sparkline data={spark} color={sparkColor || "var(--mint)"} w={84} h={22}/>}
      </div>
    </div>
  );
}

// ---- live → display helpers ---------------------------------------------

function _fmtInt(n) {
  if (n == null || Number.isNaN(n)) return null;
  return Number(n).toLocaleString();
}

function _fmtSigned(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return null;
  const v = Number(n).toFixed(digits);
  return Number(n) > 0 ? `+${v}` : v;
}

function _fmtMoney(n) {
  if (n == null || Number.isNaN(n)) return null;
  const v = Math.round(Number(n)).toLocaleString();
  return `$${v}`;
}

function KpiStrip() {
  const D = window.AFLData;
  const L = window.AFLLive || {};
  const summary = L.performance || {};
  const bankroll = L.bankroll || {};
  const clv = L.clv || {};

  // Live values when present; fall back to the design's headline mock numbers.
  const totalPredictions = _fmtInt(summary.total_bets) ?? "1,218";
  const winRate = summary.win_rate_pct != null ? Number(summary.win_rate_pct).toFixed(1) : "63.8";
  const roi = summary.roi_pct != null ? _fmtSigned(summary.roi_pct, 2) : "+7.81";
  const netProfit = summary.total_pl_units != null ? _fmtSigned(summary.total_pl_units, 0) : "+4,218";
  const bankrollValue = bankroll.current != null ? _fmtMoney(bankroll.current) : "$14,218";
  const drawdownLabel = bankroll.drawdown != null
    ? `dd ${(Number(bankroll.drawdown) * 100).toFixed(1)}%`
    : "start $10k";
  const brierBest = summary.brier_best != null ? Number(summary.brier_best).toFixed(3) : "0.214";
  const clvAvg = clv.avg_clv_pct != null ? _fmtSigned(clv.avg_clv_pct, 2) : "+2.34";

  return (
    <div className="kpi-grid">
      <KpiCard label="Total predictions" value={totalPredictions} sub="settled + pending"
        delta={summary.pending != null ? `${summary.pending} pending` : "+184 vs prev"} deltaDir="up"
        spark={D.ACCURACY_SERIES} sparkColor="#8b95a7"/>
      <KpiCard label="Win rate" value={winRate} unit="%"
        delta={summary.wins != null ? `${summary.wins}W / ${summary.losses}L` : "+1.6 pp"} deltaDir="up"
        spark={D.ACCURACY_SERIES} sparkColor="#5ef0b7"/>
      <KpiCard label="ROI" value={roi} unit="%"
        delta={summary.settled != null ? `n=${summary.settled}` : "+1.4 pp"} deltaDir="up"
        spark={D.ROI_SERIES} sparkColor="#5ef0b7"/>
      <KpiCard label="Net P/L" value={netProfit} unit="u"
        delta={summary.settled != null ? "all-time" : "+612 last 7d"} deltaDir="up"
        spark={D.CUM_PROFIT.slice(-30)} sparkColor="#5ef0b7"/>
      <KpiCard label="Bankroll" value={bankrollValue} sub={drawdownLabel}
        delta={bankroll.peak != null ? `peak ${_fmtMoney(bankroll.peak)}` : "+42.18%"} deltaDir="up"
        spark={D.BANKROLL.slice(-30)} sparkColor="#6cb6ff"/>
      <KpiCard label="Brier score" value={brierBest} sub="lower is better"
        delta="best model" deltaDir="up"
        spark={D.ACCURACY_SERIES.map(v=>1-v)} sparkColor="#a78bfa"/>
      {/* TODO: surface live log-loss from /dashboard/performance.model_runs */}
      <KpiCard label="Log loss" value="0.612" sub="lower is better"
        delta="−0.026" deltaDir="up"
        spark={D.ACCURACY_SERIES.map(v=>1-v*0.9)} sparkColor="#a78bfa"/>
      <KpiCard label="CLV" value={clvAvg} unit="%" sub="closing line value"
        delta={clv.beat_closing_line != null
          ? `beats ${(Number(clv.beat_closing_line) * 100).toFixed(0)}%`
          : "+0.41 pp"} deltaDir="up"
        spark={D.ROI_SERIES.map(v=>v*0.4+1)} sparkColor="#f5c45e"/>
    </div>
  );
}

window.KpiStrip = KpiStrip;
