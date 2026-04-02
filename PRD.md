# PRD — AFL Market Intelligence and Value Betting Research System (TAB-focused)

## 1. Product Summary
This project is a research-oriented AFL market intelligence and value betting decision-support system focused on identifying potential pre-match value opportunities in TAB head-to-head markets.

The system will:
- collect AFL match, team, and contextual data,
- collect TAB odds snapshots for target markets,
- estimate match win probabilities,
- compare model-implied probabilities against bookmaker-implied probabilities,
- generate paper-trade recommendations,
- explain why each recommendation was selected,
- and track long-term performance, reliability, and risk.

The system will begin in paper-trading mode only. It will remain in paper trading until it passes a formal review gate based on sample size, data integrity, calibration quality, drawdown control, and closing line value, rather than short-term win rate alone.

---

## 2. Product Vision
Build a disciplined, data-driven AFL research pipeline that prioritizes:
- reproducibility,
- conservative risk management,
- evaluation quality,
- explainability,
- and operational reliability.

This is not intended to be an aggressive auto-betting bot. It is a controlled ML research and decision-support system designed to test whether small, repeatable edges exist in AFL pre-match betting markets under realistic assumptions.

---

## 3. Problem
Manual betting decisions are often noisy, emotional, inconsistent, and difficult to evaluate rigorously. AFL prices can move due to injuries, team selection changes, venue effects, form narratives, and market sentiment. It is difficult to determine whether a bet is genuinely valuable or simply popular.

The user wants a system that can:
- gather relevant AFL and TAB data daily,
- estimate true probabilities more consistently than naive intuition,
- identify value opportunities,
- simulate decisions safely before risking money,
- and later support a tightly restricted, manually reviewed live micro-trial if justified.

---

## 4. Goals

### Primary Goals
- Build an end-to-end AFL betting research pipeline.
- Predict pre-match head-to-head match winner probabilities.
- Identify value opportunities using model edge versus TAB implied probability.
- Run daily paper trading automatically.
- Track ROI, calibration, drawdown, and recommendation quality over time.
- Generate clear daily recommendations for manual review.

### Secondary Goals
- Use Claude CLI for implementation, ETL, scraping, orchestration, and coding.
- Use Codex for planning, architecture review, experiment review, and QA.
- Use a 3-machine setup for distributed development and operations.
- Keep the system extensible to future sports or betting markets.

---

## 5. Non-Goals
- No martingale or progressive stake systems.
- No in-play or live betting in MVP.
- No fully autonomous real-money execution in MVP.
- No assumption that backtest profit guarantees live profit.
- No commercial redistribution of TAB data or odds.
- No player props, multis, or exotic bet types in MVP.
- No weak speculative features such as sponsor relationships or club financial condition unless later evidence shows clear predictive value.

---

## 6. User
Primary user: a single operator/researcher running the system personally.

User needs:
- daily AFL value recommendations,
- clear explanation of why a recommendation was selected,
- visibility into model confidence and edge,
- visibility into odds freshness and data quality,
- performance tracking over time,
- strict risk controls,
- and a quick disable switch for any future live mode.

---

## 7. Scope

### In Scope (MVP)
- AFL only
- pre-match only
- head-to-head winner market only
- daily odds snapshot collection
- paper trading recommendations
- model training and backtesting
- basic reports and analytical dashboard
- bankroll simulation and drawdown tracking
- recommendation explanations
- data quality checks

### Out of Scope (MVP)
- racing
- multis/parlays
- in-play betting
- player prop betting
- automated real-money bet submission
- mobile app as a first-class product
- commercial hosting for external users
- social/community features
- speculative business-level signals without demonstrated value

---

## 8. Research Hypothesis
A conservative AFL pre-match model that combines historical team performance, bookmaker pricing, line movement, venue effects, and structured injury/team-availability signals may identify a small subset of matches where the estimated true win probability is sufficiently above bookmaker-implied probability to justify paper-trade inclusion.

---

## 9. Success Criteria

### Primary Evaluation Criteria
- Positive or near-break-even paper-trading ROI over a meaningful sample period
- Positive average closing line value (CLV)
- Acceptable probability calibration
- Stable recommendation quality across multiple rounds, not just short-term hot streaks
- Reliable daily pipeline completion and recommendation generation

### Secondary Evaluation Criteria
- Hit rate
- Average model edge
- Recommendation frequency
- Odds freshness and snapshot completeness
- Reproducibility of experiment runs
- Consistency versus bookmaker-implied baseline

### Risk Metrics
- Max drawdown
- Weekly paper-trade loss
- Bet frequency per day
- Exposure concentration
- Live stop-loss trigger count (future live phase only)

---

## 10. Paper Trading Review Gate
The system will not enter any live micro-trial unless paper trading demonstrates:
- a minimum evaluation window of at least 8-12 weeks,
- sufficient sample size,
- stable recommendation logic,
- acceptable calibration,
- controlled drawdown,
- evidence of positive or at least non-random CLV,
- and no unresolved integrity issues in data ingestion or recommendation generation.

Short-term win rate alone is not sufficient to justify live deployment.

---

## 11. Product Phases

### Phase 1 — Setup and Historical Pipeline
- data ingestion
- storage
- feature pipeline
- baseline models
- backtest evaluation
- reproducible artifacts and logs

