import datetime as dt

from ccot import costing
from ccot import years as Y
from conftest import D


def settings_two_rates():
    return {"rates": [
        {"effective": "2024-04-01", "weekday": {"hourly": 125, "hours": 12}, "weekend": {"hourly": 150, "hours": 10}},
        {"effective": "2026-10-01", "weekday": {"hourly": 130, "hours": 12}, "weekend": {"hourly": 160, "hours": 10}},
    ], "budgets": {}}


def test_rates_are_effective_dated_not_retrospective():
    s = settings_two_rates()
    assert costing.shift_cost(s, D("2026-09-30"), Y.LOCUM) == 1500.0
    assert costing.shift_cost(s, D("2026-10-01"), Y.LOCUM) == 1560.0
    assert costing.shift_cost(s, D("2026-10-03"), Y.LOCUM) == 1600.0     # Saturday
    assert costing.shift_cost(s, D("2026-12-28"), Y.BH) == 0.0           # bank holidays sit outside the WLI bill
    assert costing.shift_cost(s, D("2026-12-28"), Y.LOCUM) == 1600.0     # but would cost the weekend rate if ever billed
    assert costing.shift_cost(s, D("2026-10-01"), Y.JP) == 0.0
    assert costing.rate_for(s, D("2020-01-01"))["effective"] == "2024-04-01"  # before the first rate: use the first


def test_historic_bills_match_the_workbook():
    s = settings_two_rates()
    for shifts, bill, year in ((112, 168000, 2023), (133, 199500, 2024), (132, 198000, 2025)):
        wd = costing.per_shift(s, dt.date(year, 6, 1))
        we = costing.per_shift(s, dt.date(year, 6, 6))
        assert wd == we == 1500.0
        assert shifts * wd == bill


def test_wli_summary_with_budget(store):
    s = store.settings()
    s["budgets"]["2026-27"] = 60000
    store.save_settings(s)
    y = store.year("2026-27")
    Y.set_shift(y, D("2026-04-06"), "AW", Y.BH, "import")      # Easter Monday, not billed
    Y.set_shift(y, D("2026-04-07"), "AW", Y.JP, "import")
    Y.set_shift(y, D("2026-04-08"), "AW", Y.LOCUM, "import")
    Y.set_shift(y, D("2026-04-11"), "XW", Y.LOCUM, "import")   # Saturday
    Y.set_shift(y, D("2026-04-13"), "XW", Y.LOCUM, "import")   # future relative to today below
    y["unfilled"] = ["2026-04-09", "2026-04-10", "2026-04-12"]
    store.save_year(y)
    w = costing.wli(store, "2026-27", today=D("2026-04-12"))
    assert w["spend_to_date"] == 3000.0 and w["committed"] == 4500.0
    assert w["locum_shifts"] == {"weekday": 2, "weekend": 1, "total": 3} and w["bank_holiday_shifts"] == 1
    assert w["decided_dates"] == 8 and w["undecided_dates"] == 365 - 8
    assert w["projected"] > w["committed"]
    assert w["budget"] == 60000 and w["overspend"] is True and w["spend_pct"] == 5.0
