# AFL Predict — Setup Guide

> **Fresh-clone TL;DR.** A new checkout pointed at an empty database
> must be brought up via Alembic. Run these from the repo root after
> creating your virtualenv and installing `requirements-dev.txt`:
>
> ```bash
> # Windows (PowerShell)
> copy .env.example .env
> python -m alembic upgrade head
> python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
> curl http://localhost:8000/health
> ```
>
> ```bash
> # Linux (bash)
> cp .env.example .env
> python -m alembic upgrade head
> python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
> curl http://localhost:8000/health
> ```
>
> `systemctl` (used in the Linux server steps further down) is **not**
> available on Windows — use Task Scheduler or NSSM there instead.
>
> Do not run `make db-init` on a database you intend to migrate with
> Alembic. The two flows produce overlapping DDL and will collide. For
> anything beyond a quick throwaway, prefer `python -m alembic upgrade
> head`.

---

# AFL Predict — 머신 셋업 가이드

RX6600 서버와 RTX5080 워크스테이션 두 환경에서 AFL Predict를 실행하기 위한 단계별 가이드.

---

## 역할 분담 (권장)

| 머신 | GPU | 권장 역할 |
|------|-----|-----------|
| 서버 컴퓨터 | RX6600 (AMD) | 파이프라인 스케줄 실행, API 서버, DB 호스팅 |
| 워크스테이션 | RTX5080 (NVIDIA) | 모델 학습, 백테스트, 개발 |

---

## 공통 사전 준비 (두 머신 모두)

### 1. Python 3.11 설치

```bash
# Windows — winget 사용
winget install Python.Python.3.11

# 설치 확인
python --version   # Python 3.11.x 이어야 함
```

> Python 3.12+ 는 일부 ML 패키지 호환 문제가 있으므로 반드시 3.11 사용.

### 2. Git 설치

```bash
winget install Git.Git

# 설치 후 재시작하거나 새 터미널 열기
git --version
```

### 3. 코드 받기

```bash
# OneDrive 동기화를 쓰지 않는 서버 머신이라면 git clone 사용
git clone <repo-url> AFL_predict
cd AFL_predict

# 개발 머신(OneDrive 동기화 중)이라면 이미 있는 폴더로 이동
cd "C:\Users\user\OneDrive\바탕 화면\AFL_predict"
```

### 4. PostgreSQL 설치 (DB를 로컬에 둘 경우)

```bash
winget install PostgreSQL.PostgreSQL

# 설치 후 pgAdmin 또는 psql로 DB 생성
psql -U postgres
```

```sql
CREATE DATABASE afl_predict;
CREATE USER afl_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE afl_predict TO afl_user;
\q
```

> 서버 머신에만 PostgreSQL을 설치하고, 워크스테이션은 서버 DB에 원격 접속해도 됨.

---

## 머신 A — RX6600 서버

AMD GPU는 Windows에서 CUDA를 지원하지 않으므로 ML 연산은 **CPU 모드**로 실행.  
파이프라인 스케줄링, API 서버, 데이터 수집 역할에 집중.

### Step 1: 가상환경 생성 및 의존성 설치

```bash
cd AFL_predict

python -m venv .venv
.venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements-dev.txt
```

### Step 2: 환경변수 설정

```bash
copy .env.example .env
notepad .env
```

`.env` 필수 항목 설정:

```env
# Database
DATABASE_URL=postgresql+psycopg2://afl_user:yourpassword@localhost:5432/afl_predict

# API Keys (실제 키로 교체)
ODDS_API_KEY=your_odds_api_key
SQUIGGLE_USER_AGENT=your_contact_email

# 환경
ENV=production
LOG_LEVEL=INFO
```

### Step 3: DB 초기화 및 마이그레이션

```bash
# 가상환경 활성화 상태에서 — Alembic으로 스키마 생성 + 최신 head 까지 업그레이드.
# make db-init (Base.metadata.create_all) 와 섞어 쓰지 말 것. 둘 중 하나만 사용.
make migrate
```

### Step 4: 스토리지 디렉토리 생성

```bash
mkdir storage\raw_snapshots
mkdir storage\model_artifacts
mkdir storage\daily_summaries
```

### Step 5: 설치 확인 (테스트 실행)

```bash
make test-fast
```

모든 테스트 통과 확인 후 진행.

### Step 6: API 서버 실행

```bash
make serve
# → http://0.0.0.0:8000 에서 실행
# → http://서버IP:8000/docs 에서 Swagger UI 확인
```

### Step 7: 파이프라인 수동 실행 테스트

```bash
# 데이터 수집 테스트
make ingest-afl ARGS="--season 2025 --dry-run"
make ingest-odds ARGS="--dry-run"

# 전체 파이프라인 1회 실행
make pipeline
```

### Step 8: 자동 스케줄 설정 (Windows 작업 스케줄러)

매일 자동 실행을 원한다면 Windows 작업 스케줄러 사용:

```bash
# 작업 스케줄러에 등록할 배치 파일 생성
# run_pipeline.bat 내용:
# cd /d "C:\path\to\AFL_predict"
# call .venv\Scripts\activate
# python -m orchestration.daily_pipeline --triggered-by cron
```

