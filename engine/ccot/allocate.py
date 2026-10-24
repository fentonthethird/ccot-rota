"""Turn a window's submissions into a draft allocation, and accept a draft into the year."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from . import calendar as cal
from . import roster as R
from . import windows as W
from . import years as Y
from .solver import Problem, Result, solve
from .store import Store


def build_problem(store: Store, w: Dict[str, Any], time_limit: float = 60.0) -> Problem:
    start = dt.date.fromisoformat(w["start"])
    dates = W.dates(w)
    y = store.year(w["year"])
    # Dates already held (an override made before allocation, or an earlier import) stay as they are.
    open_dates = [d for d in dates if Y.holder(y, d) is None]
    available: Dict[str, set] = {}
    pairs: Dict[str, set] = {}
    for ini, sub in (w.get("submissions") or {}).items():
        available[ini] = {start + dt.timedelta(days=i) for i, ch in enumerate(sub["days"]) if ch == "1"} & set(open_dates)
        pairs[ini] = {start + dt.timedelta(days=i) for i in sub.get("pairs", [])}
    # Stated maximum shifts for the window. Dates in the window already held (set by override before
    # allocation) count towards it.
    max_shifts: Dict[str, int] = {}
    for ini, sub in (w.get("submissions") or {}).items():
        if sub.get("max"):
            held = sum(1 for d in dates if Y.holder(y, d) == ini)
            max_shifts[ini] = max(0, int(sub["max"]) - held)
    consultants = [c["initials"] for c in R.consultants(store) if c["initials"] in available]
    offers = {d: [c for c in consultants if d in available[c]] for d in open_dates}
    allowance: Dict[str, Dict[str, int]] = {}
    locum_ytd: Dict[str, int] = {}
    for ini in consultants:
        c = R.get(store, ini)
        a = W.allowance(store, w, c)
        allowance[ini] = a
        locum_ytd[ini] = Y.locum_done(y, ini, upto=start - dt.timedelta(days=1))["total"]
    prior = {}
    for k in range(1, 5):
        d = start - dt.timedelta(days=k)
        h = Y.holder(y, d)
        if h:
            prior[d] = h
    contract = {ini: sum(R.quota(R.get(store, ini), w["year"])) for ini in consultants}
    return Problem(dates=open_dates, consultants=consultants, available=available, pairs=pairs, max_shifts=max_shifts,
                   allowance=allowance, locum_ytd=locum_ytd, prior=prior, contract=contract, time_limit=time_limit)


def classify(result: Result, consultants: List[str]) -> Dict[dt.date, str]:
    """Chronologically, the first `jp` shifts of each type are job plan, the rest locum; bank holidays are BH."""
    kinds: Dict[dt.date, str] = {}
    for ini in consultants:
        used = {"weekday": 0, "weekend": 0}
        for d in sorted(d for d, h in result.assignment.items() if h == ini):
            t = cal.day_type(d)
            if t == cal.BH:
                kinds[d] = Y.BH
            elif used[t] < result.jp[ini][t]:
                kinds[d] = Y.JP
                used[t] += 1
            else:
                kinds[d] = Y.LOCUM
    return kinds


def run(store: Store, wid: str, time_limit: float = 60.0) -> Dict[str, Any]:
    w = store.window(wid)
    y = store.year(w["year"])
    p = build_problem(store, w, time_limit=time_limit)
    res = solve(p)
    kinds = classify(res, p.consultants)
    start = dt.date.fromisoformat(w["start"])
    dates = W.dates(w)
    # per consultant before/after
    per: Dict[str, Any] = {}
    for c in R.consultants(store):
        ini = c["initials"]
        qw, qe = R.quota(c, w["year"])
        before = Y.jp_done(y, ini, upto=start - dt.timedelta(days=1))
        lb = Y.locum_done(y, ini, upto=start - dt.timedelta(days=1))["total"]
        got = [d for d, h in res.assignment.items() if h == ini]
        jpw = res.jp.get(ini, {"weekday": 0, "weekend": 0})
        per[ini] = {
            "name": c["name"], "active": c.get("active", True), "submitted": ini in (w.get("submissions") or {}),
            "offered": len(p.available.get(ini, ())), "allocated": len(got),
            "max": ((w.get("submissions") or {}).get(ini) or {}).get("max"),
            "quota": {"weekday": qw, "weekend": qe},
            "jp_before": before, "jp_window": jpw,
            "jp_after": {t: before[t] + jpw[t] for t in ("weekday", "weekend")},
            "allowance": p.allowance.get(ini, {"weekday": 0, "weekend": 0}),
            "locum_before": lb, "locum_window": res.locum_new.get(ini, 0), "locum_after": lb + res.locum_new.get(ini, 0),
            "dates": [d.isoformat() for d in sorted(got)],
        }
    fill = {}
    for t in (cal.WEEKDAY, cal.WEEKEND, cal.BH):
        ds = [d for d in dates if cal.day_type(d) == t]
        filled = sum(1 for d in ds if res.assignment.get(d) or Y.holder(y, d))
        fill[t] = {"filled": filled, "total": len(ds)}
    stages = [{"name": s.name, "objective": s.objective, "value": s.value, "status": s.status, "optimal": s.optimal} for s in res.stages]
    satisfied = {
        "1_all_offered_dates_filled": len(res.unfillable) == sum(1 for d in p.dates if not res.offers[d]),
        "2_all_allowances_met": all(res.jp[c]["weekday"] + res.jp[c]["weekend"] >= p.allowance[c]["total"] for c in p.consultants),
        "3_all_pairs_honoured": not res.pair_violations,
        "5_no_long_runs": next((s.value == 0 for s in res.stages if s.name == "5"), True),
        "6_no_two_in_a_week": next((s.value == 0 for s in res.stages if s.name == "6"), True),
    }
    draft = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "assignment": {d.isoformat(): res.assignment[d] for d in p.dates},
        "kinds": {d.isoformat(): kinds[d] for d in p.dates if res.assignment[d]},
        "unfillable": [d.isoformat() for d in res.unfillable],
        "no_offers": [d.isoformat() for d in p.dates if not res.offers[d]],
        # offered by someone, but everyone who offered had reached the most shifts they asked for
        "held_back_by_limits": [{"date": d.isoformat(), "offered_by": res.offers[d]} for d in res.unfillable if res.offers[d]],
        "pair_violations": [{"c": c, "saturday": s.isoformat()} for c, s in res.pair_violations],
        "stages": stages,
        "satisfied": satisfied,
        "fill": fill,
        "consultants": per,
        "locum_spread": {"min": min(res.locum_total.values()) if res.locum_total else 0, "max": max(res.locum_total.values()) if res.locum_total else 0},
    }
    w["draft"] = draft
    w["status"] = "draft"
    store.save_window(w)
    return draft


def accept(store: Store, wid: str) -> Dict[str, Any]:
    """Write the draft into the year file. Dates already held are left alone."""
    w = store.window(wid)
    draft = w.get("draft")
    if not draft:
        raise ValueError("window %s has no draft; run `ccot allocate %s` first" % (wid, wid))
    y = store.year(w["year"])
    n = 0
    for k, ini in draft["assignment"].items():
        d = dt.date.fromisoformat(k)
        if Y.holder(y, d) is not None:
            continue
        if ini:
            Y.set_shift(y, d, ini, draft["kinds"][k], "allocate", note=None)
            n += 1
        elif k not in y.setdefault("unfilled", []):
            y["unfilled"].append(k)
    y["unfilled"] = sorted(set(y.get("unfilled", [])))
    if wid not in y.setdefault("allocated_windows", []):
        y["allocated_windows"].append(wid)
    Y.log(y, "allocate", window=wid, shifts=n, unfilled=len(draft["unfillable"]))
    store.save_year(y)
    w["status"] = "allocated"
    w["accepted"] = dt.datetime.now().isoformat(timespec="seconds")
    store.save_window(w)
    return y
