# 프리뷰/리뷰 생성기 사전 점검 리포트

작성일: 2026-06-17
대상: RTX 5080 + unsloth QLoRA 기반 경기 프리뷰/리뷰 생성기 붙이기 전 준비도 점검
방법: 코드 직접 조사 (추측 배제, `file:line` 근거만)

---

## 0. 한 줄 결론

> **데이터·이력 인프라는 대부분 준비됨(D·E 녹색). 하지만 "왜"를 설명할 재료(C: SHAP/경기단위 기여도)는 아직 없고, 예측 시점 컨텍스트 스냅샷이 분산·부분 저장되어 있어 `match_context` 조립 계층을 새로 만들어야 한다(A·B 노랑).**

신호등 요약:

| 섹션 | 주제 | 상태 | 핵심 메시지 |
|---|---|:---:|---|
| A | 예측 출력 형태 | 🟡 | DB엔 앙상블 확률·edge·kelly만. 단일경기 전용 경로 없음(배치 루프 내부 함수). |
| B | 컨텍스트 피처 노출 | 🟡 | 피처는 풍부하나 DB 스냅샷은 부분집합. margin/score 미노출. |
| C | SHAP / 경기단위 "왜" | 🔴 | **SHAP 미사용.** 모델 단위 gain importance를 로그로만 출력. 경기별 기여도 없음. |
| D | fixture vs result 수집 | 🟢 | 예정·완료 둘 다 수집·저장. odds도 match_id로 매칭 저장. |
| E | 예측 이력 / 리뷰 | 🟢 | match_id 조인 + BetOutcome 정산 + CLV까지. 리뷰 구조 견고. |

---

## A. 예측 출력 — 무엇을, 어떤 형태로

- **단일 경기 생성 함수**: `_create_prediction_and_rec()` — `orchestration/jobs/generate_recommendations.py:367`
  - 단, **단일 경기 전용 API/진입점은 없음.** 배치 `run()`의 루프(라인 134~136) 안에서 행 단위로만 호출됨.
- **반환 타입 (계층별로 다름)**:
  - 모델: `BaseModel.predict_proba()` → `pd.DataFrame` (`models/base_model.py:33`)
  - API: `PredictionOut` pydantic, **배치만** `GET /predictions/?match_id=` → `list[PredictionOut]` (`api/routes/predictions.py:12,22`)
  - DB: `Prediction` ORM row (`db/models/predictions.py:11`)
  - 대시보드: `dict` (`generate_predictions_json.py:126`)
- **DB `Prediction` 저장 필드** (`db/models/predictions.py:14-30`): `match_id`, `model_run_id`, `home_win_prob`, `away_win_prob`, `home_edge`, `away_edge`, `kelly_home`, `kelly_away`, `created_at`
- **⚠️ 개별 모델 확률(xgboost/poisson/elo)은 DB에 저장되지 않음.** 대시보드 JSON에만 `xgboost_prob/poisson_prob/elo_prob`가 등장하고, 이는 CSV에서 읽어옴(`generate_predictions_json.py:126-140`). → 사후 리뷰에서 "모델 간 의견 충돌"을 DB만으로 재구성 불가.

**프리뷰 영향**: win_prob·edge·kelly는 바로 쓸 수 있음. 하지만 "모델별 확률 분해"는 예측 직후 JSON을 잡아두지 않으면 사라짐.

---

## B. 컨텍스트 피처 노출 — 프리뷰의 "재료"

| 재료 | 노출 여부 | 컬럼 | 근거 |
|---|:---:|---|---|
| ELO rating | ✅ 경기단위 노출 | `home_elo_pre`, `away_elo_pre`, `elo_diff` | `features/extractors/elo.py:97-101` |
| Form (멀티윈도우) | ✅ 노출 | `*_win_rate_l3/l5/l10`, `*_avg_pts_for/against_l10`, `*_momentum` | `features/extractors/form.py:145-152` |
| H2H | ✅ 노출 | `h2h_home_win_rate_l5`, `h2h_avg_margin_l5`, `h2h_games_played` | `features/extractors/h2h.py:89-104` |
| Predicted margin/score | ❌ **미노출** | Poisson이 `mu_home/mu_away` 내부 계산만, 확률로 변환 후 폐기 | `models/poisson_model.py:47-55,103-116` |

