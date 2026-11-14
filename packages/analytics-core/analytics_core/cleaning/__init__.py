"""Parsing and standardising raw data without deleting or inventing anything."""

from .dates import DateColumnResult, parse_date_column
from .duplicates import duplicate_mask
from .numbers import (
    NUMERIC_NULL_TOKENS,
    TEXT_NULL_TOKENS,
    detect_decimal_separator,
    parse_number,
)
from .table import (
    DUPLICATE_COLUMN,
    ROW_COLUMN,
    CleaningOutcome,
    ColumnKind,
    ColumnType,
    Issue,
    LogEntry,
    clean_table,
    infer_column_type,
)
from .text import category_key, find_variants, tidy

__all__ = [
    "DUPLICATE_COLUMN",
    "NUMERIC_NULL_TOKENS",
    "ROW_COLUMN",
    "TEXT_NULL_TOKENS",
    "CleaningOutcome",
    "ColumnKind",
    "ColumnType",
    "DateColumnResult",
    "Issue",
    "LogEntry",
    "category_key",
    "clean_table",
    "detect_decimal_separator",
    "duplicate_mask",
    "find_variants",
    "infer_column_type",
    "parse_date_column",
    "parse_number",
    "tidy",
]
