# Documentation assets

## Screenshots

Both images were captured on 2026-08-21 from the static dashboard
(`static/quant-dashboard/`) served by `python serve.py`, after running
`make demo`. Capture command:

```bash
make demo
python serve.py --port 8123 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --window-size=1600,5200 --virtual-time-budget=12000 \
  --screenshot=out.png http://localhost:8123/
```

| File | Contents |
|---|---|
| `prediction-view.png` | Status banner plus the Recent predictions table. **Every row is real** — each comes from the `predictions.json` the demo wrote, with each pick's probability priced against its own side of the market. |
| `dashboard.png` | The full overview viewport, for layout context. **Read the caveat below before reusing it.** |

## Caveat: the dashboard mixes real and placeholder values

`static/quant-dashboard/` came from a design handoff and ships with a bundled
placeholder dataset so the layout paints before any data loads. The runtime
overlay replaces only what the payload actually provides:

**Real (overlaid from `predictions.json` / the `/dashboard/*` API):**
the predictions table, total predictions, win rate, Brier score, log loss, and
the status banner.

**Placeholder — from the design mock, not results:**
ROI, net P/L, bankroll and bankroll curve, CLV, cumulative profit, calibration
and diagnostics charts, segment and stake-strategy breakdowns, the row counts in
the sidebar, the table's "Showing 24 of 1,218 · Page 1/51" footer, and the user
persona in the sidebar corner.

`dashboard.png` therefore shows figures such as "ROI +7.81%" and
"Bankroll $14,218" that **the system has not achieved**. It is kept for layout
reference only and is deliberately **not** used as the hero image in the
top-level README. `prediction-view.png` is cropped to the regions the demo
payload genuinely populates, with the mock pagination footer excluded.

When the payload is a demo run (`"demo": true`), the banner reads
`SAMPLE DATA — demo run — remaining panels are placeholder values, not results`,
which is visible in both screenshots.

Verified performance numbers live in [`../results.md`](../results.md) — that is
the only place to read this system's actual results.
