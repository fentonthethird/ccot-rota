"""Dates: England and Wales bank holidays, day types, and the April to March job plan year."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, Iterator, Tuple

_BH_PATH = Path(__file__).with_name("bank_holidays_england_wales.json")
BANK_HOLIDAYS: Dict[dt.date, str] = {dt.date.fromisoformat(k): v for k, v in json.loads(_BH_PATH.read_text(encoding="utf-8")).items()}

WEEKDAY, WEEKEND, BH = "weekday", "weekend", "bh"


def is_bank_holiday(d: dt.date) -> bool:
    return d in BANK_HOLIDAYS


def day_type(d: dt.date) -> str:
    """'bh' beats 'weekend' beats 'weekday'. A bank holiday never counts towards a job plan."""
    if d in BANK_HOLIDAYS:
        return BH
    return WEEKEND if d.weekday() >= 5 else WEEKDAY


def job_plan_year(d: dt.date) -> str:
    """Label of the job plan year containing d, e.g. '2026-27' for 1 Apr 2026 to 31 Mar 2027."""
    y = d.year if d.month >= 4 else d.year - 1
    return "%d-%02d" % (y, (y + 1) % 100)


def year_bounds(label: str) -> Tuple[dt.date, dt.date]:
    y = int(label[:4])
    return dt.date(y, 4, 1), dt.date(y + 1, 3, 31)


def year_label_long(label: str) -> str:
    """Sheet name convention in the workbook: '2026-2027'."""
    y = int(label[:4])
    return "%d-%d" % (y, y + 1)


def label_from_long(name: str) -> str:
    y = int(name[:4])
    return "%d-%02d" % (y, (y + 1) % 100)


def daterange(a: dt.date, b: dt.date) -> Iterator[dt.date]:
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


def quarter_of(d: dt.date) -> int:
    """Quarter within the job plan year: Q1 = Apr to Jun ... Q4 = Jan to Mar."""
    return ((d.month - 4) % 12) // 3 + 1


def fmt(d: dt.date) -> str:
    return d.strftime("%a %d %b %Y")
