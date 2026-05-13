// Chart primitives — small, sharp SVG charts tuned for dark theme.

const CHART_COLORS = {
  mint: "#5ef0b7",
  rose: "#ff6b81",
  amber: "#f5c45e",
  violet: "#a78bfa",
  azure: "#6cb6ff",
  cyan: "#5ed8e6",
  ink2: "#8b95a7",
  ink3: "#5d6678",
  grid: "rgba(255,255,255,0.05)",
  gridStrong: "rgba(255,255,255,0.09)",
};

// === Sparkline (KPI cards) ===
function Sparkline({ data, color = CHART_COLORS.mint, w = 80, h = 24, fill = true }) {
  if (!data?.length) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i) => [i * stepX, h - ((v - min) / span) * (h - 2) - 1]);
  const path = pts.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = path + ` L${w} ${h} L0 ${h} Z`;
  const id = "sparkfill-" + Math.floor(Math.random() * 1e9);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      {fill && (
        <>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.35"/>
              <stop offset="100%" stopColor={color} stopOpacity="0"/>
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${id})`}/>
        </>
      )}
      <path d={path} fill="none" stroke={color} strokeWidth="1.4"/>
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="2" fill={color}/>
    </svg>
  );
}

// === Line chart with optional area + axes ===
function LineChart({
  series, w = 600, h = 220, yLabel, xLabels,
  yTicks = 4, area = true, color = CHART_COLORS.mint, baseline,
  pad = { l: 38, r: 14, t: 12, b: 22 }, format = (v) => v.toFixed(1),
}) {
  const all = series.flatMap(s => s.data);
  let min = Math.min(...all);
  let max = Math.max(...all);
  if (baseline !== undefined) { min = Math.min(min, baseline); max = Math.max(max, baseline); }
  const span = max - min || 1;
  // Round nice
  const padFrac = 0.1;
  min -= span * padFrac; max += span * padFrac;
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const xScale = i => pad.l + (i / (series[0].data.length - 1)) * innerW;
  const yScale = v => pad.t + innerH - ((v - min) / (max - min)) * innerH;

  const ticks = [];
  for (let i = 0; i <= yTicks; i++) {
    const v = min + (max - min) * (i / yTicks);
    ticks.push({ v, y: yScale(v) });
  }

  return (
    <svg className="chart-svg" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      {/* grid */}
      {ticks.map((t, i) => (
        <line key={i} x1={pad.l} x2={w - pad.r} y1={t.y} y2={t.y}
          stroke={i === 0 ? CHART_COLORS.gridStrong : CHART_COLORS.grid} strokeDasharray={i === 0 ? "0" : "2 3"}/>
      ))}
      {/* y labels */}
      {ticks.map((t, i) => (
        <text key={i} x={pad.l - 6} y={t.y + 3}
          fill={CHART_COLORS.ink3} fontSize="9" textAnchor="end" fontFamily="JetBrains Mono, monospace">
          {format(t.v)}
        </text>
      ))}
      {/* x labels */}
      {xLabels && xLabels.map((lab, i) => {
        const idx = Math.round((i / (xLabels.length - 1)) * (series[0].data.length - 1));
        return (
          <text key={i} x={xScale(idx)} y={h - 6}
            fill={CHART_COLORS.ink3} fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">
            {lab}
          </text>
        );
      })}
      {/* baseline */}
      {baseline !== undefined && (
        <line x1={pad.l} x2={w - pad.r} y1={yScale(baseline)} y2={yScale(baseline)}
          stroke={CHART_COLORS.ink3} strokeDasharray="2 3" opacity="0.5"/>
      )}
      {/* series */}
      {series.map((s, sIdx) => {
        const c = s.color || color;
        const path = s.data.map((v, i) => (i === 0 ? "M" : "L") + xScale(i) + " " + yScale(v)).join(" ");
        const areaPath = path + ` L${xScale(s.data.length - 1)} ${pad.t + innerH} L${xScale(0)} ${pad.t + innerH} Z`;
        const gid = `line-grad-${sIdx}-${Math.floor(Math.random() * 1e9)}`;
        return (
          <g key={sIdx}>
            {area && (
              <>
                <defs>
                  <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={c} stopOpacity="0.22"/>
                    <stop offset="100%" stopColor={c} stopOpacity="0"/>
                  </linearGradient>
                </defs>
                <path d={areaPath} fill={`url(#${gid})`}/>
              </>
            )}
            <path d={path} fill="none" stroke={c} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round"/>
            <circle cx={xScale(s.data.length - 1)} cy={yScale(s.data[s.data.length - 1])} r="2.5" fill={c}/>
          </g>
        );
      })}
    </svg>
  );
}

