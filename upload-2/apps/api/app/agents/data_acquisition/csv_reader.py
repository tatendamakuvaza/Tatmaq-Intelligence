"""Reading delimited text files (.csv)."""

from __future__ import annotations

import codecs
import csv
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from ..base import AgentError
from .raw_table import RawTable, build_raw_table, is_blank

DELIMITERS = (",", ";", "\t", "|")
DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}


SAMPLE_BYTES = 256 * 1024


def detect_encoding(sample: bytes) -> str:
    """The text encoding of a file, judged from its first bytes."""
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if b"\x00" in sample[:8192]:
        raise AgentError("This does not look like a text file. Upload a .csv file or an Excel workbook (.xlsx).")
    try:
        # final=False: a multi-byte character cut in half at the end of the sample is not an error
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def detect_delimiter(sample: str) -> str:
    """The separator that splits the first lines into the most consistent number of fields."""
    lines = [line for line in sample.splitlines() if line.strip()][:30]
    best, best_score = ",", (0.0, 0)
    for delimiter in DELIMITERS:
        try:
            widths = [len(row) for row in csv.reader(lines, delimiter=delimiter)]
        except csv.Error:
            continue
        width, frequency = Counter(widths).most_common(1)[0] if widths else (1, 0)
        if width < 2:
            continue
        score = (frequency / len(widths), width)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _rows(handle: TextIO, delimiter: str) -> Iterator[tuple[int, list[object]]]:
    """Non-empty lines of a CSV file with their line numbers, one at a time."""
    reader = csv.reader(handle, delimiter=delimiter)
    try:
        for cells in reader:
            values: list[object] = list(cells)
            while values and is_blank(values[-1]):
                values.pop()
            if values:
                yield reader.line_num, values
    except csv.Error as error:
        raise AgentError(f"This file could not be read as CSV (line {reader.line_num}: {error}).") from error


def _read(path: Path, encoding: str, delimiter: str, max_rows: int, max_columns: int) -> RawTable:
    label = {"utf-8-sig": "utf-8", "cp1252": "windows-1252"}.get(encoding, encoding)
    log = [f"Read as {label} text with {DELIMITER_NAMES[delimiter]}-separated values."]
    source = {"type": "csv", "encoding": label, "delimiter": DELIMITER_NAMES[delimiter]}
    # The file is read as a stream: it is never held in memory as one block of text.
    errors = "replace" if encoding == "cp1252" else "strict"
    with path.open("r", encoding=encoding, errors=errors, newline="") as handle:
        table = build_raw_table(
            _rows(handle, delimiter), max_rows=max_rows, max_columns=max_columns, source=source, log=log
        )
    if encoding == "cp1252":
        table.warnings.append(
            "The file is not saved as UTF-8; it was read as Windows-1252. "
            "Check that accented characters and currency symbols look right."
        )
    return table


def read_csv(path: Path, *, max_rows: int, max_columns: int) -> RawTable:
    with path.open("rb") as handle:
        sample = handle.read(SAMPLE_BYTES)
    encoding = detect_encoding(sample)
    delimiter = detect_delimiter(sample.decode(encoding, errors="ignore")[:50_000])
    try:
        return _read(path, encoding, delimiter, max_rows, max_columns)
    except UnicodeDecodeError:
        # Valid UTF-8 at the start but not throughout: read the whole file as Windows-1252 instead.
        return _read(path, "cp1252", delimiter, max_rows, max_columns)