### Phase 2 — Daily Paper Trading
- daily odds snapshot collection
- recommendation engine
- bankroll simulation
- daily reports
- analytical dashboard
- reliability monitoring

### Phase 3 — Restricted Live Trial
Starts only if Phase 2 passes the formal paper-trading review gate.

Rules:
- AUD 5 maximum total per day
- fixed stake only
- maximum 1-3 bets per day
- no chasing losses
- immediate stop on integrity failure or excessive drawdown
- manual confirmation required in early live mode
- live mode disabled by default

---

## 12. Data Sources

### Data Categories

#### Core Match Data
- fixtures
- final results
- score margins
- venue
- home/away
- round and season identifiers

#### Core Market Data
- pre-match head-to-head odds snapshots
- bookmaker name
- snapshot timestamps
- opening odds where available
- latest odds before recommendation cutoff
- closing odds where obtainable

#### Contextual Signals
- injury reports
- team selection availability
- late changes
- recent form summaries

#### Deferred / Future Signals
- player-level derived aggregates
- structured news sentiment
- player props
- richer market movement features

### Collection Priority
1. official API or official approved web service
2. official AFL and public match/result sources
3. carefully rate-limited scraping if necessary and compliant
4. local snapshot storage for reproducibility

---

## 13. Modeling Approach

### Target
Predict the probability of Team A winning the match.

### Candidate Feature Groups

#### Team Strength Features
- rolling ELO
- recent point differential
- offense and defense form windows
- season-to-date strength indicators

#### Match Context Features
- venue effect
- home/away
- travel burden
- rest days
- bye-related context where relevant

#### Market Features
- bookmaker implied probability
- opening-to-latest odds movement
- market disagreement indicators
- line movement magnitude and direction

#### Availability Features
- confirmed injuries
- late outs / team selection changes
- player-level aggregate availability score

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
- data quality checks pass,
- and no exclusion rule is triggered.

---

## 14. Recommendation Output
For each recommended match, the system should output:
- match identifier
- home team and away team
- market odds
- bookmaker implied probability
- model probability
- estimated edge
- recommendation tier
- confidence band
- key explanatory signals
- timestamp of odds capture
- data quality status

### Recommendation Categories
- **Strong Edge**
- **Watchlist**
- **No Bet**

The system should prefer high-quality, selective recommendations over forced daily volume.

---

## 15. Risk and Responsible Gambling Controls
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
- automatic no-bet if model integrity checks fail
- manual review in early live phase

---

## 16. Compliance Constraints
- Use is personal and non-commercial unless explicit permissions change.
- Prefer approved TAB API or approved web service access.
- Do not redistribute TAB data.
- Do not assume all displayed odds are executable at intended size or time.
- Log the timestamp and source of every odds snapshot.
- Keep raw and processed data separated for auditability and reproducibility.

---

## 17. Architecture

### Server Computer
Responsibilities:
- scheduler
- ingestion jobs
- database
- raw snapshot storage
- cleaned dataset generation
- daily report generation
- orchestration controller
- model retraining jobs
- log persistence

### Main Computer
Responsibilities:
- active development
- notebooks
- model experiments
- dashboard review
- manual oversight
- data QA
- feature and model iteration

### MacBook
Responsibilities:
- monitoring
- remote review
- light edits
- report inspection
- Codex-driven planning and review

---

## 18. Agent Workflow

### Claude CLI
- code implementation
- scraping
- ETL
- feature engineering
- training scripts
- reports and dashboards
- infrastructure scripts
- orchestration workers

### Codex
- planning
- repo structure design
- architecture review
- experiment QA
- evaluation sanity checks
- code review
- PRD compliance verification

---

## 19. Storage and Reproducibility
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
- evaluation summaries
- dashboard-ready aggregates

Every experiment or daily run should be reproducible from stored inputs, configs, and generated artifacts.

---

## 20. Dashboard Scope (MVP+)
The dashboard should provide:
- daily recommendations
- historical paper-trade log
- ROI over time
- drawdown chart
- CLV tracking
- model calibration view
- edge distribution
- recommendation breakdown by tier
- data freshness / pipeline status
- recommendation explanation summaries

The dashboard is analytical, not decorative. Its purpose is to support review, diagnosis, and disciplined decision-making.

---

## 21. MVP Definition
The MVP is complete when the system can:
- ingest upcoming AFL matches,
- ingest TAB head-to-head odds snapshots,
- build a feature table,
- run at least one baseline model,
- output daily paper-trade recommendations,
- explain why a recommendation was generated,
- evaluate outcomes,
- and display performance through a simple analytical dashboard or report.

---

## 22. Explicit Exclusions (Early Phases)
The following are excluded unless later evidence shows predictive value:
- sponsor relationships
- club financial condition
- vague social sentiment without structured extraction
- speculative narrative features without reproducible capture
- overly complex player-level modeling before core team-level baselines are stable

---

## 23. Open Questions
- Which approved TAB access path will be used in practice?
- What exact daily cutoff time should be used for odds capture?
- Which additional AFL data source is most stable for lineup and injury context?
- What minimum sample size is required before live testing?
- What edge threshold should trigger a recommendation tier?
- How should CLV be measured when exact closing odds are unavailable?
- Which dashboard views are essential for MVP versus later phases?