- **피처명은 사람이 읽을 수 있는 snake_case** (`bm_home_implied_prob`, `elo_diff`, `home_win_rate_l10`...). LLM 프롬프트에 라벨 매핑 거의 불필요.
- **XGBoost 최종 사용 ~30컬럼**, 전체 생성 ~50컬럼 (`models/xgboost_model.py:25-60`).

### ⚠️ B의 함정 — DB 스냅샷은 부분집합
`match_features` 테이블(`db/models/match_features.py`)에 **영구 저장되는 건 일부뿐**:
- 저장됨: ELO 3개, **l10 form만**, bookmaker odds, rest/travel, venue, target `home_win`
- **저장 안 됨: h2h, momentum, l3/l5 윈도우, weather, odds_movement, player availability**

→ 전체 피처 벡터는 `data/processed/features_latest_*.csv` + parquet에만 존재. 즉 **"예측 시점에 모델이 본 전체 컨텍스트"를 경기 row 하나로 재현하려면 CSV/parquet를 따로 보존·조인해야 함.** DB의 `match_features`만 믿으면 재료의 절반이 빠진다.

---

## C. SHAP — 🔴 가장 큰 갭

- **SHAP 라이브러리 미사용.** 코드 전체에 `import shap` 없음.
- 현재 있는 건 XGBoost **native gain importance**, 그것도:
  - **학습 시점**에만 계산 (`orchestration/jobs/train_models.py:385-402`, `_log_feature_importances`)
  - **로그로만 출력**, 저장 안 함
  - **모델 전체 수준** 집계 — 경기별(sample-level) 기여도 아님
- `XGBoostModel.predict_proba()`는 확률만 반환 (`models/xgboost_model.py:145-154`). 경기별 설명 저장 인프라 없음.

**프리뷰/리뷰 영향 (치명적)**: 프리뷰의 핵심인 *"이 경기는 ELO 격차 +85와 홈팀 l10 폼이 강해서 67%"* 같은 **경기별 "왜"를 만들 재료가 0**. 생성기를 붙이기 전 반드시 채워야 할 1순위.

---

## D. fixture vs result — 🟢 양호

| 항목 | 상태 | 근거 |
|---|:---:|---|
| 예정 경기 수집 | ✅ | `squiggle_collector.fetch_games()` `q=games&year=`, 예정/완료 동시 반환 (`squiggle_collector.py:56-78`) |
| 완료 스코어 저장 | ✅ | `matches.home_score/away_score/result` (`db/models/matches.py:31-34`), 완료 시에만 채움 |
| 결과 덮어쓰기 방지 | ✅ | `existing.result is None`일 때만 정산 (`ingest_afl.py:220`) |
| Squiggle 엔드포인트 | `games`만 | `tips`/`standings` 미사용 |
| Odds 매칭 저장 | ✅ | `odds_snapshots.match_id` FK, `_resolve_match()`로 매칭 후 upsert (`ingest_tab_odds.py:165,180,198`) |

**프리뷰=예정경기, 리뷰=완료경기** 두 입력 모두 확보됨. odds도 실시간 조회가 아니라 경기에 묶여 영구 저장됨.

---

## E. 예측 이력 / 리뷰 가능성 — 🟢 견고

- `model_runs`: **메타데이터만** (모델명·버전·brier/logloss/accuracy·artifact_path·status). 경기별 예측은 여기 없음 (`db/models/model_runs.py:11-48`).
- `predictions`: 예측 시점 **확률·edge·kelly 스냅샷 보존** + `created_at` (`db/models/predictions.py`). `model_run_id`로 어느 모델이 냈는지 추적 가능.
- **조인 키**: `Prediction.match_id → Match.id` → `Match.result/home_score/away_score`. 명확.
- **정산**: `settle_results._settle_pending()` (`settle_results.py:60-109`)가 추천 side vs 실제 result 비교 → `BetOutcome(won, profit_loss_units, closing_odds, clv)` 생성. CLV는 마감 odds 스냅샷과 대조해 계산(`:112-147`).
- 리뷰 조회: `GET /dashboard/performance`가 예측-결과 쌍 전체 + 누적 P&L + 캘리브레이션 제공 (`api/routes/dashboard.py:317-468`).

