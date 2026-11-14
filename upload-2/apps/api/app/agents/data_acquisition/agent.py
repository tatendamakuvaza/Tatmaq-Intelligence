"""Agent 02 - Data Acquisition.

``import_and_profile``  read an uploaded file once, when it arrives: find the table,
                        type the columns, profile them, fingerprint the file and store
                        the table exactly as imported.
``verify_and_load``     at the start of every analysis: prove the stored file is still
                        the file that was uploaded by re-computing its fingerprint.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..base import AgentError, AgentResult, AgentTask, BaseAgent, Metrics
from ..base.permissions import TOOL_ORIGINAL_READ, TOOL_RAW_WRITE
from ..base.tools import sha256_of
from .csv_reader import read_csv
from .excel_reader import read_xlsx
from .profiler import TableProfile, profile_table
from .raw_table import RawTable

PREVIEW_ROWS = 8


def _preview(table: RawTable) -> dict[str, Any]:
    head = table.frame.head(PREVIEW_ROWS)
    rows = [
        [None if not isinstance(value, str) else value[:40] for value in head[name].tolist()] for name in table.columns
    ]
    return {"columns": table.columns, "rows": [list(row) for row in zip(*rows, strict=True)]}


def _profile_json(table: RawTable, profile: TableProfile, *, size_bytes: int, sha256: str) -> dict[str, Any]:
    return {
        "file": {**table.source, "size_bytes": size_bytes, "sha256": sha256},
        # "rows" is corrected by the cleaning agent once summary lines are set aside.
        "rows_in_file": len(table.frame),
        "rows": len(table.frame),
        "columns": len(table.columns),
        "roles": profile.roles,
        "columns_detail": [column.to_json() for column in profile.columns],
        "preview": _preview(table),
        "processing_log": table.log,
    }


class DataAcquisitionAgent(BaseAgent):
    agent_key = "data_acquisition"

    async def execute(self, task: AgentTask) -> AgentResult:
        if task.action == "import_and_profile":
            return self._import_and_profile(task)
        if task.action == "verify_and_load":
            return self._verify_and_load(task)
        raise AgentError(f"The data acquisition agent has no action called '{task.action}'.")

    def _fetch(self, task: AgentTask) -> tuple[Path, int, str]:
        original: Path = self.tools.get(TOOL_ORIGINAL_READ)(task.dataset_refs["original_path"])
        size = original.stat().st_size
        if size > task.limits.max_file_bytes:
            raise AgentError("This file is larger than the upload limit.")
        return original, size, sha256_of(original)

    def _import_and_profile(self, task: AgentTask) -> AgentResult:
        started = time.monotonic()
        original, size, digest = self._fetch(task)
        file_type = task.dataset_refs["file_type"]
        reader = {"xlsx": read_xlsx, "csv": read_csv}.get(file_type)
        if reader is None:
            raise AgentError(f"'{file_type}' files are not supported.")
        table = reader(original, max_rows=task.limits.max_rows, max_columns=task.limits.max_columns)
        profile = profile_table(table, default_day_first=task.inputs.get("date_order", "DMY") == "DMY")

        self.tools.get(TOOL_RAW_WRITE)(task.dataset_refs["raw_path"], table.frame)

        rows, columns = len(table.frame), len(table.columns)
        roles = profile.roles
        recognised = ", ".join(f"{role.replace('_', ' ')}: '{name}'" for role, name in roles.items())
        warnings = list(table.warnings)
        if not roles:
            warnings.append("None of the column headings were recognised as dates, amounts, products or similar, "
                            "so only general statistics will be available for this dataset.")  # fmt: skip
        return AgentResult(
            agent_key="data_acquisition",
            status="completed",
            summary=f"Imported {rows:,} rows and {columns} columns"
                    + (f" from worksheet '{table.source['sheet']}'" if table.source.get("sheet") else "")
                    + (f". Recognised {recognised}." if recognised else "."),
            warnings=tuple(warnings),
            metrics=Metrics(execution_time_ms=int((time.monotonic() - started) * 1000), records_processed=rows),
            outputs={
                "sha256": digest,
                "size_bytes": size,
                "rows": rows,
                "columns": columns,
                "raw_path": task.dataset_refs["raw_path"],
                "profile": _profile_json(table, profile, size_bytes=size, sha256=digest),
                "schema": {"columns": [{"name": c.name, "kind": c.kind, "role": c.role} for c in profile.columns]},
                "column_types": {name: asdict(ctype) for name, ctype in profile.types.items()},
                "category_columns": profile.category_columns,
                "measure_columns": profile.measure_columns,
            },
        )  # fmt: skip

    def _verify_and_load(self, task: AgentTask) -> AgentResult:
        started = time.monotonic()
        _, size, digest = self._fetch(task)
        expected = task.dataset_refs["sha256"]
        if digest != expected:
            raise AgentError(
                "Integrity check failed: the stored file no longer matches the fingerprint recorded when it was "
                "uploaded, so it was not analysed. Upload the dataset again."
            )
        rows, columns = int(task.dataset_refs["rows"]), int(task.dataset_refs["columns"])
        return AgentResult(
            agent_key="data_acquisition",
            status="completed",
            summary=f"Verified the file against its recorded fingerprint (SHA-256 {digest[:12]}...) and loaded "
                    f"the profile: {rows:,} rows, {columns} columns.",
            metrics=Metrics(execution_time_ms=int((time.monotonic() - started) * 1000), records_processed=rows),
            outputs={"sha256": digest, "size_bytes": size, "rows": rows, "columns": columns, "verified": True},
        )  # fmt: skip
