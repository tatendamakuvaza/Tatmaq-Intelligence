from datetime import date

import numpy as np
import pandas as pd

from analytics_core.cleaning import DUPLICATE_COLUMN, ROW_COLUMN, clean_table, find_variants, infer_column_type


def raw_table(columns: dict[str, list]) -> pd.DataFrame:
    length = len(next(iter(columns.values())))
    frame = pd.DataFrame({name: pd.Series(values, dtype="str") for name, values in columns.items()})
    frame.insert(0, ROW_COLUMN, np.arange(2, length + 2))
    return frame


def test_type_inference():
    assert infer_column_type(["10,000", "$45.50", "(30)", None]).kind == "number"
    assert infer_column_type(["3", "4", "12"]).integer is True
    assert infer_column_type(["01/09/2026", "2026-09-02", "3 Sep 2026"]).kind == "date"
    assert infer_column_type(["00123", "00456", "07712"]).kind == "text"  # codes keep their zeros
    assert infer_column_type(["Harare", "Bulawayo"]).kind == "text"
    assert infer_column_type([None, "", "N/A"]).kind == "empty"
    assert infer_column_type(["1 234,56", "12,5"]).decimal_separator == ","


def test_a_column_name_hint_tolerates_dirty_cells():
    mostly_numbers = ["10", "20", "30", "40", "50", "60", "70", "80", "ninety", "tbc"]
    assert infer_column_type(mostly_numbers).kind == "text"  # 80% parse: not enough on its own
    assert infer_column_type(mostly_numbers, expect="number").kind == "number"
    assert infer_column_type(["46000", "46001"], expect="date").excel_serial_dates is True
    assert infer_column_type(["46000", "46001"]).kind == "number"
    assert infer_column_type(["1001", "1002"], expect="text").kind == "text"


def test_category_variants_pick_the_commonest_spelling():
    counts = {"Harare CBD": 10, "harare cbd": 3, "HARARE CBD": 2, "Bulawayo": 5}
    assert find_variants(counts) == {"harare cbd": "Harare CBD", "HARARE CBD": "Harare CBD"}
    assert find_variants({"harare": 2, "Harare": 2}) == {"harare": "Harare"}  # tie goes to mixed case
    assert find_variants({"Gweru": 4, "Mutare": 1}) == {}


def build_dirty_table() -> pd.DataFrame:
    return raw_table(
        {
            "Date": ["2026-03-01", "15/03/2026", "15-03-2026", "2026-03-01", "not a date", None, None],
            "Branch": ["Harare CBD", "harare cbd ", "Harare CBD", "Harare CBD", "Mutare", "Mutare", None],
            "Qty": ["2", None, "5", "2", "x", "1", None],
            "Amount": ["10,000", "$45.50", "(30)", "10,000", "12", "N/A", "10057.50"],
            "Note": ["ok", "ok", "ok", "ok", "ok", "ok", "TOTAL"],
        }
    )


def clean_dirty_table():
    raw = build_dirty_table()
    types = {
        "Date": infer_column_type(raw["Date"], expect="date"),
        "Branch": infer_column_type(raw["Branch"], expect="text"),
        "Qty": infer_column_type(raw["Qty"], expect="number"),
        "Amount": infer_column_type(raw["Amount"], expect="number"),
        "Note": infer_column_type(raw["Note"]),
    }
    outcome = clean_table(raw, types, category_columns=["Branch"], measure_columns=["Qty", "Amount"],
                          today=date(2026, 11, 11))  # fmt: skip
    return raw, outcome


def test_cleaning_standardises_values_and_keeps_every_record():
    _, outcome = clean_dirty_table()
    cleaned = outcome.cleaned

    # the TOTAL line is the only row left out, and it is reported
    assert (outcome.rows_in, outcome.rows_out, outcome.summary_rows) == (7, 6, [8])
    assert cleaned[ROW_COLUMN].tolist() == [2, 3, 4, 5, 6, 7]

    assert cleaned["Amount"].tolist()[:5] == [10000.0, 45.5, -30.0, 10000.0, 12.0]
    assert cleaned["Date"].dt.strftime("%Y-%m-%d").tolist()[:4] == [
        "2026-03-01",
        "2026-03-15",
        "2026-03-15",
        "2026-03-01",
    ]
    assert cleaned["Branch"].tolist()[:3] == ["Harare CBD", "Harare CBD", "Harare CBD"]