// === Bar chart (vertical) ===
function BarChart({ data, w = 600, h = 220, color = CHART_COLORS.mint,
  pad = { l: 38, r: 14, t: 12, b: 30 }, format = (v) => v.toString(),
  yLabel, signed = false, xKey = "label", yKey = "value", colorBy = null }) {
  const vals = data.map(d => d[yKey]);
  let min = signed ? Math.min(0, ...vals) : 0;
  let max = Math.max(...vals);
  const span = max - min || 1;
  max += span * 0.1; min -= signed ? span * 0.1 : 0;
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const bw = innerW / data.length;
  const yScale = v => pad.t + innerH - ((v - min) / (max - min)) * innerH;
  const yZero = yScale(0);

  const ticks = [];
  for (let i = 0; i <= 4; i++) {
    const v = min + (max - min) * (i / 4);
    ticks.push({ v, y: yScale(v) });
  }

  return (
    <svg className="chart-svg" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      {ticks.map((t, i) => (
        <line key={i} x1={pad.l} x2={w - pad.r} y1={t.y} y2={t.y}
          stroke={Math.abs(t.v) < 0.001 ? CHART_COLORS.gridStrong : CHART_COLORS.grid} strokeDasharray={Math.abs(t.v) < 0.001 ? "0" : "2 3"}/>
      ))}
      {ticks.map((t, i) => (
        <text key={i} x={pad.l - 6} y={t.y + 3}
          fill={CHART_COLORS.ink3} fontSize="9" textAnchor="end" fontFamily="JetBrains Mono, monospace">
          {format(t.v)}
        </text>
      ))}
      {data.map((d, i) => {
        const v = d[yKey];
        const x = pad.l + i * bw + 2;
        const bWidth = bw - 4;
        const y = v >= 0 ? yScale(v) : yZero;
        const bh = Math.abs(yScale(v) - yZero);
        const c = colorBy ? colorBy(d, i) : (signed && v < 0 ? CHART_COLORS.rose : color);
        return (
          <g key={i}>
            <rect x={x} y={y} width={bWidth} height={bh} fill={c} rx="1.5" opacity="0.92"/>
            <text x={x + bWidth / 2} y={h - 16}
              fill={CHART_COLORS.ink3} fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">
              {d[xKey]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// === Calibration curve ===
function CalibrationChart({ data, w = 380, h = 260 }) {
  const pad = { l: 32, r: 12, t: 10, b: 28 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const xS = v => pad.l + v * innerW;
  const yS = v => pad.t + innerH - v * innerH;

  return (
    <svg className="chart-svg" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      {/* grid */}
      {[0, 0.25, 0.5, 0.75, 1].map((t, i) => (
        <g key={i}>
          <line x1={xS(t)} x2={xS(t)} y1={pad.t} y2={pad.t + innerH}
            stroke={CHART_COLORS.grid} strokeDasharray="2 3"/>
          <line x1={pad.l} x2={pad.l + innerW} y1={yS(t)} y2={yS(t)}
            stroke={CHART_COLORS.grid} strokeDasharray="2 3"/>
          <text x={xS(t)} y={h - 10} fill={CHART_COLORS.ink3} fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">{t.toFixed(1)}</text>
          <text x={pad.l - 6} y={yS(t) + 3} fill={CHART_COLORS.ink3} fontSize="9" textAnchor="end" fontFamily="JetBrains Mono, monospace">{t.toFixed(1)}</text>
        </g>
      ))}
      {/* perfect calibration */}
      <line x1={xS(0)} y1={yS(0)} x2={xS(1)} y2={yS(1)}
        stroke={CHART_COLORS.ink3} strokeDasharray="3 4" opacity="0.7"/>
      {/* curve */}
      <path d={data.map((d, i) => (i === 0 ? "M" : "L") + xS(d.p) + " " + yS(d.obs)).join(" ")}
        fill="none" stroke={CHART_COLORS.mint} strokeWidth="1.8"/>
      {/* points */}
      {data.map((d, i) => (
        <circle key={i} cx={xS(d.p)} cy={yS(d.obs)} r={Math.max(2, Math.min(6, d.n / 50))}
          fill={CHART_COLORS.mint} stroke="#0a0d12" strokeWidth="1"/>
      ))}
      {/* axis labels */}
      <text x={pad.l + innerW / 2} y={h - 1} fill={CHART_COLORS.ink3} fontSize="9.5" textAnchor="middle" fontFamily="Inter Tight, sans-serif">
        Predicted probability
      </text>
      <text x={10} y={pad.t + innerH / 2} fill={CHART_COLORS.ink3} fontSize="9.5" textAnchor="middle" fontFamily="Inter Tight, sans-serif"
        transform={`rotate(-90 10 ${pad.t + innerH / 2})`}>
        Observed frequency
      </text>
    </svg>
  );
}

// === Histogram ===
function Histogram({ data, w = 380, h = 200, color = CHART_COLORS.violet, format = (v) => v.toFixed(2) }) {
  const pad = { l: 32, r: 8, t: 10, b: 24 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const max = Math.max(...data);
  const bw = innerW / data.length;
  const yS = v => pad.t + innerH - (v / max) * innerH;
  return (
    <svg className="chart-svg" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      {[0, 0.5, 1].map((t, i) => (
        <line key={i} x1={pad.l} x2={pad.l + innerW} y1={pad.t + innerH * (1 - t)} y2={pad.t + innerH * (1 - t)}
          stroke={CHART_COLORS.grid} strokeDasharray="2 3"/>
      ))}
      {data.map((v, i) => {
        const x = pad.l + i * bw + 1;
        const bh = (v / max) * innerH;
        return <rect key={i} x={x} y={pad.t + innerH - bh} width={bw - 1.5} height={bh} fill={color} opacity={0.85} rx="1"/>;
      })}
      {/* x ticks: 0, 0.25, 0.5, 0.75, 1 */}
      {[0, 0.25, 0.5, 0.75, 1].map((t, i) => (
        <text key={i} x={pad.l + t * innerW} y={h - 8} fill={CHART_COLORS.ink3} fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">
          {format(t)}
        </text>
      ))}
    </svg>
  );
}

// === Scatter ===
function Scatter({ points, w = 600, h = 280, xLabel = "Edge %", yLabel = "Return %",
  xMin, xMax, yMin, yMax }) {
  const pad = { l: 38, r: 12, t: 12, b: 28 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  xMin = xMin ?? Math.min(...xs); xMax = xMax ?? Math.max(...xs);
  yMin = yMin ?? Math.min(...ys); yMax = yMax ?? Math.max(...ys);
  const xS = v => pad.l + ((v - xMin) / (xMax - xMin)) * innerW;
  const yS = v => pad.t + innerH - ((v - yMin) / (yMax - yMin)) * innerH;

  // simple regression line
  const n = points.length;
  const mx = xs.reduce((a,b)=>a+b,0)/n, my = ys.reduce((a,b)=>a+b,0)/n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) { num += (xs[i]-mx)*(ys[i]-my); den += (xs[i]-mx)**2; }
  const slope = num/den, intercept = my - slope*mx;

  const ticksX = 5, ticksY = 4;
  return (
    <svg className="chart-svg" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      {Array.from({length: ticksY+1}).map((_, i) => {
        const v = yMin + (yMax-yMin) * (i / ticksY);
        return <g key={i}>
          <line x1={pad.l} x2={pad.l+innerW} y1={yS(v)} y2={yS(v)}
            stroke={Math.abs(v) < 0.5 ? CHART_COLORS.gridStrong : CHART_COLORS.grid} strokeDasharray={Math.abs(v) < 0.5 ? "0" : "2 3"}/>
          <text x={pad.l-6} y={yS(v)+3} fill={CHART_COLORS.ink3} fontSize="9" textAnchor="end" fontFamily="JetBrains Mono, monospace">{v.toFixed(0)}</text>
        </g>;
      })}
      {Array.from({length: ticksX+1}).map((_, i) => {
        const v = xMin + (xMax-xMin) * (i / ticksX);
        return <g key={i}>
          <line x1={xS(v)} x2={xS(v)} y1={pad.t} y2={pad.t+innerH}
            stroke={Math.abs(v) < 0.5 ? CHART_COLORS.gridStrong : CHART_COLORS.grid} strokeDasharray={Math.abs(v) < 0.5 ? "0" : "2 3"}/>
          <text x={xS(v)} y={h-10} fill={CHART_COLORS.ink3} fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">{v.toFixed(0)}</text>
        </g>;
      })}
      {/* regression */}
      <line x1={xS(xMin)} y1={yS(intercept + slope*xMin)} x2={xS(xMax)} y2={yS(intercept + slope*xMax)}
        stroke={CHART_COLORS.mint} strokeDasharray="3 3" opacity="0.6"/>
      {/* points */}
      {points.map((p, i) => (
        <circle key={i} cx={xS(p.x)} cy={yS(p.y)} r={p.r || 2.5}
          fill={p.y >= 0 ? CHART_COLORS.mint : CHART_COLORS.rose} opacity="0.55"/>
      ))}
    </svg>
  );
}

// === Donut ===
function Donut({ data, total, size = 140, thickness = 18 }) {
  const r = size / 2 - thickness / 2;
  const C = 2 * Math.PI * r;
  const cx = size / 2, cy = size / 2;
  let acc = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1a212c" strokeWidth={thickness}/>
      {data.map((d, i) => {
        const frac = d.value / total;
        const dash = `${C * frac} ${C - C * frac}`;
        const offset = -C * acc;
        acc += frac;
        return <circle key={i} cx={cx} cy={cy} r={r} fill="none"
          stroke={d.color} strokeWidth={thickness} strokeDasharray={dash}
          strokeDashoffset={offset} transform={`rotate(-90 ${cx} ${cy})`}
          strokeLinecap="butt"/>;
      })}
    </svg>
  );
}

// === Heat strip (round perf) ===
function HeatStrip({ data, w = 600, h = 60, getValue = d => d.roi, getLabel = d => d.r,
  vMin = -10, vMax = 10 }) {
  const pad = { l: 0, r: 0, t: 10, b: 18 };
  const innerW = w - pad.l - pad.r;
  const cellW = innerW / data.length;
  const colorFor = v => {
    if (v >= 0) {
      const t = Math.min(1, v / vMax);
      return `rgba(94, 240, 183, ${0.18 + t * 0.7})`;
    } else {
      const t = Math.min(1, Math.abs(v) / Math.abs(vMin));
      return `rgba(255, 107, 129, ${0.18 + t * 0.7})`;
    }
  };
  return (
    <svg className="chart-svg" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      {data.map((d, i) => (
        <g key={i}>
          <rect x={pad.l + i * cellW + 1} y={pad.t} width={cellW - 2} height={h - pad.t - pad.b}
            fill={colorFor(getValue(d))} rx="2"/>
          <text x={pad.l + i * cellW + cellW/2} y={h - 4}
            fill="#5d6678" fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">
            {getLabel(d)}
          </text>
        </g>
      ))}
    </svg>
  );
}

window.AFLCharts = { Sparkline, LineChart, BarChart, CalibrationChart, Histogram, Scatter, Donut, HeatStrip, CHART_COLORS };
