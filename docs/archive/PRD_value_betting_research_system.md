# PRD — AFL Value Betting Research System (TAB-focused)

## 1. Product Summary
This project is a research-oriented AFL betting intelligence system focused on identifying potential value bets in TAB pre-match sports markets.

The system will:
- collect AFL match and team data,
- collect TAB odds snapshots for target markets,
- estimate win probabilities,
- compare model-implied probabilities against bookmaker-implied probabilities,
- generate paper-trade recommendations,
- track long-term performance and risk.

The project starts in paper trading mode for approximately one month. If the system shows stable and acceptable performance under realistic assumptions, it may move into a tightly restricted live trial with a fixed daily betting budget of AUD 5.

## 2. Product Vision
Build a disciplined, data-driven AFL betting research pipeline that prioritizes:
- reproducibility,
- conservative risk management,
- evaluation quality,
- and operational reliability.

This is not intended to be an aggressive auto-betting bot. It is a controlled ML research system for testing whether small, repeatable edges exist in AFL pre-match betting markets.

## 3. Problem
Manual betting decisions are noisy, emotional, and inconsistent. AFL prices can move quickly with injuries, form narratives, and public sentiment. It is difficult to determine whether a bet is genuinely valuable or simply popular.

The user wants a system that can:
- gather relevant AFL and TAB data daily,
- estimate true probabilities better than naive intuition,
- identify value opportunities,
- simulate decisions safely before risking money,
- and later support very small real-money experimentation.

## 4. Goals
### Primary Goals
- Build an end-to-end AFL betting research pipeline.
- Predict head-to-head match winner probabilities before match start.
- Identify value bets using model edge versus TAB implied probability.
- Run daily paper trading automatically.
- Track return, calibration, drawdown, and execution quality.

### Secondary Goals
- Use Claude CLI for implementation, scraping, ETL, orchestration, and coding.
- Use Codex for planning, architecture review, experiment review, and QA.
- Use a 3-machine setup for distributed development and operations.
- Make the system extensible to future sports or markets.

## 5. Non-Goals
- No martingale or progressive stake systems.
- No in-play or live betting in MVP.
- No fully autonomous real-money execution in MVP.
- No assumption that backtest profit guarantees live profit.
- No commercial redistribution of TAB data or odds.

## 6. User
Primary user: a single operator/researcher running the system personally.

User needs:
- daily AFL bet recommendations,
- clear explanation of why a bet was selected,
- visibility into model confidence and edge,
- performance tracking over time,
- hard risk controls,
- quick disable switch for live mode.

## 7. Scope
### In Scope (MVP)
- AFL only
- pre-match only
- head-to-head winner market only
- daily odds snapshot collection
- paper trading recommendations
- model training and backtesting
- dashboard and reports
- bankroll and drawdown tracking

### Out of Scope (MVP)
- racing
- multis/parlays
- in-play betting
- player prop betting
- automated real-money bet submission
- mobile app as a first-class product
- commercial hosting for external users

## 8. Research Hypothesis
A conservative AFL model using historical results, team strength, venue effects, and current bookmaker pricing may identify a small subset of matches where the model’s estimated win probability exceeds the bookmaker-implied probability by enough to justify paper-trade inclusion.

## 9. Success Criteria
### Modeling Metrics
- Brier score
- log loss
- calibration quality
- ROI in paper trading
- hit rate
- average edge of selected bets
- performance versus baseline bookmaker-implied selection

### Operational Metrics
- successful daily pipeline completion
- data freshness before recommendation cutoff
- complete odds snapshot coverage for target matches
- reproducible experiment runs

### Risk Metrics
- max drawdown
- weekly paper-trade loss
- bet frequency per day
- exposure concentration
- live stop-loss trigger count

## 10. Product Phases
### Phase 1 — Setup and Historical Pipeline
- data ingestion
- storage
- feature pipeline
- baseline models
- backtest evaluation

### Phase 2 — Daily Paper Trading
- daily odds snapshot collection
- recommendation engine
- bankroll simulation
- reports and dashboard

### Phase 3 — Restricted Live Trial
Starts only if Phase 2 passes review criteria.

Rules:
- AUD 5 maximum total per day
- fixed stake only
- maximum 1–3 bets per day
- no chasing losses
- immediate stop on integrity failure or excessive drawdown
- manual confirmation required in early live mode

## 11. Data Sources
### AFL Data
- fixtures
- final results
- scores
- venue
- home/away
- recent form
- team-related status signals where available

### TAB Data
- pre-match odds snapshots
- target market availability
- market timestamp capture
- line movement if obtainable

Priority order for collection:
1. official API / official approved web service
2. official AFL/public sources
3. carefully rate-limited scraping if necessary and compliant
4. local snapshot storage for reproducibility

## 12. Modeling Approach
### Target
Predict probability of Team A winning the match.

### Candidate Features
- rolling team strength
- ELO ratings
- recent form windows
- points for / points against trends
- venue effect
- travel factor
- rest days
- opening vs latest odds delta if available
- bookmaker implied baseline

### Baselines
- bookmaker implied probability baseline
- ELO model
- logistic regression
- gradient boosting model

### Selection Rule
Recommend a bet only if:
- model edge exceeds threshold,
- confidence threshold is met,
- odds are fresh enough,
- risk budget is available,
- data quality checks pass.

## 13. Risk and Responsible Gambling Controls
Mandatory controls:
- paper trading first
- live mode disabled by default
- maximum daily live exposure = AUD 5
- maximum bets per day = configurable
- fixed stakes only
- weekly loss cap
- drawdown stop
- automatic no-bet if data collection fails
- automatic no-bet if odds freshness fails
- manual review in early live phase

## 14. Compliance Constraints
- Use is personal and non-commercial unless explicit permissions change.
- Prefer approved TAB API / web service access.
- Do not redistribute TAB data.
- Do not assume all displayed odds are executable at intended size or time.
- Log the timestamp and source of every odds snapshot.

## 15. Architecture
### Server Computer
Responsibilities:
- scheduler
- ingestion jobs
- database
- artifact storage
- daily report generation
- orchestration controller
- model retraining jobs

### Main Computer
Responsibilities:
- active development
- notebooks
- model experiments
- dashboard review
- manual oversight
- data QA

### MacBook
Responsibilities:
- monitoring
- remote review
- light edits
- report inspection
- Codex-driven planning/review

## 16. Agent Workflow
### Claude CLI
- code implementation
- scraping
- ETL
- feature engineering
- training scripts
- dashboards
- infra scripts
- orchestration workers

### Codex
- planning
- repo structure design
- architecture review
- experiment QA
- evaluation sanity checks
- code review
- PRD compliance verification

## 17. Storage and Reproducibility
Persist:
- raw odds snapshots
- raw AFL source snapshots
- cleaned tables
- feature tables
- train/test splits
- model artifacts
- recommendations
- bankroll simulation logs
- live trial logs
- configs for each run

## 18. MVP Definition
The MVP is complete when the system can:
- ingest upcoming AFL matches,
- ingest TAB head-to-head odds,
- build a feature table,
- run at least one baseline model,
- output daily paper-trade recommendations,
- evaluate outcomes,
- and show performance through a simple dashboard.

## 19. Open Questions
- Which approved TAB access path will be used in practice?
- What exact daily cutoff time should be used for odds capture?
- Which additional AFL data source is most stable for lineup/injury context?
- What minimum sample size is required before live testing?
- What paper-trading performance threshold is strong enough to justify a micro live trial?