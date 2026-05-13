// Performance over time + Diagnostics + Betting + Segments
const { LineChart, BarChart, CalibrationChart, Histogram, Scatter, Donut, HeatStrip, CHART_COLORS } = window.AFLCharts;

const ROUND_LABELS = ["R1","R3","R5","R7","R9","R11","R13","R15","R17","R19","R21","R23"];
const DAY_LABELS = ["Apr 14","Apr 18","Apr 22","Apr 26","Apr 30","May 04"];

function CardHead({ title, sub, right }) {
  return (
    <div className="card-head">
      <div>
        <div className="card-title">{title}</div>
        {sub && <div className="card-sub" style={{marginTop:3}}>{sub}</div>}
      </div>
      <div className="card-actions">
        {right}
        <button className="icon-btn"><window.I.More/></button>
      </div>
    </div>
  );
}

function MiniTabs({ items, active }) {
  return (
    <div className="tab-row">
      {items.map((t, i) => (
        <div key={i} className={"tab " + (i === active ? "active" : "")}>{t}</div>
      ))}
    </div>
  );
}

// === SECTION: Performance over time ===
function PerformanceSection() {
  const D = window.AFLData;
  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-title">Performance over time</div>
        </div>
        <div className="section-actions">
          <MiniTabs items={["Daily","Weekly","Round","Season"]} active={2}/>
          <span className="eyebrow" style={{marginLeft:6}}>last 28 rounds</span>
        </div>
      </div>
      <div className="grid-perf">
        <div className="card">
          <CardHead title="Accuracy over time" sub="rolling 14-game window"
            right={<span className="big-stat" style={{marginRight:8}}>
              <span className="v">63.8%</span><span className="d delta up">▲ +1.6pp</span>
            </span>}/>
          <div className="card-pad">
            <LineChart series={[{ data: D.ACCURACY_SERIES, color: CHART_COLORS.mint }]}
              h={200} yTicks={4} baseline={0.5}
              format={v => (v * 100).toFixed(0) + "%"} xLabels={ROUND_LABELS}/>
            <div className="legend" style={{marginTop:6}}>
              <span><span className="legend-dot" style={{background: CHART_COLORS.mint}}></span>Model accuracy</span>
              <span><span className="legend-dot" style={{background: CHART_COLORS.ink3}}></span>Coin-flip baseline 50%</span>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="ROI over time" sub="per-bet ROI, 14-bet rolling"
            right={<span className="big-stat" style={{marginRight:8}}>
              <span className="v">+7.81%</span><span className="d delta up">▲ +1.4pp</span>
            </span>}/>
          <div className="card-pad">
            <LineChart series={[{ data: D.ROI_SERIES, color: CHART_COLORS.azure }]}
              h={200} yTicks={4} baseline={0}
              format={v => v.toFixed(1) + "%"} xLabels={ROUND_LABELS}/>
            <div className="legend" style={{marginTop:6}}>
              <span><span className="legend-dot" style={{background: CHART_COLORS.azure}}></span>Rolling ROI</span>
              <span><span className="legend-dot" style={{background: CHART_COLORS.ink3}}></span>Break-even 0%</span>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="Cumulative profit" sub="units staked = 1u flat"
            right={<span className="big-stat" style={{marginRight:8}}>
              <span className="v">+84.2u</span><span className="d delta up">▲ all-time</span>
            </span>}/>
          <div className="card-pad">
            <LineChart series={[{ data: D.CUM_PROFIT, color: CHART_COLORS.mint }]}
              h={200} yTicks={4} baseline={0}
              format={v => v.toFixed(0) + "u"} xLabels={DAY_LABELS}/>
          </div>
        </div>
        <div className="card">
          <CardHead title="Bankroll curve" sub="Kelly ¼ · start $10,000"
            right={<span className="big-stat" style={{marginRight:8}}>
              <span className="v">$14,218</span><span className="d delta up">▲ +42.18%</span>
            </span>}/>
          <div className="card-pad">
            <LineChart series={[{ data: D.BANKROLL, color: CHART_COLORS.amber }]}
              h={200} yTicks={4} format={v => "$" + (v/1000).toFixed(1) + "k"}
              xLabels={DAY_LABELS}/>
          </div>
        </div>
      </div>
    </>
  );
}

