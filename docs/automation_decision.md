# Automation Decision Note

**Purpose:** Evaluate whether and when additional automation layers should be added to
the AFL Predict system.

**Governing principle:** Automation should only be added if it demonstrably improves
reliability or operator efficiency after the core system has proven stable. Automation
added before the core is stable increases the surface area of things that can break
silently.

---

## 1. What automation already exists

Before evaluating additions, be precise about what is already running:

| Layer | What it does | Status |
|-------|-------------|--------|
| **Cron: daily pipeline** | Runs `orchestration.daily_pipeline` at 08:00 AEST | In place (`ops/crontab_server.txt`) |
| **Cron: weekly retraining** | Runs `train_models` every Sunday 02:00 AEST | In place |
| **Cron: weekly backtest** | Runs `run_backtest` every Monday 03:00 AEST | In place |
| **Log rotation** | Deletes log files older than 30 days | In place |
| **FastAPI server** | Serves read-only dashboard and recommendation endpoints | In place |
| **Pipeline state tracking** | Every job result written to DB with retry logic | In place |
| **Data freshness check** | Pre-flight soft check before every pipeline run | In place |
| **Daily summary artifact** | JSON written to `storage/daily_summaries/` each day | In place |

The core daily loop is already fully automated. A human operator is only needed for:
- Morning review (~10 minutes)
- Exception handling when the pipeline fails
- Weekly review (~30–45 minutes)

This is a reasonable baseline for a paper trading research system.

---

## 2. Candidate additions

### 2a. Telegram alerts

**What it would do:** Send a push notification to the operator's phone when:
- The daily pipeline completes (with status)
- A new recommendation is generated
- A pipeline job fails
- Drawdown exceeds a threshold

**How it would work:** A Telegram bot token + chat ID; a simple POST to
`https://api.telegram.org/bot{token}/sendMessage` from within the pipeline or a
wrapper script.

**Would it improve reliability?** No. The pipeline already runs and logs its outcome
to the DB and a log file. The daily summary artifact captures the same information.
Reliability is a function of the pipeline code and the cron schedule — not of whether
the operator is notified in real-time.

**Would it improve operator efficiency?**  
During paper trading: marginally. The operator already reviews the morning artifact
as part of the daily routine. A phone notification that the pipeline finished does not
eliminate that review — it only means the review can start 5 minutes earlier.

**Risk if added prematurely:** Notification fatigue. If the system sends a message
every day (pipeline success, new recommendation, no-bet day), the operator begins
ignoring messages within a week. A missed failure notification in that state is worse
than no notifications at all.

**Conclusion:** Do not add now.  
**Condition to reconsider:** After 4+ weeks of stable paper trading, if the operator
finds the morning review routine genuinely difficult to maintain (e.g., frequently
forgetting to check the artifact), a single daily digest message — one message per day,
sent at pipeline completion, containing only status + recommendation count + drawdown —
is the right form. Not per-event alerts.

---

### 2b. OpenClaw

**What it is:** OpenClaw is a sports betting edge tool primarily used for finding
positive-EV opportunities, comparing odds across bookmakers, and tracking CLV
(closing line value). It is typically used to monitor live odds movement and alert
when value appears.

**Relevance to this system:** The AFL Predict system already computes its own edge
estimates from The Odds API odds. It does not currently track closing-line movement
(see `docs/archive/differentiation_plan.md` Priority 3). OpenClaw could potentially serve
as an odds movement data source or a CLV validation tool.

**Would it improve reliability?** No. It addresses a different problem — live odds
monitoring — rather than improving pipeline stability.

**Would it improve operator efficiency?**  
Possibly, after the core system is stable and CLV tracking is a real workflow need.
OpenClaw adds value when an operator is actively comparing live odds across bookmakers
and validating that recommendations are moving in the right direction. During paper
trading with a single bookmaker reference (TAB via The Odds API), it adds no value.

**Risk if added prematurely:** It introduces an external dependency for a workflow
that does not yet exist. The system currently collects one odds snapshot per day.
Building a CLV workflow requires first implementing multi-snapshot collection
(differentiation plan Priority 3) and confirming TAB is the correct reference
bookmaker. OpenClaw cannot do this work for us.

**Conclusion:** Do not add now.  
**Condition to reconsider:** After multi-snapshot odds collection is implemented
(differentiation plan Priority 3), and after at least 60 settled paper bets exist,
evaluate whether OpenClaw's CLV tracking is more useful than the system's own
snapshot comparison. If so, evaluate the integration cost and reliability implications
at that time. Do not integrate it as a data dependency for core recommendations.

