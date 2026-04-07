.PHONY: help install serve pipeline pipeline-cron test test-fast lint format migrate db-init build-features backtest train-models freshness-check daily-summary readiness today-summary notify clv fetch-weather fetch-player-stats

help:
	@echo ""
	@echo "AFL Predict — available commands"
	@echo "---------------------------------"
	@echo "  install          Install Python dependencies"
	@echo "  serve            Start FastAPI development server"
	@echo "  pipeline         Run the full daily pipeline manually"
	@echo "  ingest-afl       Fetch AFL fixtures/results (--season --round)"
	@echo "  ingest-odds      Fetch TAB/AU H2H odds snapshots (--dry-run)"
	@echo "  build-features   Build pre-match feature matrix (--season --no-db)"
	@echo "  backtest         Run walk-forward backtest (--mode --min-train-seasons)"
	@echo "  train-models     Train baseline models on temporal split"
	@echo "  test             Run test suite"
	@echo "  test-fast        Run tests excluding slow integration tests"
	@echo "  lint             Run ruff linter"
	@echo "  format           Auto-format with ruff"
	@echo "  migrate          Run Alembic database migrations"
	@echo "  db-init          Create all tables (local dev / first run)"
	@echo "  pipeline-cron    Run pipeline (marks triggered_by=cron)"
	@echo "  freshness-check  Check odds/fixture data freshness"
	@echo "  daily-summary    Write today's summary artifact to storage/"
	@echo "  readiness        Run live-readiness evaluation report"
	@echo "  today-summary    Pretty-print today's daily summary artifact"
	@echo ""

install:
	pip install -r requirements-dev.txt

serve:
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

pipeline:
	python -m orchestration.daily_pipeline --triggered-by manual

pipeline-cron:
	python -m orchestration.daily_pipeline --triggered-by cron

freshness-check:
	python -m orchestration.jobs.check_data_freshness

daily-summary:
	python -m orchestration.jobs.generate_daily_summary

readiness:
	python -m evaluation.live_readiness

today-summary:
	@python -c "import json, pathlib, datetime; p=pathlib.Path('storage/daily_summaries')/f\"{datetime.date.today()}.json\"; print(json.dumps(json.loads(p.read_text()), indent=2) if p.exists() else 'No summary found for today. Run: make daily-summary')"

ingest-afl:
	python -m orchestration.jobs.ingest_afl $(ARGS)

ingest-odds:
	python -m orchestration.jobs.ingest_tab_odds $(ARGS)

build-features:
	python -m orchestration.jobs.build_features $(ARGS)

backtest:
	python -m orchestration.jobs.run_backtest $(ARGS)

train-models:
	python -m orchestration.jobs.train_models $(ARGS)

test:
	pytest tests/ -v

test-fast:
	pytest tests/ -v -m "not slow"

lint:
	ruff check .

format:
	ruff format .

migrate:
	alembic upgrade head

db-init:
	python -c "from db.session import create_all_tables; create_all_tables(); print('Tables created.')"

notify:
	python -m orchestration.jobs.notify_bets

fetch-weather:
	python -m orchestration.jobs.fetch_weather $(ARGS)

fetch-player-stats:
	python -m orchestration.jobs.fetch_player_stats $(ARGS)

clv:
	python -c "from db.session import SessionLocal; from evaluation.clv_tracker import batch_clv, clv_summary, format_ci; db=SessionLocal(); r=batch_clv(db); print(clv_summary(r)); db.close()"