def test_unreadable_and_missing_values_stay_missing_never_zero():
    _, outcome = clean_dirty_table()
    cleaned = outcome.cleaned
    assert np.isnan(cleaned["Qty"].iloc[1]) and np.isnan(cleaned["Qty"].iloc[4])  # blank, then "x"
    assert np.isnan(cleaned["Amount"].iloc[5])  # "N/A"
    assert pd.isna(cleaned["Date"].iloc[4])  # "not a date"
    assert not (cleaned["Qty"] == 0).any() and not (cleaned["Amount"] == 0).any()


def test_duplicates_are_flagged_and_kept():
    _, outcome = clean_dirty_table()
    assert outcome.duplicate_rows == 1
    assert outcome.cleaned[DUPLICATE_COLUMN].tolist() == [False, False, False, True, False, False]


def test_every_change_is_logged_and_every_problem_reported():
    _, outcome = clean_dirty_table()
    steps = {(entry.step, entry.column): entry for entry in outcome.log}
    assert steps[("normalise_numbers", "Amount")].rows_affected == 4
    assert steps[("normalise_numbers", "Amount")].examples[0] == {"row": 2, "before": "10,000", "after": "10000"}
    assert steps[("standardise_dates", "Date")].rows_affected == 2
    assert steps[("standardise_categories", "Branch")].examples == [
        {"before": "harare cbd", "after": "Harare CBD", "rows": 1}
    ]
    assert steps[("trim_whitespace", "Branch")].rows_affected == 1
    assert steps[("exclude_summary_rows", None)].rows_affected == 1

    issues = {(issue.code, issue.column): issue for issue in outcome.issues}
    assert issues[("invalid_numbers", "Qty")].rows == [6]
    assert issues[("invalid_dates", "Date")].count == 1
    assert issues[("inconsistent_date_formats", "Date")].details["formats"] == {
        "YYYY-MM-DD": 2, "DD/MM/YYYY": 1, "DD-MM-YYYY": 1}  # fmt: skip
    assert issues[("missing_values", "Qty")].count == 2  # one blank cell, one unreadable
    assert issues[("duplicate_rows", None)].rows == [5]
    assert issues[("negative_values", "Amount")].count == 1
    assert ("ambiguous_dates", "Date") not in issues  # 15/03 can only be day-first


def test_the_raw_table_is_never_modified():
    raw = build_dirty_table()
    snapshot = raw.copy(deep=True)
    types = {name: infer_column_type(raw[name]) for name in raw.columns if name != ROW_COLUMN}
    clean_table(raw, types, category_columns=["Branch"], measure_columns=["Amount"])
    pd.testing.assert_frame_equal(raw, snapshot)


def test_a_product_called_total_on_a_full_row_is_not_a_summary_line():
    raw = raw_table({"Product": ["Total", "Soap"], "Region": ["Harare", "Gweru"], "Amount": ["5", "6"]})
    types = {name: infer_column_type(raw[name]) for name in ("Product", "Region", "Amount")}
    outcome = clean_table(raw, types)
    assert outcome.summary_rows == [] and outcome.rows_out == 2


def test_extreme_values_are_flagged_for_review_and_left_in_place():
    amounts = [str(v) for v in [10, 11, 12, 11, 10, 12, 11, 10, 12, 11, 5000]]
    raw = raw_table({"Amount": amounts})
    outcome = clean_table(raw, {"Amount": infer_column_type(raw["Amount"])}, measure_columns=["Amount"])
    issue = next(issue for issue in outcome.issues if issue.code == "outliers")
    assert issue.rows == [12] and issue.details["method"] == "3 x IQR"
    assert outcome.cleaned["Amount"].max() == 5000.0
