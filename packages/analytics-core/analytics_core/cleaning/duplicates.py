"""Detecting repeated records."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def duplicate_mask(frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    """True for every row that exactly repeats an earlier row on ``columns``.

    The first occurrence is not marked: of three identical rows, two are duplicates.
    Missing values compare equal to each other. Rows that are empty on every compared
    column are never marked.
    """
    if not columns or frame.empty:
        return np.zeros(len(frame), dtype=bool)
    subset = frame[list(columns)]
    repeated = subset.duplicated(keep="first").to_numpy()
    all_missing = subset.isna().all(axis=1).to_numpy()
    return repeated & ~all_missing
