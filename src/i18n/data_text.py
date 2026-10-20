"""Display-time choice between a long-text data column and its `_eng` translation.

Some long Spanish text columns (AI recommendations, alert messages, predictive
diagnoses) are translated offline by `scripts/translate_text_fields.py`, which
stores the English text next to the original in `<column>_eng`. The dashboard
never translates anything itself: where it renders one of those columns it asks
this module for the value to show.

* English selected and `<column>_eng` has text -> the English text.
* Anything else (Spanish selected, column missing, value empty/NaN) -> the
  original Spanish column, so a row that was not translated yet is never blank.

Only the call sites listed in documentation/general/translation_text_fields.md
use this; every other reader of these files keeps seeing the Spanish column.
"""

from __future__ import annotations

import pandas as pd

from src.i18n import current_language

ENG_SUFFIX = "_eng"


def eng_column(column: str) -> str:
    """Name of the translated twin of `column`."""
    return f"{column}{ENG_SUFFIX}"


def is_eng_column(name) -> bool:
    """True for a translation column; use it to keep `_eng` out of column scans."""
    return isinstance(name, str) and name.endswith(ENG_SUFFIX)


def _has_text(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):  # array-likes are not text
        return False
    return bool(str(value).strip())


def _english() -> bool:
    return current_language() == "en"


def localized_value(row, column: str, default=None):
    """`row[column]` (dict or Series), or its `_eng` twin when English is selected."""
    if _english():
        translated = row.get(eng_column(column))
        if _has_text(translated):
            return translated
    return row.get(column, default)


def localized_series(df: pd.DataFrame, column: str) -> pd.Series:
    """`df[column]`, with `_eng` text substituted row by row when English is selected."""
    original = df[column]
    twin = eng_column(column)
    if not _english() or twin not in df.columns:
        return original
    translated = df[twin]
    has_text = translated.notna() & (translated.astype(str).str.strip() != "")
    return translated.where(has_text, original)
