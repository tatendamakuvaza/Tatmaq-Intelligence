"""Reading Excel workbooks (.xlsx)."""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ..base import AgentError
from .raw_table import RawTable, build_raw_table, is_blank

#: A workbook that would unpack to more than this is refused before it is opened.
MAX_UNCOMPRESSED_BYTES = 1_500_000_000
MAX_COMPRESSION_RATIO = 200


def _check_archive(path: Path) -> None:
    """An .xlsx file is a zip archive. Refuse fakes and decompression bombs up front."""
    if not zipfile.is_zipfile(path):
        raise AgentError(
            "This file is not a valid Excel workbook. If it came from an older version of Excel, "
            "open it and save it again as 'Excel Workbook (.xlsx)'."
        )
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if not any(entry.filename == "xl/workbook.xml" for entry in entries):
            raise AgentError("This file is not a valid Excel workbook.")
        unpacked = sum(entry.file_size for entry in entries)
        packed = max(sum(entry.compress_size for entry in entries), 1)
        if unpacked > MAX_UNCOMPRESSED_BYTES or unpacked / packed > MAX_COMPRESSION_RATIO:
            raise AgentError("This workbook is too large to process safely.")


def _rows(sheet: Any) -> Iterator[tuple[int, list[object]]]:
    """Non-empty rows of a worksheet with their spreadsheet row numbers, one at a time."""
    for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        cells = list(row)
        while cells and is_blank(cells[-1]):
            cells.pop()
        if cells:
            yield number, cells


def read_xlsx(path: Path, *, max_rows: int, max_columns: int) -> RawTable:
    _check_archive(path)
    try:
        # read_only streams rows instead of loading the workbook into memory;
        # data_only returns the values Excel last calculated for formula cells.
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as error:  # openpyxl raises many types for damaged files
        raise AgentError("This Excel workbook could not be opened. It may be damaged or password-protected.") from error

    try:
        sheets = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"] or workbook.worksheets
        if not sheets:
            raise AgentError("This workbook has no worksheets.")
        sizes = [(sheet.max_row or 0) * (sheet.max_column or 0) for sheet in sheets]
        chosen = sheets[sizes.index(max(sizes))] if all(sizes) else sheets[0]

        log: list[str] = []
        if len(sheets) > 1:
            others = ", ".join(f"'{sheet.title}'" for sheet in sheets if sheet is not chosen)
            log.append(
                f"The workbook has {len(sheets)} worksheets. Analysed '{chosen.title}', the largest; "
                f"not analysed: {others}."
            )
        else:
            log.append(f"Read worksheet '{chosen.title}'.")
        source = {"type": "xlsx", "sheet": chosen.title, "sheets": [sheet.title for sheet in workbook.worksheets]}
        return build_raw_table(_rows(chosen), max_rows=max_rows, max_columns=max_columns, source=source, log=log)
    finally:
        workbook.close()
