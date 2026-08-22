"""
backtesting/provenance.py
--------------------------
Reproducibility manifest for canonical evaluation artifacts.

A published metric is only auditable if you can tell what produced it. This
module captures the code, input, runtime and evaluation state of a backtest run
so a reader can answer three questions from the artifact alone:

  1. Was the tree clean, and at which commit?
  2. Was the input the canonical dataset, byte for byte?
  3. Would this environment be expected to reproduce the numbers?

Deliberately excluded: machine-specific absolute paths as primary identifiers.
The input is identified by its SHA-256, row count and schema hash; the path is
recorded only as a secondary hint.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

# Packages whose version can move a metric. Recorded on every run.
_CRITICAL_PACKAGES = (
    "scikit-learn",
    "xgboost",
    "statsmodels",
    "pandas",
    "numpy",
    "scipy",
)

_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """Stream a SHA-256 so large parquet inputs do not need to fit in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_hash(columns: list[str]) -> str:
    """Stable hash of the column set, order-independent.

    Column *order* is an implementation detail of the writer; column
    *membership* is the contract a model is trained against.
    """
    joined = "\n".join(sorted(columns))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False, timeout=10
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        return None


def code_provenance() -> dict[str, Any]:
    """Commit SHA plus whether the tree carried uncommitted changes.

    `dirty=True` means the artifact cannot be tied to a published commit, which
    is the difference between "reproducible" and "reproducible in principle".
    """
    sha = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    return {
        "commit": sha,
        "branch": branch,
        "dirty": bool(status) if status is not None else None,
        "dirty_file_count": len(status.splitlines()) if status else 0,
    }


def runtime_provenance() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for pkg in _CRITICAL_PACKAGES:
        try:
            versions[pkg] = version(pkg)
        except PackageNotFoundError:  # pragma: no cover - env dependent
            versions[pkg] = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": versions,
    }


def input_provenance(path: Path, n_rows: int, columns: list[str]) -> dict[str, Any]:
    """Identify the evaluation input by content, not by location."""
    return {
        "logical_id": path.name,
        "path_hint": str(path),
        "sha256": sha256_file(path),
        "n_rows": int(n_rows),
        "n_columns": len(columns),
        "schema_sha256": schema_hash(columns),
    }


def build_manifest(
    *,
    input_path: Path,
    n_rows: int,
    columns: list[str],
    cli_args: list[str],
    evaluation: dict[str, Any],
    models: dict[str, Any],
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the full reproducibility manifest for an artifact."""
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "code": code_provenance(),
        "input": input_provenance(input_path, n_rows, columns),
        "runtime": runtime_provenance(),
        "invocation": {"argv": cli_args},
        "evaluation": evaluation,
        "models": models,
        "market": market or {},
    }
