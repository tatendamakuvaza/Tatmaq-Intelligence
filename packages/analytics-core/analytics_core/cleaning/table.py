"""Turning a table of raw text into typed, analysis-ready columns.

Three rules hold throughout:

* **Nothing is deleted.** Problem rows are flagged; the one exception is spreadsheet
  "TOTAL" lines, which are not records and would double-count if kept.
* **Nothing is invented.** A value that cannot be read becomes missing and is reported;
  missing values are never replaced with zero.
* **Everything is logged.** Each change is recorded with a count and before/after
  examples, and the raw table it was made from is left untouched.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import numpy as np
import pandas as pd

from ..financial.money import exceeds_float_precision
from ..statistics.outliers import EXTREME_K, iqr_bounds, outlier_mask
from .dates import EXCEL_SERIAL_MAX, EXCEL_SERIAL_MIN, excel_serial_to_datetime, parse_date_column
from .duplicates import duplicate_mask
from .numbers import (
    NUMERIC_NULL_TOKENS,
    TEXT_NULL_TOKENS,
    DecimalSeparator,
    detect_decimal_separator,
    is_canonical_number,
    is_percent_text,
    looks_like_code,
    parse_number,
)
from .text import count_of, find_variants, tidy

ColumnKind = Literal["number", "date", "text", "empty"]
Severity = Literal["info", "warning", "critical"]

ROW_COLUMN = "__row__"
DUPLICATE_COLUMN = "__duplicate__"

#: Share of values that must parse for a column with no naming hint to be typed.
STRICT_RATE = 0.95
#: Share required when the column name already says what the column holds.
LENIENT_RATE = 0.60

SUMMARY_LABELS = frozenset(
    {"total", "totals", "grand total", "grand totals", "sub total", "subtotal", "sub-total", "overall total", "sum"}
)


@dataclass(frozen=True)
class ColumnType:
    kind: ColumnKind
    integer: bool = False
    decimal_separator: DecimalSeparator = "."
    excel_serial_dates: bool = False
    percent: bool = False
    parse_rate: float = 1.0


@dataclass(frozen=True)
class LogEntry:
    step: str
    column: str | None
    rows_affected: int
    description: str
    examples: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    column: str | None
    count: int
    message: str
    rows: list[int] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CleaningOutcome:
    cleaned: pd.DataFrame
    log: list[LogEntry]
    issues: list[Issue]
    rows_in: int
    rows_out: int
    summary_rows: list[int]
    duplicate_rows: int


def _present(value: object, null_tokens: frozenset[str]) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return None if text.casefold() in null_tokens else text


def infer_column_type(
    values: Sequence[object] | pd.Series,
    *,
    expect: ColumnKind | None = None,
    default_day_first: bool = True,
) -> ColumnType:
    """Decide what a column of raw text holds.

    ``expect`` carries what the column *name* suggests ("Invoice Date", "Amount",
    "Product"). A suggestion lowers the bar from 95% to 60% of values having to parse,
    because a column called "Amount" with a few typing errors is still an amount, and
    its bad cells should be flagged rather than the whole column treated as text.
    """
    counts: Counter[str] = Counter()
    for value in values:
        text = _present(value, NUMERIC_NULL_TOKENS)
        if text is not None:
            counts[text] += 1
    total = sum(counts.values())
    if total == 0:
        return ColumnType("empty")
    if expect == "text":
        return ColumnType("text")

    number_rate_needed = LENIENT_RATE if expect == "number" else STRICT_RATE
    date_rate_needed = LENIENT_RATE if expect == "date" else STRICT_RATE

    separator = detect_decimal_separator(counts)
    numbers = {text: parse_number(text, separator) for text in counts}
    number_rate = sum(counts[text] for text, value in numbers.items() if value is not None) / total

    if expect == "date":
        serial_rows = sum(
            counts[text]
            for text, value in numbers.items()
            if value is not None and EXCEL_SERIAL_MIN <= value <= EXCEL_SERIAL_MAX
        )
        if serial_rows / total >= date_rate_needed:
            return ColumnType("date", excel_serial_dates=True, parse_rate=serial_rows / total)
    elif number_rate >= number_rate_needed:
        code_rate = sum(counts[text] for text in counts if looks_like_code(text)) / total
        if code_rate < 0.05:
            return ColumnType(
                "number",
                integer=all(v == v.to_integral_value() for v in numbers.values() if v is not None),
                decimal_separator=separator,
                percent=sum(counts[text] for text in counts if is_percent_text(text)) / total >= 0.5,
                parse_rate=number_rate,
            )

    distinct = list(counts)
    parsed = parse_date_column(distinct, default_day_first=default_day_first)
    date_rate = sum(counts[t] for t, v in zip(distinct, parsed.values, strict=True) if v is not None) / total
    if date_rate >= date_rate_needed:
        return ColumnType("date", parse_rate=date_rate)
    return ColumnType("text")


def _summary_row_mask(raw: pd.DataFrame, columns: Sequence[str], types: Mapping[str, ColumnType]) -> np.ndarray:
    """Rows such as a spreadsheet's closing "TOTAL" line.

    A row qualifies only if a cell reads exactly like a total label *and* at least half
    of its descriptive cells (text and date columns) are empty, so a product called
    "Total Body Lotion" on a normal, fully filled row is never mistaken for one.
    """
    descriptive = [c for c in columns if types[c].kind in ("text", "date")]
    if not descriptive:
        return np.zeros(len(raw), dtype=bool)
    labelled = np.zeros(len(raw), dtype=bool)
    empty_cells = np.zeros(len(raw), dtype=int)
    for column in descriptive:
        values = raw[column].tolist()
        texts = [tidy(v).casefold().rstrip(":") if isinstance(v, str) else "" for v in values]
        labelled |= np.fromiter((t in SUMMARY_LABELS for t in texts), dtype=bool, count=len(texts))
        empty_cells += np.fromiter((t == "" for t in texts), dtype=int, count=len(texts))
    return labelled & (empty_cells * 2 >= len(descriptive))


def _examples(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return items[:limit]


def _clean_number(
    name: str, values: list[object], rows: np.ndarray, ctype: ColumnType,
    log: list[LogEntry], issues: list[Issue], limit: int,
) -> pd.Series:  # fmt: skip
    out = np.full(len(values), np.nan, dtype="float64")
    cache: dict[str, Decimal | None] = {}
    tokens: list[dict[str, Any]] = []
    reformatted: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    imprecise = 0
    for position, value in enumerate(values):
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text.casefold() in NUMERIC_NULL_TOKENS:
            if text:
                tokens.append({"row": int(rows[position]), "before": text, "after": None})
            continue
        if text not in cache:
            cache[text] = parse_number(text, ctype.decimal_separator)
        number = cache[text]
        if number is None:
            invalid.append({"row": int(rows[position]), "value": text})
            continue
        out[position] = float(number)
        if not is_canonical_number(text):
            reformatted.append({"row": int(rows[position]), "before": text, "after": format(number, "f")})
        if exceeds_float_precision(number):
            imprecise += 1

    if tokens:
        log.append(LogEntry("null_tokens", name, len(tokens),
                            f"Read {count_of(len(tokens), 'placeholder')} such as 'N/A' or '-' as missing.",
                            _examples(tokens, limit)))  # fmt: skip
    if reformatted:
        log.append(LogEntry("normalise_numbers", name, len(reformatted),
                            f"Normalised the formatting of {count_of(len(reformatted), 'number')} "
                            "(thousands separators, currency symbols, brackets).",
                            _examples(reformatted, limit)))  # fmt: skip
    if invalid:
        issues.append(Issue("invalid_numbers", "warning", name, len(invalid),
                            f"{count_of(len(invalid), 'value')} in '{name}' could not be read as a number and "
                            f"{'was' if len(invalid) == 1 else 'were'} left out of calculations.",
                            [item["row"] for item in invalid[:limit]],
                            {"examples": _examples(invalid, limit)}))  # fmt: skip
    if imprecise:
        issues.append(Issue("precision", "warning", name, imprecise,
                            f"{count_of(imprecise, 'value')} in '{name}' {'has' if imprecise == 1 else 'have'} more than 15 "
                            "significant digits; totals involving them may not be exact to the cent."))  # fmt: skip
    return pd.Series(out, dtype="float64")


def _clean_date(
    name: str, values: list[object], rows: np.ndarray, ctype: ColumnType, default_day_first: bool,
    today: date, log: list[LogEntry], issues: list[Issue], limit: int,
) -> pd.Series:  # fmt: skip
    if ctype.excel_serial_dates:
        parsed: list[datetime | None] = []
        invalid_positions: list[int] = []
        for position, value in enumerate(values):
            text = _present(value, NUMERIC_NULL_TOKENS)
            if text is None:
                parsed.append(None)
                continue
            number = parse_number(text)
            stamp = excel_serial_to_datetime(float(number)) if number is not None else None
            parsed.append(stamp)
            if stamp is None:
                invalid_positions.append(position)
        converted = sum(1 for stamp in parsed if stamp is not None)
        log.append(LogEntry("convert_serial_dates", name, converted,
                            f"Converted {count_of(converted, 'spreadsheet day number')} to calendar dates."))  # fmt: skip
        format_counts: dict[str, int] = {"spreadsheet serial": converted}
        ambiguous = short_years = 0
        basis, day_first = "not_applicable", default_day_first
    else:
        result = parse_date_column(values, default_day_first=default_day_first, pivot_year=today.year)
        parsed, invalid_positions = result.values, result.invalid_positions
        format_counts, ambiguous, short_years = result.format_counts, result.ambiguous_rows, result.two_digit_year_rows
        basis, day_first = result.order_basis, result.day_first
        restyled = sum(count for label, count in format_counts.items() if label != "YYYY-MM-DD")
        if restyled:
            log.append(LogEntry("standardise_dates", name, restyled,
                                f"Standardised {count_of(restyled, 'date')} to the ISO form YYYY-MM-DD.",
                                [{"format": label, "rows": count} for label, count in format_counts.items()]))  # fmt: skip

    if len(format_counts) > 1:
        minority = sum(format_counts.values()) - max(format_counts.values())
        issues.append(Issue("inconsistent_date_formats", "warning", name, minority,
                            f"'{name}' mixes {len(format_counts)} date formats ({', '.join(format_counts)}); "
                            f"{count_of(minority, 'date')} {'is' if minority == 1 else 'are'} written differently from the rest.",
                            details={"formats": format_counts}))  # fmt: skip
    order = "day/month/year" if day_first else "month/day/year"
    if basis == "conflict":
        issues.append(Issue("date_order_conflict", "warning", name, ambiguous,
                            f"'{name}' contains both day-first and month-first dates. {count_of(ambiguous, 'date')} "
                            f"could be read either way and {'was' if ambiguous == 1 else 'were'} read as {order}.", details={"assumed_order": order}))  # fmt: skip
    elif ambiguous:
        issues.append(Issue("ambiguous_dates", "warning", name, ambiguous,
                            f"{count_of(ambiguous, 'date')} in '{name}' (such as 01/09/2026) could be read either "
                            f"way. They were read as {order}, because nothing in the column settles it.",
                            details={"assumed_order": order}))  # fmt: skip
    if invalid_positions:
        issues.append(Issue("invalid_dates", "warning", name, len(invalid_positions),
                            f"{count_of(len(invalid_positions), 'value')} in '{name}' could not be read as a date and "
                            f"{'was' if len(invalid_positions) == 1 else 'were'} left out of time-based calculations.",
                            [int(rows[p]) for p in invalid_positions[:limit]],
                            {"examples": [{"row": int(rows[p]), "value": str(values[p])}
                                          for p in invalid_positions[:limit]]}))  # fmt: skip
    if short_years:
        issues.append(Issue("two_digit_years", "info", name, short_years,
                            f"{count_of(short_years, 'date')} in '{name}' {'uses a two-digit year' if short_years == 1 else 'use two-digit years'}; "
                            "the century was inferred."))  # fmt: skip
    future = [p for p, stamp in enumerate(parsed) if stamp is not None and stamp.date() > today]
    if future:
        issues.append(Issue("future_dates", "info", name, len(future),
                            f"{count_of(len(future), 'date')} in '{name}' {'is' if len(future) == 1 else 'are'} later than today "
                            f"({today.isoformat()}).",
                            [int(rows[p]) for p in future[:limit]]))  # fmt: skip
    return pd.Series(pd.to_datetime(parsed))


def _clean_text(
    name: str, values: list[object], rows: np.ndarray, standardise: bool,
    log: list[LogEntry], issues: list[Issue], limit: int,
) -> pd.Series:  # fmt: skip
    out: list[str | None] = []
    trimmed: list[dict[str, Any]] = []
    tokens = 0
    for position, value in enumerate(values):
        if not isinstance(value, str):
            out.append(None)
            continue
        text = tidy(value)
        if text.casefold() in TEXT_NULL_TOKENS:
            tokens += bool(text)
            out.append(None)
            continue
        if text != value:
            trimmed.append({"row": int(rows[position]), "before": repr(value), "after": repr(text)})
        out.append(text)
    if trimmed:
        log.append(LogEntry("trim_whitespace", name, len(trimmed),
                            f"Removed stray spaces from {count_of(len(trimmed), 'value')}.", _examples(trimmed, limit)))  # fmt: skip
    if tokens:
        log.append(
            LogEntry("null_tokens", name, tokens, f"Read {count_of(tokens, 'placeholder')} such as 'N/A' as missing.")
        )

    if standardise:
        counts = Counter(text for text in out if text is not None)
        mapping = find_variants(counts)
        if mapping:
            affected = sum(counts[variant] for variant in mapping)
            merged = [{"before": variant, "after": canonical, "rows": counts[variant]}
                      for variant, canonical in sorted(mapping.items())]  # fmt: skip
            out = [mapping.get(text, text) if text is not None else None for text in out]
            log.append(LogEntry("standardise_categories", name, affected,
                                f"Merged {count_of(len(mapping), 'alternative spelling')} in '{name}' into the most common one.",
                                merged))  # fmt: skip
            issues.append(Issue("inconsistent_categories", "info", name, affected,
                                f"'{name}' used {count_of(len(mapping), 'alternative spelling')} for the same value "
                                f"(for example '{merged[0]['before']}' for '{merged[0]['after']}').",
                                details={"merged": merged}))  # fmt: skip
    return pd.Series(out, dtype="str")


def clean_table(
    raw: pd.DataFrame,
    types: Mapping[str, ColumnType],
    *,
    category_columns: Sequence[str] = (),
    measure_columns: Sequence[str] = (),
    default_day_first: bool = True,
    today: date | None = None,
    max_examples: int = 5,
) -> CleaningOutcome:
    """Clean a raw table. ``raw`` holds text columns plus ``__row__`` (source row numbers)."""
    today = today or date.today()
    columns = [column for column in raw.columns if column != ROW_COLUMN]
    rows_in = len(raw)
    log: list[LogEntry] = []
    issues: list[Issue] = []

    summary = _summary_row_mask(raw, columns, types)
    summary_rows = [int(row) for row in raw.loc[summary, ROW_COLUMN].tolist()]
    if summary_rows:
        log.append(LogEntry("exclude_summary_rows", None, len(summary_rows),
                            f"Set aside {count_of(len(summary_rows), 'TOTAL line')}: a total repeats the sum of the "
                            "records and would double-count if analysed.",
                            [{"row": row} for row in summary_rows[:max_examples]]))  # fmt: skip
        issues.append(Issue("summary_rows", "info", None, len(summary_rows),
                            f"{count_of(len(summary_rows), 'TOTAL line')} {'was' if len(summary_rows) == 1 else 'were'} found "
                            "among the records and set aside.",
                            summary_rows[:max_examples]))  # fmt: skip
        raw = raw.loc[~summary].reset_index(drop=True)

    rows = raw[ROW_COLUMN].to_numpy()
    cleaned: dict[str, pd.Series] = {ROW_COLUMN: raw[ROW_COLUMN].astype("int64")}
    for column in columns:
        ctype, values = types[column], raw[column].tolist()
        if ctype.kind == "number":
            cleaned[column] = _clean_number(column, values, rows, ctype, log, issues, max_examples)
        elif ctype.kind == "date":
            cleaned[column] = _clean_date(column, values, rows, ctype, default_day_first, today,
                                          log, issues, max_examples)  # fmt: skip
        else:
            cleaned[column] = _clean_text(column, values, rows, column in category_columns,
                                          log, issues, max_examples)  # fmt: skip
    frame = pd.DataFrame(cleaned)

    for column in columns:
        missing = frame[column].isna().to_numpy()
        count = int(missing.sum())
        if not count:
            continue
        if count == len(frame):
            issues.append(Issue("empty_column", "info", column, count, f"'{column}' is empty."))
            continue
        important = column in measure_columns or types[column].kind == "date"
        issues.append(Issue("missing_values", "warning" if important else "info", column, count,
                            f"'{column}' is missing in {count:,} of {len(frame):,} rows "
                            f"({count / len(frame):.1%}). Missing values are not treated as zero.",
                            [int(r) for r in rows[missing][:max_examples]],
                            {"share": round(count / len(frame), 6)}))  # fmt: skip

    duplicates = duplicate_mask(frame, columns)
    frame[DUPLICATE_COLUMN] = duplicates
    if duplicates.any():
        count = int(duplicates.sum())
        issues.append(Issue("duplicate_rows", "warning", None, count,
                            f"{count_of(count, 'row')} exactly {'repeats' if count == 1 else 'repeat'} an earlier row. "
                            "Flagged for review; they stay in the totals until someone confirms they are duplicates.",
                            [int(r) for r in rows[duplicates][:max_examples]]))  # fmt: skip

    for column in measure_columns:
        if types[column].kind != "number":
            continue
        data = frame[column].to_numpy()
        negative = np.isfinite(data) & (data < 0)
        if negative.any():
            issues.append(Issue("negative_values", "info", column, int(negative.sum()),
                                f"'{column}' has {count_of(int(negative.sum()), 'negative value')}, which may be returns, "
                                "credit notes or entry errors.",
                                [int(r) for r in rows[negative][:max_examples]]))  # fmt: skip
        bounds = iqr_bounds(data, EXTREME_K)
        if bounds is None or bounds.iqr == 0:
            continue
        extreme = outlier_mask(data, bounds)
        if extreme.any():
            order = np.argsort(-np.abs(data[extreme] - (bounds.q1 + bounds.q3) / 2))[:max_examples]
            issues.append(Issue("outliers", "info", column, int(extreme.sum()),
                                f"{count_of(int(extreme.sum()), 'value')} in '{column}' {'lies' if extreme.sum() == 1 else 'lie'} "
                                f"far outside the usual range ({bounds.lower:,.2f} to {bounds.upper:,.2f}). "
                                "Flagged for review, not removed: unusual does not mean wrong.",
                                [int(r) for r in rows[extreme][order]],
                                {"lower": bounds.lower, "upper": bounds.upper, "method": "3 x IQR",
                                 "examples": [{"row": int(r), "value": float(v)}
                                              for r, v in zip(rows[extreme][order], data[extreme][order], strict=True)]}))  # fmt: skip

    return CleaningOutcome(
        cleaned=frame,
        log=log,
        issues=issues,
        rows_in=rows_in,
        rows_out=len(frame),
        summary_rows=summary_rows,
        duplicate_rows=int(duplicates.sum()),
    )
