// Sidebar + Topbar
const { useState } = React;

function Sidebar() {
  const items = [
    { sec: "Workspace", items: [
      { name: "Overview", icon: "Dashboard", active: true },
      { name: "Predictions", icon: "Activity", badge: "1.2k" },
      { name: "Calibration", icon: "Target" },
      { name: "Betting log", icon: "Cash", badge: "612" },
      { name: "Backtests", icon: "Layers" },
    ]},
    { sec: "Models", items: [
      { name: "Versions", icon: "GitBranch", badge: "5" },
      { name: "Compare", icon: "Compare" },
      { name: "Features", icon: "Sliders" },
    ]},
    { sec: "Data", items: [
      { name: "Matches", icon: "Trophy" },
      { name: "Markets", icon: "Globe" },
      { name: "Feeds", icon: "Database", badge: "3" },
    ]},
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">A</div>
        <div>
          <div className="brand-name">AFL<span className="dim">_predict</span></div>
          <div className="brand-meta">v4.2.1 · main</div>
        </div>
      </div>
      {items.map((g, i) => (
        <div className="nav-section" key={i}>
          <div className="nav-label">{g.sec}</div>
          {g.items.map((it, j) => {
            const Ico = window.I[it.icon];
            return (
              <div key={j} className={"nav-item " + (it.active ? "active" : "")}>
                {Ico && <Ico size={14}/>}
                <span>{it.name}</span>
                {it.badge && <span className="badge">{it.badge}</span>}
              </div>
            );
          })}
        </div>
      ))}
      <div className="sidebar-footer">
        <div className="avatar">JM</div>
        <div>
          <div className="user-name">J. Mulligan</div>
          <div className="user-meta">analyst · solo</div>
        </div>
      </div>
    </aside>
  );
}

function TopBar() {
  return (
    <div className="topbar">
      <div className="topbar-row">
        <div className="crumbs">
          <span>Workspace</span><span className="sep">/</span>
          <strong>Overview</strong>
        </div>
        <span className="live-pill"><span className="live-dot"></span>Live · sync 12s ago</span>
        <div className="spacer"></div>
        <div className="search">
          <window.I.Search size={12}/>
          <input placeholder="Search picks, matches, runs…"/>
          <span className="kbd">⌘K</span>
        </div>
        <button className="icon-btn" title="Notifications"><window.I.Bell/></button>
        <button className="icon-btn" title="Help"><window.I.Help/></button>
        <button className="icon-btn" title="Settings"><window.I.Settings/></button>
      </div>
      <div className="topbar-row">
        <div className="filters">
          <div className="filter">
            <window.I.Calendar/>
            <span className="label">Range</span>
            <span className="value">Apr 14 – May 04, 2026</span>
            <window.I.Chevron/>
          </div>
          <div className="filter">
            <span className="label">Season</span>
            <span className="value">2026 · Home & Away</span>
            <window.I.Chevron/>
          </div>
          <div className="filter">
            <span className="label">Market</span>
            <span className="value">All markets</span>
            <window.I.Chevron/>
          </div>
          <div className="filter">
            <span className="label">Team</span>
            <span className="value">All teams</span>
            <window.I.Chevron/>
          </div>
          <div className="divider-v"></div>
          <div className="filter">
            <window.I.GitBranch/>
            <span className="label">Model</span>
            <span className="value">v4.2.1 <span style={{color:"var(--mint)"}}>●</span></span>
            <window.I.Chevron/>
          </div>
          <div className="filter dotted">
            <window.I.Plus/>
            <span>Add filter</span>
          </div>
        </div>
        <div className="spacer"></div>
        <button className="btn"><window.I.Compare/> Compare versions</button>
        <button className="btn"><window.I.Refresh/> Refresh</button>
        <button className="btn primary"><window.I.Download/> Export</button>
      </div>
    </div>
  );
}

window.Sidebar = Sidebar;
window.TopBar = TopBar;
