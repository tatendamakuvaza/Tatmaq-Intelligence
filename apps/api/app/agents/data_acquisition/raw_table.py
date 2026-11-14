"""The common shape both file readers produce, and header-row detection.

Every cell becomes text (or missing). Typing is deliberately left to later stages so
that exactly what was in the file is preserved in the stored raw table, and each
row keeps the number it had in the source file so problems can be pointed at.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from itertools import chain, islice
from statistics import median
from typing import Any

import pandas as pd

from analytics_core.cleaning import ROW_COLUMN, parse_date_column, parse_number, tidy

from ..base import AgentError

HEADER_SEARCH_ROWS = 30
#: Rows packed into compact column storage at a time while a file is being read.
CHUNK_ROWS = 50_000
MAX_COLUMN_NAME = 120
RESERVED_PREFIX = "__"


@dataclass
class RawTable:
    frame: pd.DataFrame  # __row__ plus one text column per source column
    columns: list[str]
    source: dict[str, Any] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def cell_text(value: object) -> str | None:
    """A cell as text, written so that it reads back as the same value."""
    if is_blank(value):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep="T", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    return str(value)


def _is_label(value: object) -> bool:
    """Header cells are words: text that is neither a number nor a date."""
    if not isinstance(value, str) or not value.strip():
        return False
    return parse_number(value) is None and parse_date_column([value]).values[0] is None


def find_header_row(rows: list[tuple[int, list[object]]]) -> int | None:
    """Index of the header row among ``rows``, or ``None`` if the data has no header.

    Spreadsheets often begin with a title and a blank line. The header is the first
    row that is made of labels and is about as wide as the rows beneath it.
    """
    widest = max((len(cells) for _, cells in rows[: HEADER_SEARCH_ROWS + 10]), default=0)
    for index, (_, cells) in enumerate(rows[:HEADER_SEARCH_ROWS]):
        filled = [cell for cell in cells if not is_blank(cell)]
        if not filled or (len(filled) < 2 and widest > 1):
            continue  # a title line
        all_labels = sum(_is_label(cell) for cell in filled) / len(filled) >= 0.8
        following = rows[index + 1 : index + 11]
        if not following:
            # The last line of the file. If it reads like headings, the file has headings and no data.
            return index if all_labels else None
        typical_width = median(sum(not is_blank(cell) for cell in row) for _, row in following)
        if all_labels and len(filled) >= 0.6 * typical_width:
            return index
    return None


def _column_names(header: list[object], width: int) -> list[str]:
    names: list[str] = []
    seen: dict[str, int] = {}
    for position in range(width):
        value = header[position] if position < len(header) else None
        name = tidy(str(value))[:MAX_COLUMN_NAME] if not is_blank(value) else f"Column {position + 1}"
        if name.startswith(RESERVED_PREFIX):
            name = f"col {name}"
        key = name.casefold()
        seen[key] = seen.get(key, 0) + 1
        names.append(name if seen[key] == 1 else f"{name} ({seen[key]})")
    return names


def _chunk(names: list[str], numbers: list[int], columns: dict[str, list[str | None]]) -> pd.DataFrame:
    frame = pd.DataFrame({name: pd.Series(columns[name], dtype="str") for name in names})
    frame.insert(0, ROW_COLUMN, numbers)
    return frame


def build_raw_table(
    rows: Iterable[tuple[int, list[object]]],
    *,
    max_rows: int,
    max_columns: int,
    source: dict[str, Any],
    log: list[str],
) -> RawTable:
    """Turn non-empty source rows (with their row numbers) into a raw table.

    ``rows`` is consumed as a stream. Only the first few dozen rows are held to find the
    header; the rest are packed into compact column chunks every ``CHUNK_ROWS`` rows, so
    memory grows with the size of the table rather than with several copies of it.
    The row limit is enforced while reading: an oversized file stops early.
    """
    stream = iter(rows)
    head = list(islice(stream, HEADER_SEARCH_ROWS + 10))
    if not head:
        raise AgentError("The file contains no data.")
    warnings: list[str] = []
    header_index = find_header_row(head)
    if header_index is None:
        names = _column_names([], max(len(cells) for _, cells in head))
        first_data = 0
        warnings.append("No header row was found, so columns were named 'Column 1', 'Column 2' and so on.")
        source["header_row"] = None
    else:
        header_number, header = head[header_index]
        first_data = header_index + 1
        names = _column_names(header, max([len(header)] + [len(cells) for _, cells in head[first_data:]]))
        source["header_row"] = header_number
        if header_index:
            log.append(
                f"Skipped {header_index} line{'' if header_index == 1 else 's'} above the header (titles or notes)."
            )
        log.append(f"Header found on row {header_number}.")

    def check_width(width: int) -> None:
        if width > max_columns:
            raise AgentError(f"This dataset has {width} columns; the limit is {max_columns}.")

    check_width(len(names))
    chunks: list[pd.DataFrame] = []
    numbers: list[int] = []
    columns: dict[str, list[str | None]] = {name: [] for name in names}
    for total, (number, cells) in enumerate(chain(head[first_data:], stream), start=1):
        if total > max_rows:
            raise AgentError(
                f"This dataset has more than {max_rows:,} rows, which is over the current limit. "
                "Split it into smaller files, for example one per year."
            )
        if len(cells) > len(names):  # a row wider than the header: give the extra cells columns of their own
            check_width(len(cells))
            if numbers:
                chunks.append(_chunk(names, numbers, columns))
            names = names + _column_names([], len(cells))[len(names) :]
            numbers, columns = [], {name: [] for name in names}
        for position, name in enumerate(names):
            columns[name].append(cell_text(cells[position]) if position < len(cells) else None)
        numbers.append(number)
        if len(numbers) >= CHUNK_ROWS:
            chunks.append(_chunk(names, numbers, columns))
            numbers, columns = [], {name: [] for name in names}
    if numbers:
        chunks.append(_chunk(names, numbers, columns))
    if not chunks:
        raise AgentError("The file has column headings but no rows of data beneath them.")

    frame = chunks[0] if len(chunks) == 1 else pd.concat(chunks, ignore_index=True)
    for name in names:  # columns that only appear in later chunks come back untyped: make them text again
        if frame[name].dtype != chunks[-1][name].dtype:
            frame[name] = frame[name].astype("str")
    return RawTable(frame=frame[[ROW_COLUMN, *names]], columns=names, source=source, log=log, warnings=warnings)
