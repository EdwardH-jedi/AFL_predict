# AFL Predict — 24/7 오케스트레이션 가이드 (RX 6600 + RTX 5080)

> 설치 절차는 [`ops/machine_workflows.md`](machine_workflows.md) 참조.
> 이 문서는 **"누가 언제 무엇을 실행하는가"** 와 장애 시 동작을 정의하는 운영 기준(single source of truth)이다.
> 스케줄 시각이 다른 문서/스크립트와 다르면 **이 문서가 우선**한다.

---

## 1. 머신 역할 매트릭스

| 항목 | 서버 (RX 6600) | 메인 (RTX 5080) |
|------|---------------|-----------------|
| 가동 | **24시간 상시** | 필요 시 (최소: 매일 09:30 전후 + 일요일 새벽) |
| NODE_ROLE | `collector` | `predictor` |
| PostgreSQL | **호스트** (localhost:5432) | 원격 접속 |
| FastAPI + 대시보드 | **호스트** (0.0.0.0:8000, 시작 프로그램 등록) | 접속만 |
| 데이터 수집 (fixtures/odds/weather) | O | X |
| 피처 빌드 + 모델 추론 + 추천 | X | O |
| 모델 학습 (CUDA) | X | O (주 1회) |
| 모델 아티팩트 (`storage/model_artifacts/`) | 없음 | **로컬 보관** |
| Discord 알림 | X | O (파이프라인 내 `notify_bets`) |

핵심 원칙:
- **RX 6600은 DB·API·수집의 단일 장애점(SPOF)이다.** 이 머신이 꺼지면 시스템 전체가 정지한다 — 절전 금지 (§5).
- **RTX 5080은 계산 노드다.** 꺼져 있어도 데이터 수집·대시보드 조회는 계속되지만, 그날의 추천·알림·정산은 생성되지 않는다 (§4).
- 두 머신의 유일한 공유 상태는 **PostgreSQL**이다. 아티팩트(모델 파일, parquet)는 5080 로컬이며 DB를 통해 결과(Prediction/Recommendation 행)만 공유된다.

## 2. 정규 스케줄 (canonical)

### 일일

| 시각 | 머신 | 작업 (Task Scheduler 이름) | 내용 |
|------|------|---------------------------|------|
| 07:00 | RX 6600 | `AFL_FetchWeather` | Open-Meteo 날씨 수집 |
| 08:00 | RX 6600 | `AFL_DailyPipeline` | collector 파이프라인: freshness → ingest_afl → ingest_tab_odds → daily_summary → role_data_steward |
| 09:30 | RTX 5080 | `AFL_DailyPipeline_Predictor` | predictor 파이프라인: build_features → generate_recommendations → notify_bets → settle_results → daily_summary → role 감사 5종 |

collector(08:00)와 predictor(09:30) 사이 90분 간격은 수집 재시도 여유분이다. 두 작업 모두 `StartWhenAvailable` 설정으로, 시각을 놓치면 부팅/로그인 직후 따라잡는다.

### 주간

| 시각 | 머신 | 작업 | 내용 |
|------|------|------|------|
| 일 03:00 | RTX 5080 | `AFL_WeeklyTrain` | `train_models` — 5개 모델 + 캘리브레이션 + 앙상블, CUDA 사용, 아티팩트는 5080 로컬 저장 |

### 주간 (미등록 — 추가 필요)

| 시각 | 머신 | 작업 | 내용 |
|------|------|------|------|
| 목 18:30 | RX 6600 | `AFL_FetchPlayerStats` (신규) | `fetch_player_stats` — AFL 팀시트는 목요일 ~18:00 AEST 발표. 현재 어디에도 스케줄되어 있지 않아 `PlayerAvailabilityExtractor`가 항상 중립값을 반환한다 (data-steward Fix #8) |

등록 방법 (RX 6600, 관리자 PowerShell):

```powershell
$py  = "C:\Users\edwar\AFL_predict\.venv\Scripts\python.exe"
$dir = "C:\Users\edwar\AFL_predict"
Register-ScheduledTask -TaskName "AFL_FetchPlayerStats" `
  -Action  (New-ScheduledTaskAction -Execute $py -Argument "-m orchestration.jobs.fetch_player_stats" -WorkingDirectory $dir) `
  -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At "18:30") `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1))
