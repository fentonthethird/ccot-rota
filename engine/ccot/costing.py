"""WLI costing with effective-dated rates, spend to date, projection and budget."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from . import calendar as cal
from . import years as Y
from .store import Store


def rates_sorted(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(settings.get("rates", []), key=lambda r: r["effective"])


def rate_for(settings: Dict[str, Any], d: dt.date) -> Dict[str, Any]:
    """The rate table in force on a date: the latest one whose effective date is on or before it."""
    rs = rates_sorted(settings)
    if not rs:
        raise ValueError("no rates configured")
    chosen = rs[0]
    for r in rs:
        if dt.date.fromisoformat(r["effective"]) <= d:
            chosen = r
    return chosen


def per_shift(settings: Dict[str, Any], d: dt.date, day_type: Optional[str] = None) -> float:
    """Cost of one extra shift on a date. Bank holidays use the weekend rate and length."""
    r = rate_for(settings, d)
    t = day_type or cal.day_type(d)
    key = "weekday" if t == cal.WEEKDAY else "weekend"
    return float(r[key]["hourly"]) * float(r[key]["hours"])


def shift_cost(settings: Dict[str, Any], d: dt.date, kind: str) -> float:
    """What a recorded shift adds to the WLI bill. Job plan shifts cost nothing extra and bank
    holiday shifts are paid outside the WLI bill, so only locum shifts count."""
    return per_shift(settings, d) if kind == Y.LOCUM else 0.0


def add_rate(store: Store, effective: dt.date, weekday_hourly: float, weekday_hours: float, weekend_hourly: float, weekend_hours: float) -> Dict[str, Any]:
    s = store.settings()
    s.setdefault("rates", [])
    s["rates"] = [r for r in s["rates"] if r["effective"] != effective.isoformat()]
    s["rates"].append({"effective": effective.isoformat(), "weekday": {"hourly": weekday_hourly, "hours": weekday_hours}, "weekend": {"hourly": weekend_hourly, "hours": weekend_hours}})
    s["rates"].sort(key=lambda r: r["effective"])
    store.save_settings(s)
    return s


def wli(store: Store, label: str, today: Optional[dt.date] = None) -> Dict[str, Any]:
    """Spend to date, committed spend for the whole year, a projection, and the budget position."""
    today = today or dt.date.today()
    settings = store.settings()
    y = store.year(label)
    ys, ye = cal.year_bounds(label)
    shifts = y.get("shifts", {})
    spend_to_date = committed = 0.0
    locum_by_type = {"weekday": 0, "weekend": 0}
    bh_shifts = 0
    decided = set(dt.date.fromisoformat(k) for k in shifts) | set(dt.date.fromisoformat(k) for k in y.get("unfilled", []))
    for k, s in shifts.items():
        d = dt.date.fromisoformat(k)
        c = shift_cost(settings, d, s["kind"])
        committed += c
        if d <= today:
            spend_to_date += c
        if s["kind"] == Y.LOCUM:
            locum_by_type[cal.day_type(d)] += 1
        elif s["kind"] == Y.BH:
            bh_shifts += 1
    # Projection: dates not yet decided are assumed to carry locum shifts at the same rate per
    # decided date of the same type as so far this year, costed at the rate in force on that date.
    est = 0.0
    undecided = [d for d in cal.daterange(ys, ye) if d not in decided]
    for t in ("weekday", "weekend"):
        dec_t = [d for d in decided if cal.day_type(d) == t]
        share = locum_by_type[t] / len(dec_t) if dec_t else 0.0
        for d in undecided:
            if cal.day_type(d) == t:
                est += share * per_shift(settings, d)
    projected = committed + est
    budget = (settings.get("budgets") or {}).get(label)
    out = {
        "year": label, "as_of": today.isoformat(),
        "spend_to_date": round(spend_to_date, 2), "committed": round(committed, 2), "projected": round(projected, 2),
        "locum_shifts": {"weekday": locum_by_type["weekday"], "weekend": locum_by_type["weekend"], "total": sum(locum_by_type.values())},
        "bank_holiday_shifts": bh_shifts,
        "decided_dates": len(decided), "undecided_dates": len(undecided),
        "budget": budget,
        "budget_pct": round(100.0 * projected / budget, 1) if budget else None,
        "spend_pct": round(100.0 * spend_to_date / budget, 1) if budget else None,
        "overspend": (projected > budget) if budget else None,
        "rates": rate_for(settings, today),
    }
    return out
