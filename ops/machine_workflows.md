# AFL Predict — Machine Setup & Operation Guide

## 머신 역할 구성

| 머신 | GPU | 역할 | NODE_ROLE |
|------|-----|------|-----------|
| **서버 컴퓨터** | RX 6600 | 24/7 데이터 수집, API 서버 | `collector` |
| **메인 컴퓨터** | RTX 5080 | 모델 학습, 백테스트, 분석 | `predictor` |

두 머신은 **PostgreSQL DB (서버에서 실행)** 를 공유합니다.
RTX 5080이 RX 6600의 DB에 네트워크로 접속하는 구조입니다.

---

## 공통 사전 준비 (두 머신 모두)

### 1. Python 3.11 설치 확인
```cmd
python --version
```
`Python 3.11.x` 가 나와야 함. 아니면 python.org에서 3.11 설치.

### 2. 프로젝트 폴더 확인

| 머신 | 경로 |
|------|------|
| 서버 컴퓨터 (RX 6600) | `C:\Users\<you>\AFL_predict` |
| 메인 컴퓨터 (RTX 5080) | `C:\Users\user\OneDrive\바탕 화면\codex-hub\AFL_predict` |

### 3. venv 생성 및 패키지 설치 (각 머신에서 독립적으로)

**서버:**
```cmd
cd "C:\Users\<you>\AFL_predict"
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

**메인:**
```cmd
cd "C:\Users\user\OneDrive\바탕 화면\codex-hub\AFL_predict"
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

---

## 서버 컴퓨터 (RX 6600) 셋업

### Step 1 — PostgreSQL 설치