// === SECTION: Diagnostics ===
function DiagnosticsSection() {
  const D = window.AFLData;
  // Confusion: predicted home win + actual home win, etc. Build from PICKS.
  let tp=0, fp=0, tn=0, fn=0;
  D.PICKS.forEach(p => {
    const predHome = p.pick.code === p.home.code;
    const actualHome = (predHome && p.result === "W") || (!predHome && p.result === "L");
    if (predHome && actualHome) tp++;
    else if (predHome && !actualHome) fp++;
    else if (!predHome && !actualHome) tn++;
    else fn++;
  });
  // Scale up to be more realistic
  const k = 50;
  tp *= k; fp *= k; tn *= k; fn *= k;
  const total = tp + fp + tn + fn;
  const fmt = n => n.toLocaleString();

  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-title">Probability quality &amp; model diagnostics</div>
        </div>
        <div className="section-actions">
          <span className="tag mint">ECE 0.024</span>
          <span className="tag violet">MCE 0.061</span>
          <span className="tag amber">refit due R26</span>
        </div>
      </div>
      <div className="grid-diag">
        <div className="card">
          <CardHead title="Calibration curve" sub="reliability — predicted vs observed"
            right={<MiniTabs items={["10 bins","20 bins"]} active={0}/>}/>
          <div className="card-pad">
            <CalibrationChart data={D.CALIBRATION} h={220}/>
            <div style={{display:"flex", justifyContent:"space-between", marginTop:8}}>
              <span className="eyebrow">expected calibration error</span>
              <span className="mono" style={{color:"var(--mint)"}}>0.024 · well-calibrated</span>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="Confidence buckets" sub="accuracy &amp; ROI by bin"/>
          <div className="card-pad">
            <div className="bar-list">
              {D.CONF_BUCKETS.map((b, i) => (
                <div className="bar-row" key={i}
                  style={{gridTemplateColumns:"66px 1fr 56px 56px"}}>
                  <span className="name mono" style={{fontSize:11}}>{b.label}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{width: (b.acc * 100) + "%"}}></div>
                  </div>
                  <span className="v">{(b.acc * 100).toFixed(1)}%</span>
                  <span className="v" style={{color: b.roi >= 0 ? "var(--mint)" : "var(--rose)"}}>
                    {b.roi >= 0 ? "+" : ""}{b.roi.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
            <div className="legend" style={{marginTop:8, justifyContent:"space-between"}}>
              <span>n = 2,054 predictions</span>
              <span style={{color:"var(--mint)"}}>ROI rises monotonically with confidence</span>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="Predicted probability distribution" sub="output histogram (20 bins)"/>
          <div className="card-pad">
            <Histogram data={D.PROB_DIST} h={170}/>
            <div className="hr" style={{margin:"8px 0"}}/>
            <div className="card-title" style={{marginBottom:6}}>Outcome breakdown</div>
            <div className="confusion">
              <div></div>
              <div className="cm-label">Actual: Home win</div>
              <div className="cm-label">Actual: Away win</div>
              <div className="cm-label">Pred: Home</div>
              <div className="cm-cell tp">
                <span className="pct">{(tp/total*100).toFixed(1)}%</span>
                <span className="n">TP · {fmt(tp)}</span>
              </div>
              <div className="cm-cell fp">
                <span className="pct">{(fp/total*100).toFixed(1)}%</span>
                <span className="n">FP · {fmt(fp)}</span>
              </div>
              <div className="cm-label">Pred: Away</div>
              <div className="cm-cell fn">
                <span className="pct">{(fn/total*100).toFixed(1)}%</span>
                <span className="n">FN · {fmt(fn)}</span>
              </div>
              <div className="cm-cell tn">
                <span className="pct">{(tn/total*100).toFixed(1)}%</span>
                <span className="n">TN · {fmt(tn)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

// === SECTION: Betting ===
function BettingSection() {
  const D = window.AFLData;
  const totalMarket = D.MARKETS.reduce((a,b) => a + b.n, 0);

  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-title">Betting performance analysis</div>
        </div>
        <div className="section-actions">
          <MiniTabs items={["By odds","By market","By stake","By edge"]} active={0}/>
        </div>
      </div>
      <div className="grid-bet">
        <div className="card">
          <CardHead title="Edge vs return" sub="every bet, regression overlay"
            right={<span className="eyebrow">r² 0.41</span>}/>
          <div className="card-pad">
            <Scatter points={D.EDGE_RETURN} h={240} xMin={-8} xMax={12} yMin={-50} yMax={60}/>
            <div className="legend" style={{marginTop:6, justifyContent:"space-between"}}>
              <span><span className="legend-dot" style={{background: CHART_COLORS.mint}}></span>positive return &nbsp;
                <span className="legend-dot" style={{background: CHART_COLORS.rose}}></span>loss</span>
              <span>x: model edge % · y: bet return %</span>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="Performance by odds range" sub="ROI &amp; accuracy by decimal odds bucket"/>
          <div className="card-pad">
            <BarChart data={D.ODDS_RANGE} xKey="range" yKey="roi" signed h={220}
              format={v => v.toFixed(0) + "%"}/>
            <div className="bar-list" style={{marginTop:6}}>
              {D.ODDS_RANGE.slice(0, 4).map((d, i) => (
                <div className="bar-row" key={i}
                  style={{gridTemplateColumns:"100px 1fr 50px 50px", padding: "4px 0"}}>
                  <span className="name mono" style={{fontSize:11}}>{d.range}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{width: (d.acc * 100) + "%", background: "var(--azure)"}}></div>
                  </div>
                  <span className="v">{(d.acc * 100).toFixed(0)}%</span>
                  <span className="n">n={d.n}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="grid-3">
        <div className="card">
          <CardHead title="By market type" sub="ROI · n bets"/>
          <div className="card-pad">
            <div className="row" style={{gap: 18, alignItems: "center"}}>
              <Donut size={130} thickness={16} total={totalMarket}
                data={D.MARKETS.map(m => ({ value: m.n, color: m.c }))}/>
              <div style={{flex:1}}>
                {D.MARKETS.map((m, i) => (
                  <div key={i} style={{display:"grid", gridTemplateColumns:"1fr auto auto", gap: 10, padding: "5px 0", borderBottom: "1px dashed var(--line)", alignItems:"center", fontSize: 12}}>
                    <span><span className="legend-dot" style={{background: m.c}}></span>{m.name}</span>
                    <span className="mono" style={{color: m.roi >= 0 ? "var(--mint)" : "var(--rose)"}}>
                      {m.roi >= 0 ? "+" : ""}{m.roi.toFixed(1)}%
                    </span>
                    <span className="mono muted" style={{fontSize:10, minWidth:34, textAlign:"right"}}>{m.n}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="Win rate vs confidence" sub="reliability lift"/>
          <div className="card-pad">
            <svg className="chart-svg" viewBox="0 0 360 200" width="100%" height="200" preserveAspectRatio="none">
              {/* grid */}
              {[0.5, 0.6, 0.7, 0.8].map((t, i) => {
                const y = 180 - ((t - 0.45) / 0.4) * 160;
                return <g key={i}>
                  <line x1="32" x2="350" y1={y} y2={y} stroke={CHART_COLORS.grid} strokeDasharray="2 3"/>
                  <text x="28" y={y+3} fill={CHART_COLORS.ink3} fontSize="9" textAnchor="end" fontFamily="JetBrains Mono">{(t*100).toFixed(0)}%</text>
                </g>;
              })}
              {/* identity */}
              <line x1="32" y1={180-((0.5-0.45)/0.4)*160} x2="350" y2={180-((0.83-0.45)/0.4)*160}
                stroke={CHART_COLORS.ink3} strokeDasharray="3 3" opacity="0.6"/>
              {/* curve */}
              <path d={window.AFLData.WIN_BY_CONF.map((p,i) => {
                const x = 32 + ((p.c - 0.50) / 0.30) * 318;
                const y = 180 - ((p.wr - 0.45) / 0.4) * 160;
                return (i === 0 ? "M" : "L") + x + " " + y;
              }).join(" ")} fill="none" stroke={CHART_COLORS.mint} strokeWidth="1.8"/>
              {window.AFLData.WIN_BY_CONF.map((p, i) => {
                const x = 32 + ((p.c - 0.50) / 0.30) * 318;
                const y = 180 - ((p.wr - 0.45) / 0.4) * 160;
                return <circle key={i} cx={x} cy={y} r={Math.max(2, p.n / 60)} fill={CHART_COLORS.mint} stroke="#0a0d12" strokeWidth="1"/>;
              })}
              {/* x ticks */}
              {[0.5, 0.6, 0.7, 0.8].map((t, i) => {
                const x = 32 + ((t - 0.50) / 0.30) * 318;
                return <text key={i} x={x} y="195" fill={CHART_COLORS.ink3} fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono">{(t*100).toFixed(0)}%</text>;
              })}
            </svg>
            <div className="legend" style={{marginTop:6, justifyContent:"space-between"}}>
              <span>x: confidence · y: empirical win rate</span>
              <span className="mono" style={{color: "var(--mint)"}}>+1.4pp lift</span>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="By stake strategy" sub="P/L · ROI · Sharpe"/>
          <div className="card-pad">
            <div className="bar-list">
              {window.AFLData.STRATEGIES.map((s, i) => (
                <div key={i} style={{display:"grid", gridTemplateColumns:"1fr auto auto auto", gap: 10, padding: "8px 0", borderBottom: "1px dashed var(--line)", alignItems:"center", fontSize: 12}}>
                  <span className="name" style={{color: "var(--ink-1)", fontWeight: 500}}>{s.name}</span>
                  <span className="mono" style={{color: s.pl >= 0 ? "var(--mint)" : "var(--rose)", minWidth: 50, textAlign:"right"}}>
                    {s.pl >= 0 ? "+$" : "−$"}{Math.abs(s.pl).toLocaleString()}
                  </span>
                  <span className="mono" style={{color: s.roi >= 0 ? "var(--ink-1)" : "var(--rose)", minWidth: 44, textAlign:"right"}}>
                    {s.roi >= 0 ? "+" : ""}{s.roi.toFixed(1)}%
                  </span>
                  <span className="mono muted" style={{minWidth: 32, textAlign:"right"}}>
                    {s.sharpe.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
            <div className="legend" style={{marginTop:6, justifyContent:"flex-end"}}>
              <span className="muted">Sharpe annualized · risk-free 4%</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

// === SECTION: Segments ===
function SegmentsSection() {
  const D = window.AFLData;
  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-title">Segment breakdown</div>
        </div>
        <div className="section-actions">
          <MiniTabs items={["Team","Venue","Round","Season","Model"]} active={0}/>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <CardHead title="Team performance" sub="ROI by team picked · top &amp; bottom 9"/>
          <div className="card-pad">
            <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap: 24}}>
              <div className="bar-list">
                {D.TEAM_PERF.slice(0, 9).map((t, i) => (
                  <div className="bar-row" key={i}>
                    <span className="name">
                      <span className="team-dot" style={{background: t.c}}></span> {t.name}
                    </span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{width: Math.min(100, Math.max(2, t.roi * 8)) + "%"}}></div>
                    </div>
                    <span className="v" style={{color:"var(--mint)"}}>+{t.roi.toFixed(1)}%</span>
                    <span className="n">n={t.n}</span>
                  </div>
                ))}
              </div>
              <div className="bar-list">
                {D.TEAM_PERF.slice(-9).reverse().map((t, i) => (
                  <div className="bar-row" key={i}>
                    <span className="name">
                      <span className="team-dot" style={{background: t.c}}></span> {t.name}
                    </span>
                    <div className="bar-track">
                      <div className="bar-fill neg" style={{width: Math.min(100, Math.abs(t.roi) * 8) + "%"}}></div>
                    </div>
                    <span className="v" style={{color:"var(--rose)"}}>{t.roi.toFixed(1)}%</span>
                    <span className="n">n={t.n}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div style={{display:"grid", gridTemplateRows:"auto 1fr"}}>
            <CardHead title="Home / Away · Venue" sub="acc &amp; ROI"/>
            <div className="card-pad" style={{display:"grid", gridTemplateColumns:"260px 1fr", gap: 18}}>
              <div>
                <div className="eyebrow" style={{marginBottom:8}}>Home / Away / Neutral</div>
                {D.HOME_AWAY.map((h, i) => (
                  <div key={i} className="card" style={{
                    padding: "10px 12px", marginBottom:8, background: "var(--bg-2)",
                  }}>
                    <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
                      <span style={{fontWeight:600, color:"var(--ink-0)", fontSize:12}}>{h.label}</span>
                      <span className="mono" style={{fontSize:10, color:"var(--ink-3)"}}>n={h.n}</span>
                    </div>
                    <div style={{display:"flex", gap:14, marginTop:6}}>
                      <div>
                        <div className="eyebrow">Acc</div>
                        <div className="mono" style={{fontSize:14, color:"var(--ink-0)"}}>{(h.acc*100).toFixed(1)}%</div>
                      </div>
                      <div>
                        <div className="eyebrow">ROI</div>
                        <div className="mono" style={{fontSize:14, color: h.roi >= 0 ? "var(--mint)" : "var(--rose)"}}>
                          {h.roi >= 0 ? "+" : ""}{h.roi.toFixed(1)}%
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div>
                <div className="eyebrow" style={{marginBottom:8}}>By venue · top 8</div>
                <div className="bar-list">
                  {D.VENUES.map((v, i) => (
                    <div className="bar-row" key={i}
                      style={{gridTemplateColumns:"110px 1fr 56px 60px"}}>
                      <span className="name" style={{fontSize:11}}>{v.name}</span>
                      <div className="bar-track">
                        <div className="bar-fill" style={{
                          width: Math.min(100, Math.max(4, Math.abs(v.roi)*9)) + "%",
                          background: v.roi >= 0 ? "var(--mint)" : "var(--rose)",
                        }}></div>
                      </div>
                      <span className="v" style={{color: v.roi >= 0 ? "var(--mint)" : "var(--rose)"}}>
                        {v.roi >= 0 ? "+" : ""}{v.roi.toFixed(1)}%
                      </span>
                      <span className="n">n={v.n}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <CardHead title="By round" sub="ROI heat · season 2026 (rounds 1–24)"/>
          <div className="card-pad">
            <HeatStrip data={D.ROUND_PERF} h={48} getLabel={d => "R" + d.r}/>
            <div className="legend" style={{marginTop:10, justifyContent:"space-between"}}>
              <span className="muted">−10%</span>
              <div style={{display:"flex", gap:2, flex:1, margin:"0 12px"}}>
                {Array.from({length:14}).map((_,i)=>(
                  <div key={i} style={{flex:1, height:6, borderRadius:1,
                    background: i < 7
                      ? `rgba(255,107,129,${0.18 + (1 - i/7) * 0.7})`
                      : `rgba(94,240,183,${0.18 + ((i-7)/7) * 0.7})`}}></div>
                ))}
              </div>
              <span className="muted">+10%</span>
            </div>
          </div>
        </div>
        <div className="card">
          <CardHead title="By season &amp; model version" sub="historical comparison"/>
          <div className="card-pad" style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap: 18}}>
            <div>
              <div className="eyebrow" style={{marginBottom:8}}>Season</div>
              <div className="bar-list">
                {D.SEASON_PERF.map((s, i) => (
                  <div className="bar-row" key={i}
                    style={{gridTemplateColumns:"54px 1fr 50px 50px"}}>
                    <span className="name mono" style={{fontSize:11}}>{s.y}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{width: Math.min(100, s.roi*10) + "%"}}></div>
                    </div>
                    <span className="v" style={{color:"var(--mint)"}}>+{s.roi.toFixed(1)}%</span>
                    <span className="n">{(s.acc*100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="eyebrow" style={{marginBottom:8}}>Model version</div>
              <div className="bar-list">
                {D.MODEL_VERSIONS.map((m, i) => (
                  <div className="bar-row" key={i}
                    style={{gridTemplateColumns:"66px 1fr 50px 70px"}}>
                    <span className="name mono" style={{fontSize:11, color: i === 0 ? "var(--mint)" : "var(--ink-1)"}}>
                      {m.v}{i === 0 ? " ●" : ""}
                    </span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{
                        width: Math.min(100, m.roi*10) + "%",
                        background: m.roi >= 0 ? "var(--mint)" : "var(--rose)",
                      }}></div>
                    </div>
                    <span className="v" style={{color: m.roi >= 0 ? "var(--mint)" : "var(--rose)"}}>
                      {m.roi >= 0 ? "+" : ""}{m.roi.toFixed(1)}%
                    </span>
                    <span className="n" style={{
                      color: m.status === "current" ? "var(--mint)"
                        : m.status === "deprecated" ? "var(--ink-3)" : "var(--ink-2)"
                    }}>{m.status}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

window.PerformanceSection = PerformanceSection;
window.DiagnosticsSection = DiagnosticsSection;
window.BettingSection = BettingSection;
window.SegmentsSection = SegmentsSection;
