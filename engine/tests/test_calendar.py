import datetime as dt
import json
import re

from ccot import calendar as cal
from conftest import DOCS


def test_bank_holidays_match_the_app_copy():
    js = (DOCS / "calendar.js").read_text(encoding="utf-8")
    body = js[js.index("{"): js.rindex("}") + 1]
    app = json.loads(body)
    assert {d.isoformat(): n for d, n in cal.BANK_HOLIDAYS.items()} == app


def test_known_england_and_wales_dates():
    for iso in ("2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25", "2026-08-31", "2026-12-25", "2026-12-28", "2027-01-01", "2027-03-26", "2027-03-29"):
        assert cal.day_type(dt.date.fromisoformat(iso)) == cal.BH, iso
    assert cal.day_type(dt.date(2026, 12, 26)) == cal.WEEKEND  # Boxing Day falls on a Saturday; the substitute is the Monday
    assert cal.day_type(dt.date(2027, 1, 4)) == cal.WEEKDAY
    assert 2024 <= min(cal.BANK_HOLIDAYS).year and max(cal.BANK_HOLIDAYS).year >= 2030


def test_job_plan_year_labels():
    assert cal.job_plan_year(dt.date(2026, 4, 1)) == "2026-27"
    assert cal.job_plan_year(dt.date(2027, 3, 31)) == "2026-27"
    assert cal.job_plan_year(dt.date(2027, 4, 1)) == "2027-28"
    assert cal.year_bounds("2026-27") == (dt.date(2026, 4, 1), dt.date(2027, 3, 31))
    assert cal.year_label_long("2026-27") == "2026-2027" and cal.label_from_long("2026-2027") == "2026-27"
    assert [cal.quarter_of(dt.date(2026, m, 15)) for m in (4, 7, 10)] == [1, 2, 3] and cal.quarter_of(dt.date(2027, 2, 1)) == 4