1. [postgresql.org/download/windows](https://www.postgresql.org/download/windows/) 에서 설치
2. 설치 중 비밀번호 설정 (기억해둘 것)
3. 기본 포트: `5432`
4. 설치 후 DB 생성:

```sql
-- pgAdmin 또는 psql 에서 실행
CREATE DATABASE afl_predict;
CREATE USER afl_user WITH PASSWORD 'your_password_here';
GRANT ALL PRIVILEGES ON DATABASE afl_predict TO afl_user;
```

### Step 2 — 방화벽 포트 열기

PostgreSQL (5432)과 API (8000)를 로컬 네트워크에서 접근 가능하게 합니다.

**Windows 방화벽 — PowerShell (관리자 권한):**
```powershell
New-NetFirewallRule -DisplayName "AFL PostgreSQL" -Direction Inbound -Protocol TCP -LocalPort 5432 -Action Allow
New-NetFirewallRule -DisplayName "AFL API" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

**PostgreSQL 원격 접속 허용 — `pg_hba.conf` 편집:**
```
# 로컬 네트워크 (예: 192.168.0.0/24) 접속 허용
host    afl_predict    afl_user    192.168.0.0/24    md5
```
파일 위치: `C:\Program Files\PostgreSQL\16\data\pg_hba.conf`
수정 후 PostgreSQL 서비스 재시작.

### Step 3 — .env 파일 생성

```cmd
cd "C:\Users\<you>\AFL_predict"
copy .env.example .env
```

`.env` 파일을 메모장으로 열고 아래와 같이 설정:

```env
APP_ENV=production
APP_DEBUG=false
LOG_LEVEL=INFO

# PostgreSQL (서버 자신의 DB)
DB_URL=postgresql+psycopg2://afl_user:your_password_here@localhost:5432/afl_predict

# Odds API
ODDS_API_KEY=your_odds_api_key_here

# 역할
NODE_ROLE=collector

# 파이프라인
PAPER_TRADE_ONLY=true
MIN_EDGE_THRESHOLD=0.03
MAX_KELLY_FRACTION=0.05

# Telegram (선택)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_ENABLED=false
```

### Step 4 — DB 스키마 초기화

```cmd
cd "C:\Users\<you>\AFL_predict"
.venv\Scripts\activate.bat
alembic upgrade head
```

### Step 5 — 초기 데이터 수집 (최초 1회)

```cmd
cd "C:\Users\<you>\AFL_predict"
.venv\Scripts\activate.bat

rem AFL 픽스처 수집 (2022~현재)
python -m orchestration.jobs.ingest_afl --season 2022
python -m orchestration.jobs.ingest_afl --season 2023
python -m orchestration.jobs.ingest_afl --season 2024
python -m orchestration.jobs.ingest_afl --season 2025

rem 오즈 수집
python -m orchestration.jobs.ingest_tab_odds

rem 날씨 백필 (과거 시즌)
python -m orchestration.jobs.fetch_weather --season 2024
python -m orchestration.jobs.fetch_weather --season 2025

rem 선수 기록 백필
python -m orchestration.jobs.fetch_player_stats --season 2024
python -m orchestration.jobs.fetch_player_stats --season 2025
```

### Step 6 — Windows 작업 스케줄러 (자동 실행)

**작업 스케줄러 열기:** 시작 메뉴 → "작업 스케줄러" 검색

아래 3개 작업을 등록합니다.

**작업 1: 일일 파이프라인 (매일 08:00)**
- 이름: `AFL_DailyPipeline`
- 트리거: 매일 08:00
- 동작: 프로그램/스크립트
  ```
  C:\Users\<you>\AFL_predict\.venv\Scripts\python.exe
  ```
  인수:
  ```
  -m orchestration.daily_pipeline --triggered-by cron
  ```
  시작 위치:
  ```
  C:\Users\<you>\AFL_predict
  ```

**작업 2: 날씨 수집 (매일 07:00)**
- 이름: `AFL_FetchWeather`
- 트리거: 매일 07:00
- 동작: 위와 동일, 인수:
  ```
  -m orchestration.jobs.fetch_weather
  ```

> **팁:** 스케줄러 작업 → 우클릭 → "실행" 으로 즉시 테스트 가능.

> **주의:** `train_models`는 서버가 아닌 메인 컴퓨터에 등록합니다. 피처 parquet가 메인 로컬에 저장되고 RTX 5080 CUDA를 사용해야 하기 때문입니다.

### Step 7 — API 서버 자동 시작

시작 프로그램에 API 서버를 등록합니다.

`C:\Users\<you>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\` 에
`start_afl_api.bat` 파일 생성:

```bat
@echo off
cd /d "C:\Users\<you>\AFL_predict"
call .venv\Scripts\activate.bat
start /b uvicorn api.main:app --host 0.0.0.0 --port 8000 >> logs\api.log 2>&1
```

로그 폴더 생성:
```cmd
mkdir "C:\Users\<you>\AFL_predict\logs"
```

---

## 메인 컴퓨터 (RTX 5080) 셋업

### Step 1 — .env 파일 생성

```cmd
cd "C:\Users\user\OneDrive\바탕 화면\codex-hub\AFL_predict"
copy .env.example .env
```

`.env` 파일 설정 (서버 IP를 실제 값으로 교체):

```env
APP_ENV=development
APP_DEBUG=true
LOG_LEVEL=INFO

# 서버의 PostgreSQL에 원격 접속
# 서버 IP 확인: 서버 컴퓨터에서 ipconfig 실행
DB_URL=postgresql+psycopg2://afl_user:your_password_here@192.168.0.XXX:5432/afl_predict

# Odds API (서버와 동일한 키)
ODDS_API_KEY=your_odds_api_key_here

# 역할
NODE_ROLE=predictor

# 파이프라인
PAPER_TRADE_ONLY=true
MIN_EDGE_THRESHOLD=0.03
MAX_KELLY_FRACTION=0.05
```

### Step 2 — DB 접속 확인

```cmd
.venv\Scripts\activate.bat
python -c "from db.session import SessionLocal; db=SessionLocal(); print('DB connected OK'); db.close()"
```

### Step 3 — Windows 작업 스케줄러 (자동 실행)

> **전제:** 서버의 PostgreSQL이 켜져 있어야 합니다. 서버가 꺼지면 아래 모든 작업이 실패합니다.

**작업 스케줄러 열기:** 시작 메뉴 → "작업 스케줄러" 검색

아래 2개 작업을 등록합니다.

**작업 1: 일일 파이프라인 — predictor (매일 09:30)**

서버 collector 파이프라인(08:00)이 끝난 뒤 실행합니다.

- 이름: `AFL_DailyPipeline_Predictor`
- 트리거: 매일 09:30
- 동작: 프로그램/스크립트
  ```
  C:\Users\user\OneDrive\바탕 화면\codex-hub\AFL_predict\.venv\Scripts\python.exe
  ```
  인수:
  ```
  -m orchestration.daily_pipeline --triggered-by cron
  ```
  시작 위치:
  ```
  C:\Users\user\OneDrive\바탕 화면\codex-hub\AFL_predict
  ```

실행 내용 (NODE_ROLE=predictor 기준):
- `build_features` — DB에서 피처 읽어 parquet 저장
- `generate_recommendations` — 모델 추론, 베팅 추천 생성
- `notify_bets` — Discord/Telegram 알림
- `settle_results` — 종료 경기 결과 정산

**작업 2: 주간 모델 재학습 (일요일 03:00)**

서버 날씨 수집(07:00) 전에 완료됩니다. 서버가 켜져 있어야 DB 저장 가능.

- 이름: `AFL_WeeklyTrain`
- 트리거: 매주 일요일 03:00
- 동작: 위와 동일, 인수:
  ```
  -m orchestration.jobs.train_models
  ```

학습 결과는 `storage/model_artifacts/`(메인 로컬)에 저장되고, RTX 5080 CUDA가 자동 활성화됩니다.

> **팁:** 스케줄러 작업 → 우클릭 → "실행" 으로 즉시 테스트 가능.

### Step 3 — CUDA 확인 (XGBoost GPU 가속)

RTX 5080의 XGBoost GPU 가속은 CUDA Toolkit이 있으면 자동 활성화됩니다.

```cmd
.venv\Scripts\activate.bat
python -c "import xgboost as xgb; print(xgb.__version__); dm=xgb.DMatrix([[1,2],[3,4]], label=[0,1]); m=xgb.train({'device':'cuda','verbosity':0}, dm, 1); print('CUDA OK')"
```
`CUDA OK` 가 나오면 GPU 학습 활성화됨. 에러 시 CPU로 폴백 (자동).

### Step 4 — 피처 빌드 및 모델 학습

서버에서 데이터 수집이 완료된 뒤 메인에서 실행:

```cmd
.venv\Scripts\activate.bat

rem 피처 매트릭스 빌드
python -m orchestration.jobs.build_features

rem 모델 학습 (XGBoost는 RTX 5080 CUDA 사용)
python -m orchestration.jobs.train_models

rem 백테스트
python -m orchestration.jobs.run_backtest --mode expanding
```

---

## 초기 설치 완료 확인 체크리스트

두 머신에서 순서대로 실행합니다.

### 서버 (RX 6600) 확인
```cmd
cd "C:\Users\<you>\AFL_predict"
.venv\Scripts\activate.bat

rem 1. DB 연결
python -c "from db.session import SessionLocal; db=SessionLocal(); print('DB OK'); db.close()"

rem 2. API 서버 기동
uvicorn api.main:app --host 0.0.0.0 --port 8000

rem 3. 브라우저에서 확인: http://localhost:8000/health
```

### 메인 (RTX 5080) 확인
```cmd
.venv\Scripts\activate.bat

rem 1. 서버 DB 원격 연결
python -c "from db.session import SessionLocal; db=SessionLocal(); print('Remote DB OK'); db.close()"

rem 2. 서버 API 접근 (서버 IP로 교체)
curl http://192.168.0.XXX:8000/health

rem 3. 테스트 전체 통과
python -m pytest tests/ -v
```

---

## 일상 운영 워크플로우

### 매일 아침 (메인 컴퓨터에서)

```cmd
.venv\Scripts\activate.bat

rem 오늘 파이프라인 상태
curl http://192.168.0.XXX:8000/dashboard/summary

rem 오늘의 픽
curl http://192.168.0.XXX:8000/dashboard/recommendations

rem 데이터 신선도
curl http://192.168.0.XXX:8000/dashboard/freshness

rem CLV 현황 (배팅 엣지 검증)
curl http://192.168.0.XXX:8000/dashboard/clv
```

### 서버 파이프라인 수동 재실행

```cmd
rem 서버 컴퓨터에서:
.venv\Scripts\activate.bat
python -m orchestration.daily_pipeline --triggered-by manual
```

### 서버 로그 확인

```cmd
rem 파이프라인 로그
type logs\pipeline.log | more

rem 실시간 확인 (PowerShell)
Get-Content logs\pipeline.log -Wait -Tail 50
```

---

## 문제 해결

| 증상 | 확인 |
|------|------|
| DB 연결 실패 | 서버 PostgreSQL 서비스 실행 중인지 확인, 방화벽 5432 포트 |
| API 응답 없음 | 서버에서 `uvicorn` 프로세스 실행 중인지 확인, 방화벽 8000 포트 |
| 오즈 수집 실패 | `.env`의 `ODDS_API_KEY` 확인, 월 500회 쿼터 확인 |
| XGBoost CUDA 미작동 | CUDA Toolkit 설치 확인, `nvidia-smi` 실행 확인 |
| 파이프라인 cron 미실행 | 작업 스케줄러에서 마지막 실행 시간/결과 확인 |
