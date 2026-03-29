# Machine Workflow Guide

How to operate the AFL Predict system across three machines.

---

## Machine roles

| Machine | Role | Runs |
|---------|------|------|
| **Server computer** | Scheduled jobs, persistent API | Cron pipeline, API server |
| **Main computer** | Review, analysis, manual oversight | Dashboard, manual reruns, backtest inspection |
| **MacBook** | Monitoring, remote operation | Read-only dashboard, SSH access to server |

---

## Server computer setup

### First-time setup

```bash
# 1. Clone repo and install dependencies
git clone <repo> /opt/afl_predict
cd /opt/afl_predict
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Create .env from template
cp .env.example .env
# Edit .env: set DB_URL, ODDS_API_KEY, SQUIGGLE_USER_AGENT

# 3. Initialise database
make db-init
# Or: alembic upgrade head

# 4. Install cron schedule
crontab ops/crontab_server.txt
crontab -l   # verify

# 5. Create log directory
mkdir -p logs

# 6. Start API server (background, auto-restart on reboot via systemd/screen)
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
```

### Daily cron (automatic at 08:00 AEST)

No action needed. Check `logs/pipeline.log` for errors.

```bash
tail -50 logs/pipeline.log
```

### Manual pipeline re-run

```bash
cd /opt/afl_predict
source .venv/bin/activate
python -m orchestration.daily_pipeline --triggered-by manual
```

### Check pipeline status from server

```bash
sqlite3 afl_predict.db \
  "SELECT run_date, status, duration_seconds
   FROM daily_pipeline_runs
   ORDER BY id DESC LIMIT 7;"
```

---

## Main computer setup

The main computer queries the API served by the server computer.
It does NOT need a local DB (read-only via API).

```bash
# 1. Install only what's needed for local analysis
pip install requests pandas matplotlib

# 2. Set API base URL (point at server)
export AFL_API=http://<server-ip>:8000
```

### Morning review workflow

```bash
# Pipeline status
curl $AFL_API/dashboard/summary | python -m json.tool

# Recommendations for today
curl "$AFL_API/dashboard/recommendations?limit=10" | python -m json.tool

# Bankroll trend (last 60 days)
curl "$AFL_API/dashboard/bankroll?days=60" | python -m json.tool

# Data freshness
curl $AFL_API/dashboard/freshness | python -m json.tool
```

Or open `http://<server-ip>:8000/docs` in a browser for interactive API.

### Analysis and backtest review

```bash
# Re-run backtest locally (requires DB access — either shared DB or local copy)
make backtest

# Check live-readiness report
curl $AFL_API/dashboard/readiness | python -m json.tool
```

### Triggering a manual pipeline run on the server

SSH to the server and run:

```bash
ssh user@server
cd /opt/afl_predict && source .venv/bin/activate
python -m orchestration.daily_pipeline --triggered-by manual
```

Or if you have a local .env pointing at the server's DB (not recommended for production):

```bash
python -m orchestration.daily_pipeline --triggered-by manual
```

---

## MacBook setup (monitoring and remote ops)

The MacBook is for read-only monitoring and SSH access.

### Quick status check (from anywhere)

```bash
# Requires: server API accessible on network / VPN
export AFL_API=http://<server-ip>:8000

# Daily summary
curl $AFL_API/dashboard/summary | python -m json.tool | head -60

# Pipeline health
curl "$AFL_API/dashboard/pipeline?days=3" | python -m json.tool
```

### SSH remote pipeline re-run

```bash
ssh user@server 'cd /opt/afl_predict && source .venv/bin/activate && python -m orchestration.daily_pipeline --triggered-by manual'
```

### Remote log tailing

```bash
ssh user@server 'tail -f /opt/afl_predict/logs/pipeline.log'
```

### MacBook local dev (if needed)

If you want to run the full stack locally on the MacBook (for development or testing):

```bash
cp .env.example .env
# Edit .env with your settings
make db-init
make pipeline          # run full pipeline once
make serve             # start API on localhost:8000
```

---

## Shared storage considerations

If the server database file (SQLite) is on a network share or Dropbox:
- Be aware of concurrent write risks — only one machine should run the pipeline at a time.
- Consider using PostgreSQL for multi-machine access (change `DB_URL` in `.env`).
- The daily summary artifact (`storage/daily_summaries/*.json`) is safe to share read-only.

---

## Environment variables per machine

Create a `.env` on each machine. Key fields:

```
# Server computer (.env)
DB_URL=sqlite:///./afl_predict.db       # or postgresql://...
ODDS_API_KEY=your_real_key
APP_ENV=production
APP_DEBUG=False
PAPER_TRADE_ONLY=True
DAILY_SUMMARY_DIR=./storage/daily_summaries

# Main computer (.env)
DB_URL=sqlite:////path/to/shared/afl_predict.db   # or API-only
APP_ENV=development
APP_DEBUG=True

# MacBook (.env — optional, for local dev only)
DB_URL=sqlite:///./afl_predict_dev.db
ODDS_API_KEY=your_real_key
APP_ENV=development
```
