# T6 Merge Readiness — Closeout

Updated: 2026-08-25 (verification closeout pass)
Original checklist: 2026-04-18 (Australia/Sydney)

## Verdict

**CLOSED — the working tree is committed, clean, and verified at the code level.**
The 2026-04-18 concerns (dirty worktree mixing source, docs, and generated
artifacts; nested repo pointer) no longer describe the repository: all work is
committed on `main`, the tree is clean, and no nested gitlink exists
(`git ls-files -s | grep 160000` returns nothing).

What remains open is **not a code blocker but an evidence limitation**:
historical model-performance numbers cannot be reproduced from this repository
alone (no bundled dataset, database, or backtest-result artifacts), so the
docs must not — and now do not — claim verified predictive performance. See
"Not verifiable locally" below.

## Original "Verification still required" — item-by-item result

| Item | Status | Evidence (2026-08-25, Python 3.11.9, Windows) |
|---|---|---|
| Route smoke test for new API endpoints | **Verified** | TestClient-based suites pass: `test_health.py`, `test_dashboard_contract.py`, `test_quant_dashboard_static.py` (part of the 313-passing run below) |
| Migration application on a clean database | **Verified** | `tests/test_alembic_fresh_db.py` passes; additionally `alembic upgrade head` (0000→0008) ran clean against a throwaway SQLite DB |
| `train_models` rerun on final feature set | **Not verifiable locally** | Requires ingested historical data (external APIs); no dataset is bundled. Docs no longer rest any claim on a prior training run |
| `run_backtest` / evaluation rerun | **Not verifiable locally** | Same data dependency; `storage/backtest_results/` contains no artifacts. Performance tables in `ACCURACY_PLAN.md` are now explicitly caveated as unreproduced historical snapshots |
| `make readiness` on the final tree | **Verified (smoke)** | `python -m evaluation.live_readiness` runs end-to-end against a fresh DB and correctly reports `not_ready` (insufficient samples, TAB bookmaker unconfirmed) — the expected result with no betting history |
| `.env.example` matches dual-machine model | **Verified** | `NODE_ROLE` present with `standalone`/`collector`/`predictor` semantics documented in `config/settings.py` and `CLAUDE.md` |

## Full validation baseline (2026-08-25)

- `pytest tests/` — **313 passed, 1 skipped** (skip is by design: no static
  critical TODOs are currently defined), 1 deprecation warning (Pydantic
  class-based config in `api/routes/fixtures.py`).
  - One test defect was found and fixed during this pass:
    `test_pass_when_todos_empty` failed whenever
    `TAB_BOOKMAKER_CONFIRMED=false` (the default) because it did not control
    the runtime TODO appended by `_check_critical_todos`.
- `ruff check .` — 202 findings (style/modernization: `datetime.UTC` aliases,
  unused imports, import order, line length). Not CI-gated (no CI is
  configured), none identified as correctness defects. Known style debt.
- No type-check gate is configured to run in CI; `mypy` config exists in
  `pyproject.toml` (non-strict).

## Issues found and fixed in this pass

1. Readiness test/env coupling (above).
2. Ensemble weight double definition: `config/settings.py` declared
   bookmaker/elo/xgboost/poisson weights that only fed the dashboard display,
   while the production ensemble used a different hardcoded dict in
   `generate_recommendations.py`. The dashboard therefore displayed weights
   (including a bookmaker component) that the ensemble did not use. Weights
   are now single-sourced from settings.
3. Accidental artifacts removed from version control: `=0.14`, `=0.44`,
   `=2.0` (pip output captured by unquoted `>=` specifiers in PowerShell) and
   a root `settings.json` (local tool permissions file).

Found by the independent (Codex) review of this pass and fixed:

4. CLV sign inversion: `settle_results._compute_clv` persisted
   `(1/bet_odds) − (1/closing_odds)` — the opposite of the documented
   convention in `evaluation/clv_tracker.py` (positive = beat the close) —
   so per-bet CLV shown by the dashboard/Discord history had inverted sign.
   Now aligned with the canonical convention. (Aggregate CLV summaries were
   unaffected — they recompute via `clv_tracker`.)
5. Weather look-ahead disclosure: historical `weather_*` features come from
   Open-Meteo *archive* observations at kickoff, not pre-match forecasts —
   post-bet-time information. Documented in `docs/backtesting.md` ("Known
   deviation"), the extractor docstring, README, and PORTFOLIO_FACTS; the
   code path itself is unchanged (fixing it needs forecast-issued-at
   snapshots and is future work).
6. Doc-accuracy corrections: `ACCURACY_PLAN.md` marked as a historical
   planning document (its "missing" items have since been implemented), and
   README/PORTFOLIO_FACTS wording corrected so the backtest is described as
   evaluating individual models (the calibrated ensemble used in production
   is not yet covered by the backtest runner).
7. Added a contract test for `/api/dashboard/backtest-summary` ensemble
   weights (previously uncovered).

## Generated artifacts policy (unchanged)

`logs/**`, `reviews/**`, `storage/daily_summaries/**`, and
`storage/model_artifacts/*.json` are operational/review evidence, kept
deliberately. They are historical records and should not be edited to
"improve" results.

## Not verifiable locally — standing limitations

- **No performance claim in this repository is independently reproducible from
  the repository contents alone.** Regenerating metrics requires re-ingesting
  data from external APIs (Squiggle, The Odds API, Open-Meteo, AFL Tables).
- The bookmaker-baseline figures recorded in `ACCURACY_PLAN.md` were computed
  when odds coverage in training data was ~0%, so they are not a valid market
  comparison; the repository makes **no claim of beating bookmaker prices**.
- The paper-trading log (`storage/paper_trading_log.md`) contains no entries:
  there are **zero recorded paper-trading results**.
- The live-readiness gate correctly evaluates to `not_ready`.
