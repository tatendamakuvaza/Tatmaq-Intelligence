from decimal import Decimal as D

from analytics_core.validation import close_to_float, identity, parts_equal_total, rows_balance, within


def test_reconciliation_checks():
    assert parts_equal_total("months", [D("0.1"), D("0.2")], D("0.3")).passed
    assert not parts_equal_total("months", [D("0.1"), D("0.2")], D("0.31")).passed
    assert identity("profit", D("35000"), D("100000") - D("65000")).passed
    assert rows_balance("rows", 95, 5, 100).passed and not rows_balance("rows", 95, 4, 100).passed
    assert close_to_float("total", D("680.64"), 680.6400000000001).passed
    assert not close_to_float("total", D("680.64"), 690.64).passed
    assert within("margin", D("35"), None, D("100")).passed
    assert not within("margin", D("135"), None, D("100")).passed
    assert within("margin", None, None, D("100")).passed