---

### 2c. Server-side orchestration (systemd, Supervisor, Docker)

**What it would do:** Manage the API server process as a persistent service:
- Auto-restart the API server on crash
- Auto-start on machine reboot
- Log service health separately from pipeline logs
- Potentially containerise the full stack with Docker

**Current state:** The API server runs as a background process (`uvicorn ... &`).
There is a `ops/systemd/afl-predict-collector.service` file (referenced in the
memory notes for Phase 7) for the collector API. The full server service configuration
may or may not be in place depending on machine setup.

**Would it improve reliability?**  
Yes, specifically for the API server process. If the server machine reboots or the
uvicorn process crashes, the API becomes unavailable until manually restarted. Systemd
supervision eliminates this failure mode.

This is the one candidate that directly addresses a real reliability gap.

**Would it improve operator efficiency?**  
Marginally — one fewer thing to check on Monday morning after a weekend. The operator
does not currently rely on the API for the core daily check (the JSON artifact is
sufficient), so the impact is low.

**Risk if added:** Low — systemd is a standard, well-understood mechanism. A
misconfigured unit file is easy to identify and fix. The risk is not high enough to
block it, only to defer it until the pipeline is confirmed stable.

**Conclusion:** Add this after 2 weeks of stable paper trading.  
**Specific form:** A systemd unit file for the API server process, similar to the
existing `ops/systemd/afl-predict-collector.service`. Do not containerise the full
stack with Docker yet — the overhead of maintaining container configuration is not
justified by the current operational complexity.

---

### 2d. Scheduled remote agents / external orchestration

**What it would mean:** Replacing the cron schedule with an external orchestration
system (Airflow, Prefect, cloud scheduler, etc.) or running the pipeline on a
cloud server rather than a local machine.

**Would it improve reliability?** Depends on current machine reliability. If the
server machine is a personal desktop that is sometimes offline, cloud-based
scheduling would be more reliable. If the machine is always on, local cron is simpler
and has fewer failure modes.

**Would it improve operator efficiency?** No. The operator interaction is in the
review and exception handling, not in the scheduling mechanism.

**Risk if added:** High complexity for uncertain benefit. Cloud deployment introduces
credentials, billing, network latency for DB access, and log aggregation concerns.
None of these are justified during paper trading.

**Conclusion:** Do not add now. Re-evaluate only if the server machine proves
unreliable (3+ cron failures in a 4-week period).

---

## 3. Summary decision table

| Candidate | Add now? | Condition to add | Form |
|-----------|---------|-----------------|------|
| Telegram alerts | No | After 4+ weeks, if review routine is hard to maintain | Single daily digest only |
| OpenClaw | No | After multi-snapshot odds + 60+ settled bets | As CLV validation tool, not data dependency |
| Systemd for API server | After 2 stable weeks | Pipeline confirmed reliable | Unit file only, not Docker |
| External orchestration | No | Only if server proves unreliable | Local cron is sufficient |

---

## 4. What would actually improve reliability right now

The most impactful reliability improvement available today is not a new automation
layer — it is resolving the two critical TODOs in `generate_recommendations.py`
(model selection and loading). Until those are fixed, the pipeline runs reliably
but produces recommendations from the wrong model. That is a correctness failure,
not a reliability failure, but it is more damaging to the paper trading record than
any amount of process automation.

In order of actual impact on system reliability and operator confidence:

1. **Resolve the critical TODOs** — model selection and loading
2. **Confirm The Odds API TAB bookmaker availability** — verify the right bookmaker
   is being used as the reference for edge calculation
3. **Systemd for API server** — after 2 stable weeks of paper trading
4. **Single daily Telegram digest** — after 4 stable weeks, if the review routine
   is genuinely difficult to maintain
5. **Everything else** — after evidence from paper trading shows what is actually
   needed

---

## 5. Automation anti-patterns to avoid

These would add the appearance of sophistication without improving outcomes:

- **Automated bet placement** — will not be built. This is a research system.
  `PAPER_TRADE_ONLY=True` is a hard constraint, not a toggle.
- **Real-time odds monitoring** — adds complexity before the batch pipeline is
  validated. The system's edge is computed from daily snapshots; real-time
  monitoring is a different product.
- **Multi-channel notifications** (Telegram + email + Slack) — notification
  sprawl increases the chance of important messages being ignored.
- **Automated threshold tuning** — parameter changes require human review and
  backtest evidence. Automating this removes the discipline that makes the paper
  trading record trustworthy.
- **Auto-retraining on pipeline failure** — retraining should be deliberate, not
  a recovery mechanism.
