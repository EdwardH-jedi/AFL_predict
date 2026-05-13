// Recent predictions table
function fmtDate(d) {
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const hh = String(d.getHours()).padStart(2,"0");
  const mm = String(d.getMinutes()).padStart(2,"0");
  return `${months[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")} · ${hh}:${mm}`;
}

function ConfPips({ n }) {
  return (
    <span className="conf-pip">
      {[0,1,2,3,4].map(i => <span key={i} className={"pip " + (i < n ? "on" : "")}/>)}
    </span>
  );
}

function PredictionsTable() {
  const D = window.AFLData;
  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-title">Recent predictions</div>
        </div>
        <div className="section-actions">
          <div className="filter">
            <span className="label">Result</span>
            <span className="value">All</span>
            <window.I.Chevron/>
          </div>
          <div className="filter">
            <span className="label">Edge</span>
            <span className="value">≥ 1%</span>
            <window.I.Chevron/>
          </div>
          <button className="btn"><window.I.Eye/> Open log</button>
          <button className="btn"><window.I.Download/> CSV</button>
        </div>
      </div>
      <div className="card">
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Date</th>
                <th>Match</th>
                <th>Pick</th>
                <th className="num-c">Pred p</th>
                <th className="num-c">Odds</th>
                <th className="num-c">Implied p</th>
                <th className="num-c">Edge</th>
                <th>Result</th>
                <th className="num-c">P/L</th>
                <th>Conf.</th>
                <th>Model</th>
              </tr>
            </thead>
            <tbody>
              {D.PICKS.map((p, i) => {
                const edgePos = p.edge >= 0;
                return (
                  <tr key={i}>
                    <td className="muted">{fmtDate(p.date)}</td>
                    <td>
                      <div className="match">
                        <span className="team-chip">
                          <span className="team-dot" style={{background: p.home.c}}></span>
                          {p.home.code}
                        </span>
                        <span className="muted">vs</span>
                        <span className="team-chip">
                          <span className="team-dot" style={{background: p.away.c}}></span>
                          {p.away.code}
                        </span>
                      </div>
                    </td>
                    <td className="pick">
                      <span className="team-chip">
                        <span className="team-dot" style={{background: p.pick.c}}></span>
                        {p.pick.name}
                      </span>
                    </td>
                    <td className="num-c">{(p.pred*100).toFixed(1)}%</td>
                    <td className="num-c">{p.odds.toFixed(2)}</td>
                    <td className="num-c muted">{(p.impl*100).toFixed(1)}%</td>
                    <td className="num-c">
                      <span className={"edge " + (edgePos ? "pos" : "neg")}>
                        {edgePos ? "+" : ""}{p.edge.toFixed(1)}%
                      </span>
                    </td>
                    <td>
                      {p.result === "W" && <span className="res-w">W</span>}
                      {p.result === "L" && <span className="res-l">L</span>}
                      {p.result === "P" && <span className="res-p">P</span>}
                    </td>
                    <td className={"num-c " + (p.pl > 0 ? "pos" : p.pl < 0 ? "neg" : "")}>
                      {p.pl > 0 ? "+" : ""}{p.pl !== 0 ? "$" + Math.abs(p.pl).toFixed(2) : "—"}
                      {p.pl < 0 && <span style={{position:"absolute"}}></span>}
                    </td>
                    <td><ConfPips n={p.conf}/></td>
                    <td>
                      <span className="tag" style={{
                        color: p.version === "v4.2.1" ? "var(--mint)" : "var(--ink-2)",
                        borderColor: p.version === "v4.2.1" ? "rgba(94,240,183,0.25)" : undefined,
                        background: p.version === "v4.2.1" ? "rgba(94,240,183,0.05)" : undefined,
                      }}>{p.version}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{
          padding: "10px 14px", borderTop: "1px solid var(--line)",
          display:"flex", justifyContent:"space-between", alignItems:"center",
          fontSize: 11, color: "var(--ink-3)", fontFamily: "JetBrains Mono"
        }}>
          <span>Showing 24 of 1,218 predictions</span>
          <span style={{display:"flex", gap: 6, alignItems: "center"}}>
            <button className="btn" style={{padding:"3px 8px"}}>‹</button>
            <span>Page 1 / 51</span>
            <button className="btn" style={{padding:"3px 8px"}}>›</button>
          </span>
        </div>
      </div>
    </>
  );
}

window.PredictionsTable = PredictionsTable;