```

## 3. 어느 스크립트로 등록하는가

| 머신 | 실행 | 주의 |
|------|------|------|
| RX 6600 | `ops\windows_tasks\register_tasks.ps1` (기본 `-Role server`) | ⚠ 현재 server 롤에 `AFL_WeeklyTrain`까지 등록한다 — **잘못된 배치.** 학습은 5080 전용이므로 등록 후 `Unregister-ScheduledTask -TaskName AFL_WeeklyTrain` 로 제거하거나 스크립트에서 해당 블록 삭제 |
| RTX 5080 | `ops\setup_scheduler_predictor.ps1` | ⚠ `AFL_NotifyBets`(10:00)를 별도 등록하는데, predictor 파이프라인(09:30)에 이미 `notify_bets`가 포함되어 있어 **Discord 이중 알림** 가능. 별도 작업은 제거 권장 |

등록 후 확인:

```powershell
Get-ScheduledTask | Where-Object TaskName -like 'AFL_*' | Select-Object TaskName, State
```

## 4. 장애 모드와 대응

| 시나리오 | 영향 | 대응 |
|----------|------|------|
| **RTX 5080이 09:30에 꺼져 있음** | 그날 추천·알림·정산 없음. 수집·대시보드는 정상 (전일 데이터 표시) | `StartWhenAvailable`로 부팅 시 자동 따라잡기. 수동: `python -m orchestration.daily_pipeline --triggered-by manual` |
| **RX 6600 다운** | 전면 정지 — DB 접속 불가로 5080 작업도 전부 실패 | 재부팅 → PostgreSQL 서비스 자동 시작 확인 → 시작 프로그램의 API 서버 확인 → 놓친 파이프라인 수동 실행 |
| **네트워크 단절 (5080→6600)** | predictor 파이프라인 DB 접속 실패 | 방화벽 5432/8000, 서버 IP 변동 확인 (공유기에서 RX 6600에 **고정 IP 할당** 권장) |
| **Odds API 쿼터 소진** (월 500회) | `ingest_tab_odds` 실패 → hard_dep이라 collector 후속 잡 스킵 | 쿼터는 매월 리셋. `/dashboard/freshness`로 마지막 성공 확인 |
| **주간 학습 실패** | 추천은 기존 아티팩트로 계속 생성 (아티팩트는 버전 보존, 덮어쓰기 없음) | 5080에서 `python -m orchestration.jobs.train_models` 수동 재실행 |

파이프라인 상태 원격 확인 (아무 머신에서나):

```
http://<RX6600-IP>:8000/dashboard/freshness    데이터 신선도
http://<RX6600-IP>:8000/dashboard/summary      오늘 파이프라인 결과
http://<RX6600-IP>:8000/api/sync/status        노드 롤 + 잡 상태 (X-Sync-Token 필요)
```

## 5. RX 6600 24시간 가동 설정 (Windows 11)

관리자 PowerShell에서 1회 실행:

```powershell
# 절전/최대 절전 완전 비활성 (AC 기준)
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 10   # 모니터만 끔

# 디스크 절전 해제
powercfg /change disk-timeout-ac 0
```

추가 체크리스트:
- [ ] BIOS: 정전 후 자동 재부팅 (Restore on AC Power Loss = Power On)
- [ ] Windows 자동 로그인 (Task Scheduler를 Interactive 로그온으로 등록했으므로 로그인 세션 필요) — `netplwiz`
- [ ] PostgreSQL 서비스 시작 유형 = 자동
- [ ] Windows Update 활성 시간 설정 (07:00–10:00 파이프라인 창을 피해서 재부팅되도록)
- [ ] 공유기에서 고정 IP(DHCP 예약) — 5080의 `.env` `DB_URL`이 IP를 하드코딩하므로 필수

## 6. 데이터/아티팩트 흐름 요약

```
[RX 6600, 24/7]                              [RTX 5080, on-demand]
Squiggle/OddsAPI/Open-Meteo/AFLTables
        │ 07:00~08:00 수집
        ▼
   PostgreSQL ◄──────────────────────────── 09:30 build_features (DB 읽기)
   (단일 공유 상태)                              │ parquet + 모델 아티팩트는 5080 로컬
        ▲                                       ▼
        └──────────────────────────────── generate_recommendations
                                          (Prediction/Recommendation 행을 DB에 기록)
        │                                       │
        ▼                                       ▼
   FastAPI :8000 대시보드 (24/7 조회 가능)   notify_bets → Discord
```

- 직접 DB 접속이 불가한 환경(외부망 등)에서는 `api/routes/data_sync.py`의 `/api/sync/latest-odds`, `/api/sync/latest-features`, `POST /api/sync/predictions`를 대체 경로로 사용 (양쪽 `.env`에 동일한 `API_SECRET_KEY` 필요).
- 모델 아티팩트는 의도적으로 동기화하지 않는다 — 추론이 5080에서만 일어나므로 필요 없음. 추론을 6600으로 옮기는 설계 변경 시에만 동기화가 필요해진다.

## 7. 드리프트 이력

2026-07-04 감사에서 발견되어 **같은 날 모두 해소됨** — 문서/스크립트가 §2 정규 스케줄과 일치한다:

| 항목 | 발견된 불일치 | 정본 (적용됨) |
|------|--------------|---------------|
| predictor 일일 파이프라인 시각 | machine_workflows.md=09:00 vs setup_scheduler_predictor.ps1=09:30 | **09:30** |
| 주간 학습 시각 | machine_workflows.md=일 04:00 vs 스크립트 2종=일 03:00 | **일 03:00** |
| 주간 학습 배치 | register_tasks.ps1이 server 롤에도 등록 | **5080 전용** (server 롤은 기존 등록분도 자동 제거) |
| notify 이중 실행 | setup_scheduler_predictor.ps1의 별도 AFL_NotifyBets(10:00) | **파이프라인 내장 1회만** (스크립트가 기존 등록분 자동 제거) |
| 메인 머신 경로 | machine_workflows.md=`...\바탕 화면\AFL_predict` vs 실제=`...\바탕 화면\codex-hub\AFL_predict` | 실제 경로 |

⚠ **이미 두 스크립트를 구버전으로 실행한 머신**에서는 갱신된 스크립트를 한 번 재실행하면 잘못 등록된 작업(`AFL_WeeklyTrain`@서버, `AFL_NotifyBets`@메인)이 자동 정리된다.