**리뷰 생성기 관점**: "예측↔실제" 대조 데이터는 완비. 단, E도 A·B의 한계를 그대로 물려받음 — **개별 모델 확률·전체 피처 스냅샷·기여도는 보존되지 않으므로**, 리뷰에서 "어느 피처 판단이 빗나갔나"를 말하려면 C/B 갭부터 메워야 함.

---

## 종합: `match_context` 조립 준비도

`match_context`(경기 단위 구조화 출력 = LLM 학습/추론 input)에 필요한 블록별 현황:

| match_context 블록 | 재료 존재? | 현재 위치 | 갭 |
|---|:---:|---|---|
| 경기 식별/일정/장소 | ✅ | `matches`, `match_features` | 없음 |
| 모델 최종 확률·edge·kelly | ✅ | `predictions` | 없음 |
| 모델별 확률 분해 | △ | 대시보드 JSON(CSV) | DB 미보존 — 예측 직후 캡처 필요 |
| 컨텍스트 피처 (ELO/form/h2h) | ✅ | CSV/parquet (DB는 부분) | 전체 벡터를 경기에 고정 저장 필요 |
| 예측 margin/score | ❌ | (폐기됨) | Poisson `mu_home/mu_away` 노출 필요 |
| 경기별 "왜" (기여도) | ❌ | 없음 | **SHAP 추론 시점 계산+저장 신규** |
| 실제 결과 (리뷰용) | ✅ | `matches`, `bet_outcomes` | 없음 |

---

## 붙이기 전 해야 할 일 (우선순위)

1. **[P0 · C 갭] 추론 시점 SHAP 계산 + 경기별 top-k 기여도 저장**
   - `XGBoostModel`에 `explain(X) -> per-row contributions` 추가 → `predictions`에 연결된 신규 테이블(or JSON 컬럼)에 저장.
   - 프리뷰의 "왜"와 리뷰의 "어디서 틀렸나" 양쪽의 유일한 재료. 이게 없으면 생성기는 확률 나열기에 그침.

2. **[P0 · A/B 갭] 예측 시점 `match_context` 스냅샷 영속화**
   - 예측을 낼 때 모델이 실제로 본 **전체 피처 행(50컬럼) + 개별 모델 확률**을 경기에 묶어 저장(append-only).
   - 현재 CSV는 `_latest_`로 덮어써질 위험 — 리뷰 시점에 "그때 그 피처"가 사라지지 않도록 고정.

3. **[P1 · B 갭] predicted margin/score 노출**
   - `poisson_model._predict_score_mode()`의 `mu_home/mu_away`를 출력 경로로 빼서 `predicted_margin` 제공. 프리뷰 자연어 품질을 크게 올림.

4. **[P1] `match_context` 빌더 단일 함수 신설**
   - 위 재료(식별·확률·분해·피처·기여도·margin·결과)를 한 dict/pydantic로 조립하는 `build_match_context(match_id)` 작성. 이게 LLM 생성기의 입력 계약(contract)이 됨. predictions.json 스키마를 확장하는 형태가 자연스러움.

5. **[P2] 피처 라벨 사전(선택)**
   - 컬럼명이 이미 읽을 만하지만, 프리뷰 자연어 품질을 위해 `elo_diff → "ELO 격차"` 류 사람친화 라벨 맵을 두면 좋음. 필수는 아님.

### 생성기 붙일 때 우선 손댈 파일 3개
1. `orchestration/jobs/generate_recommendations.py` — 예측 출력 + 스냅샷 저장 지점 (A·B·C 주입처)
2. `models/xgboost_model.py` — SHAP/기여도 노출 (C)
3. `db/models/predictions.py` (+ 신규 테이블) — 경기단위 컨텍스트/기여도 영속화 (A·B·E 연결)