또는 PowerShell로 등록:

```powershell
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
  -Argument '/c "cd /d C:\path\to\AFL_predict && .venv\Scripts\activate && python -m orchestration.daily_pipeline --triggered-by cron"'
$trigger = New-ScheduledTaskTrigger -Daily -At "08:00AM"
Register-ScheduledTask -TaskName "AFL_Pipeline" -Action $action -Trigger $trigger
```

---

## 머신 B — RTX5080 워크스테이션 (NVIDIA)

CUDA를 활용한 GPU 가속 XGBoost 학습 + 개발 환경.

### Step 1: CUDA Toolkit 설치

RTX5080은 CUDA 12.x 지원.

1. [NVIDIA 공식 사이트](https://developer.nvidia.com/cuda-downloads)에서 CUDA Toolkit 12.x 다운로드
2. 설치 후 확인:

```bash
nvcc --version
nvidia-smi
```

### Step 2: 가상환경 생성

```bash
cd AFL_predict

python -m venv .venv
.venv\Scripts\activate

pip install --upgrade pip
```

### Step 3: GPU 지원 패키지 설치

```bash
# 기본 의존성 먼저 설치
pip install -r requirements-dev.txt

# XGBoost GPU 지원 버전 (CUDA 12.x용)
pip install xgboost --upgrade

# PyTorch GPU 버전 (필요한 경우 — 현재 프로젝트는 필수 아님)
# pip install torch --index-url https://download.pytorch.org/whl/cu124
```

### Step 4: GPU XGBoost 동작 확인

```python
# python 인터프리터에서 확인
import xgboost as xgb
print(xgb.__version__)

# GPU 사용 테스트
import numpy as np
X = np.random.rand(1000, 10)
y = np.random.randint(0, 2, 1000)
dtrain = xgb.DMatrix(X, label=y)
params = {"device": "cuda", "tree_method": "hist"}
model = xgb.train(params, dtrain, num_boost_round=10)
print("GPU XGBoost 정상 작동")
```

### Step 5: 환경변수 설정

서버 DB에 원격 접속하는 경우:

```bash
copy .env.example .env
notepad .env
```

```env
# 서버 머신의 PostgreSQL에 접속
DATABASE_URL=postgresql+psycopg2://afl_user:yourpassword@서버IP:5432/afl_predict

# API Keys
ODDS_API_KEY=your_odds_api_key
SQUIGGLE_USER_AGENT=your_contact_email

ENV=development
LOG_LEVEL=DEBUG
```

> 서버 PostgreSQL이 원격 접속을 허용하려면 `pg_hba.conf`와 `postgresql.conf`에서 설정 필요.

### Step 6: DB 마이그레이션 (서버 DB 사용 시)

```bash
# 서버에서 이미 migrate 했다면 생략
# 워크스테이션에서 처음 연결하는 경우만 실행
make migrate
```

### Step 7: 설치 확인

```bash
make test-fast
```

### Step 8: 모델 학습 실행

```bash
# 피처 빌드
make build-features ARGS="--season 2024"

# 모델 학습 (GPU 가속 자동 사용)
make train-models

# 백테스트
make backtest ARGS="--mode expanding --min-train-seasons 3"
```

---

## 두 머신 공통 — 일상 작업 명령어

```bash
# 가상환경 활성화 (매번 필요)
.venv\Scripts\activate

# 오늘 파이프라인 실행
make pipeline

# 오즈 수집
make ingest-odds

# 오늘 요약 확인
make today-summary

# 데이터 신선도 확인
make freshness-check

# 라이브 베팅 준비도 평가
make readiness

# 테스트
make test

# API 서버
make serve
```

---

## 서버 ↔ 워크스테이션 연결 구조

```
[RTX5080 워크스테이션]          [RX6600 서버]
  - 모델 학습                     - API 서버 (port 8000)
  - 백테스트                      - 파이프라인 스케줄
  - 개발/실험          ←→         - PostgreSQL DB (port 5432)
                                  - 데이터 수집 자동화
```

---

## 트러블슈팅

### `ModuleNotFoundError` 발생 시
```bash
# 가상환경이 활성화되어 있는지 확인
where python   # .venv 경로가 나와야 함
pip install -r requirements-dev.txt
```

### DB 연결 실패 시
```bash
# PostgreSQL 서비스 실행 확인
Get-Service -Name postgresql*

# 서비스 시작
Start-Service -Name postgresql-x64-16
```

### XGBoost GPU 오류 시 (RTX5080)
```bash
# CUDA 버전 확인
nvidia-smi   # CUDA Version 확인
nvcc --version

# XGBoost 재설치
pip uninstall xgboost
pip install xgboost
```

### 마이그레이션 충돌 시
```bash
# 현재 DB 버전 확인
alembic current

# 최신으로 업그레이드
alembic upgrade head
```

---

## 버전 요약

| 항목 | 버전 |
|------|------|
| Python | 3.11.x |
| FastAPI | >=0.111.0 |
| SQLAlchemy | >=2.0.0 |
| XGBoost | >=2.0 |
| scikit-learn | >=1.4.0 |
| CUDA (RTX5080) | 12.x |
