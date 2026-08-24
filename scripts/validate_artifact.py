"""
scripts/validate_artifact.py
-----------------------------
Validate a canonical evaluation artifact's schema and provenance.

Run in CI so a published artifact cannot silently lose the fields that make it
auditable. Checks structure and internal consistency — it does not re-run the
evaluation.

Usage:
    python -m scripts.validate_artifact examples/backtest_canonical.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from backtesting.artifacts import ARTIFACT_SCHEMA_VERSION, BacktestResult
from backtesting.calibration import expected_calibration_error

_REQUIRED_PROVENANCE = {
    "code": ("commit", "dirty"),
    "input": ("sha256", "n_rows", "schema_sha256"),
    "runtime": ("python", "packages"),
    "evaluation": ("untuned", "mode", "seasons_in_scope"),
    "models": (),
    "market": (),
}


def validate(path: Path) -> list[str]:
    """Return a list of problems; empty means the artifact is well formed."""
    problems: list[str] = []
    raw = json.loads(path.read_text())

    if raw.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        return [
            f"artifact_schema_version is {raw.get('artifact_schema_version')!r}, "
            f"expected {ARTIFACT_SCHEMA_VERSION}"
        ]

    result = BacktestResult.from_dict(raw)

    # --- provenance completeness -------------------------------------------
    prov = result.provenance
    for section, keys in _REQUIRED_PROVENANCE.items():
        if section not in prov:
            problems.append(f"provenance.{section} missing")
            continue
        for key in keys:
            if prov[section].get(key) in (None, ""):
                problems.append(f"provenance.{section}.{key} missing or empty")

    # --- calibration metrics must be named, never a bare 'ece' -------------
    for name, agg in result.aggregate_metrics.items():
        if "ece" in agg:
            problems.append(f"{name}: bare 'ece' key present; use pooled/season_weighted")
        for key in ("pooled_ece", "season_weighted_ece", "brier_score", "log_loss"):
            if key not in agg:
                problems.append(f"{name}: aggregate missing {key}")

    # --- every model must declare its calibration state (§8) ---------------
    for name in result.aggregate_metrics:
        state = prov.get("models", {}).get(name, {}).get("calibration")
        if state is None:
            problems.append(f"{name}: provenance.models.{name}.calibration not declared")

    # --- pooled ECE must be re-derivable from the embedded predictions -----
    if not result.predictions:
        problems.append("no match-level predictions: pooled metrics are not auditable")
    else:
        pred = pd.DataFrame(result.predictions)
        for name, agg in result.aggregate_metrics.items():
            rows = pred[(pred["model"] == name) & (pred["settled"])]
            if rows.empty:
                problems.append(f"{name}: no settled prediction rows")
                continue
            recomputed = expected_calibration_error(
                rows["y_true"].values, rows["y_prob"].values, n_bins=10
            )
            stored = agg.get("pooled_ece")
            if stored is None or abs(recomputed - stored) > 1e-6:
                problems.append(
                    f"{name}: pooled_ece {stored} does not match recomputation "
                    f"{recomputed:.6f} from the artifact's own rows"
                )

    # --- market proxy must not be described as a tradeable price (§12) -----
    market = prov.get("market", {})
    if market:
        if market.get("is_closing_line") is not False:
            problems.append("market.is_closing_line must be explicitly false")
        if market.get("is_tradeable_price") is not False:
            problems.append("market.is_tradeable_price must be explicitly false")

    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    path = Path(argv[0])
    if not path.exists():
        print(f"artifact not found: {path}")
        return 1

    problems = validate(path)
    if problems:
        print(f"FAIL — {len(problems)} problem(s) in {path}:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK — {path} is a well-formed, self-auditable v{ARTIFACT_SCHEMA_VERSION} artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
