"""
orchestration/jobs/roles/feature_engineer.py
---------------------------------------------
Role audit: Feature Engineer.

Reports on the latest feature parquet: coverage per column, distribution
summary, correlation with the `home_win` target, and any leakage findings.
Does NOT rebuild features — that is build_features's job.

Output: storage/daily_summaries/roles/feature_engineer/{YYYY-MM-DD}.json
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import get_settings

settings = get_settings()

_last_result: dict[str, Any] | None = None


def get_last_result() -> dict[str, Any] | None:
    return _last_result


def run() -> None:
    global _last_result
    start = time.monotonic()
    today = date.today()
    logger.info("==> role:feature_engineer starting")

    parquet_path = _latest_parquet()
    if parquet_path is None:
        report = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "verdict": "no_data",
            "warnings": ["No feature parquet found under storage/raw_snapshots/features/."],
            "parquet_path": None,
        }
    else:
        df = pd.read_parquet(parquet_path)
        report = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "parquet_path": str(parquet_path),
            "parquet_mtime": datetime.fromtimestamp(parquet_path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "n_rows": int(len(df)),
            "n_cols": int(len(df.columns)),
            "columns": _column_report(df),
            "target_correlation": _target_correlation(df),
            "leakage": _leakage_summary(df),
        }
        verdict, warnings = _verdict(report)
        report["verdict"] = verdict
        report["warnings"] = warnings

    _write_artifact("feature_engineer", today, report)
    _last_result = report

    duration = time.monotonic() - start
    logger.info(f"==> role:feature_engineer {report.get('verdict','?').upper()} in {duration:.1f}s")


# ---------------------------------------------------------------------------
# Parquet discovery
# ---------------------------------------------------------------------------

def _latest_parquet() -> Path | None:
    base = Path(settings.raw_snapshots_dir) / "features"
    if not base.exists():
        return None
    candidates = sorted(base.rglob("*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Per-column report
# ---------------------------------------------------------------------------

def _column_report(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for col in df.columns:
        s = df[col]
        non_null = int(s.notna().sum())
        nn_pct = round(100 * non_null / len(df), 2) if len(df) else 0.0
        entry: dict[str, Any] = {
            "name": col,
            "dtype": str(s.dtype),
            "non_null_pct": nn_pct,
            "n_missing": int(len(df) - non_null),
        }
        if pd.api.types.is_numeric_dtype(s) and non_null > 0:
            num = s.dropna()
            entry.update({
                "min": _safe_round(num.min()),
                "p50": _safe_round(num.median()),
                "max": _safe_round(num.max()),
                "mean": _safe_round(num.mean()),
                "std": _safe_round(num.std()),
            })
        out.append(entry)
    return out


def _target_correlation(df: pd.DataFrame) -> dict[str, float]:
    if "home_win" not in df.columns:
        return {}
    target = df["home_win"]
    result: dict[str, float] = {}
    for col in df.columns:
        if col == "home_win" or not pd.api.types.is_numeric_dtype(df[col]):
            continue
        try:
            valid = df[[col, "home_win"]].dropna()
            if len(valid) < 30:
                continue
            corr = valid[col].corr(valid["home_win"])
            if corr is not None and not np.isnan(corr):
                result[col] = round(float(corr), 4)
        except Exception:
            continue
    return dict(sorted(result.items(), key=lambda kv: abs(kv[1]), reverse=True))


def _leakage_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Run the built-in validator if available; else return a stub."""
    try:
        from features.validators import validate_features  # type: ignore
    except Exception as exc:
        return {"validator_available": False, "reason": str(exc)}
    try:
        findings = validate_features(df)  # expected: list[dict] or dict
        errors = [f for f in findings if isinstance(f, dict) and f.get("severity") == "ERROR"]
        return {
            "validator_available": True,
            "n_findings": len(findings) if hasattr(findings, "__len__") else None,
            "n_errors": len(errors),
            "errors": errors[:10],
        }
    except Exception as exc:
        return {"validator_available": True, "error": f"validate_features raised: {exc}"}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _verdict(report: dict[str, Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    leakage = report.get("leakage", {})
    if leakage.get("n_errors", 0):
        warnings.append(f"{leakage['n_errors']} leakage ERROR finding(s) — stop shipping.")

    poor = [c for c in report["columns"] if c["non_null_pct"] < 50 and c["name"] != "home_win"]
    if len(poor) > 5:
        warnings.append(f"{len(poor)} columns have non-null < 50% — expected features may be unwired.")

    if leakage.get("n_errors", 0):
        return "critical", warnings
    if warnings:
        return "warn", warnings
    return "ok", warnings


def _safe_round(v: Any, ndigits: int = 4) -> Any:
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return round(float(v), ndigits)
    except Exception:
        return None


def _write_artifact(role: str, today: date, report: dict[str, Any]) -> None:
    output_dir = Path(settings.daily_summary_dir) / "roles" / role
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{today.isoformat()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"role:{role} report → {path}")


if __name__ == "__main__":
    run()
    print(json.dumps(get_last_result(), indent=2, default=str))
