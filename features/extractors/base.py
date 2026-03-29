"""
features/extractors/base.py
-----------------------------
Abstract base class for all per-match feature extractors.

Each extractor:
  1. Receives the full sorted list of matches (chronological order).
  2. Iterates the list once, maintaining state as it goes.
  3. Returns a dict mapping match_id → {feature_key: value}.

All extractor implementations must guarantee that the features for match M
use only information available *before* match M's match_time (no leakage).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from db.models.matches import Match


class BaseExtractor(ABC):
    """
    Contract for a single-pass, state-building feature extractor.

    Subclasses override `extract` and return a match_id keyed dict of dicts.
    """

    @abstractmethod
    def extract(self, matches: list[Match]) -> dict[int, dict]:
        """
        Compute features for every match in the provided list.

        Args:
            matches: All matches to process, sorted chronologically
                     (match_time ascending, NULLs last).

        Returns:
            Dict mapping match.id → {feature_col: value}.
            A match may be absent from the result if features cannot
            be computed for it (e.g. insufficient history). In that
            case the caller should treat all feature values as None.
        """
        ...

    @property
    def name(self) -> str:
        """Human-readable extractor name for logging."""
        return self.__class__.__name__
