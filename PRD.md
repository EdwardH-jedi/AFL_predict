# Product Requirements Document — AFL Predict

> **Version:** 0.1 (Placeholder)
> **Status:** Draft

---

## 1. Problem Statement

AFL betting markets offer pre-match head-to-head odds that can be analysed for
systematic edge using historical results, team form, and market movement.
This system provides a research platform to explore whether a consistent,
evidence-based edge exists — without automating live financial risk.

---

## 2. Objectives

1. Build a reliable daily data pipeline for AFL fixtures, results, and TAB odds.
2. Implement and evaluate baseline prediction models.
3. Track hypothetical (paper-trade) bets to measure model performance.
4. Produce a daily recommendation report for manual review.

---

## 3. Non-Goals (MVP)

- No live bet placement.
- No real-money bankroll management.
- No intraday odds scraping (daily snapshots only).
- No other sports or bet types (head-to-head only for now).

---

## 4. Data Sources

| Source         | Type              | Status         | Notes                              |
|----------------|-------------------|----------------|------------------------------------|
| AFL Tables     | Fixtures/Results  | TODO           | Public historical data             |
| TAB Australia  | H2H Odds          | TODO           | Requires scraping or API agreement |
| FootyWire      | Player stats      | Out of scope   | Future feature                     |

---

## 5. Models (Baseline Phase)

| Model               | Description                                  | Priority |
|---------------------|----------------------------------------------|----------|
| Bookmaker Baseline  | Implied probability from opening odds        | P0       |
| ELO Baseline        | Simple ELO rating system                     | P0       |
| Logistic Regression | Features → win probability                   | P1       |

---

## 6. Evaluation Metrics

- Brier Score (probability calibration)
- Log Loss
- Accuracy vs. bookmaker implied accuracy
- Return on Investment (paper trades)
- Kelly fraction distribution

---

## 7. Pipeline Schedule

| Job                      | Schedule        |
|--------------------------|-----------------|
| ingest_afl               | Daily 06:00 AEST|
| ingest_tab_odds          | Daily 07:00 AEST|
| build_features           | Daily 07:30 AEST|
| train_models             | Weekly Monday   |
| generate_recommendations | Daily 08:00 AEST|
| settle_results           | Daily after 23:00 AEST (match day) |

---

## 8. Milestones

| Milestone                  | Target        |
|----------------------------|---------------|
| MVP scaffold complete      | Week 1        |
| Historical data loaded     | Week 2        |
| Baseline models validated  | Week 3        |
| Paper trading running      | Week 4        |
| First season review        | End of season |

---

## 9. Risks

- TAB odds data availability / terms of service — **HIGH**
- Model overfitting to small AFL sample sizes — **MEDIUM**
- Odds movement not captured with daily-only snapshots — **MEDIUM**

---

## 10. Open Questions

- Which historical odds data source to use for backtesting?
- What confidence threshold triggers a recommendation?
- How to handle bye rounds and finals?
