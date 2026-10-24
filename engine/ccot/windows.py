"""Booking windows: definition, per-consultant link tokens, personalised links, allowances."""
from __future__ import annotations

import datetime as dt
import math
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from . import calendar as cal
from . import roster as R
from . import years as Y
from .store import Store


def create(store: Store, wid: str, start: dt.date, end: dt.date, deadline: Optional[dt.date] = None, year: Optional[str] = None) -> Dict[str, Any]:
    if end < start:
        raise ValueError("end is before start")
    if (end - start).days + 1 > 511:
        raise ValueError("a window can be at most 511 days")
    if wid in store.window_ids():
        raise ValueError("window %s already exists" % wid)
    year = year or cal.job_plan_year(start)
    ys, ye = cal.year_bounds(year)
    if not (ys <= start <= ye and ys <= end <= ye):
        raise ValueError("window %s to %s is not inside job plan year %s" % (start, end, year))
    w = {
        "id": wid, "year": year, "start": start.isoformat(), "end": end.isoformat(),
        "deadline": deadline.isoformat() if deadline else None,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "open",
        "tokens": {c["initials"]: secrets.token_hex(3) for c in R.consultants(store)},
        "allowances": {}, "submissions": {}, "draft": None,
    }
    store.save_window(w)
    return w


def ensure_tokens(store: Store, w: Dict[str, Any]) -> None:
    """Consultants added after the window was created still get a token."""
    changed = False
    for c in R.consultants(store):
        if c["initials"] not in w["tokens"]:
            w["tokens"][c["initials"]] = secrets.token_hex(3)
            changed = True
    if changed:
        store.save_window(w)


def length(w: Dict[str, Any]) -> int:
    return (dt.date.fromisoformat(w["end"]) - dt.date.fromisoformat(w["start"])).days + 1


def dates(w: Dict[str, Any]) -> List[dt.date]:
    return list(cal.daterange(dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"])))


def windows_left(w: Dict[str, Any]) -> int:
    """How many windows of this size remain in the job plan year, counting this one."""
    _, ye = cal.year_bounds(w["year"])
    remaining_days = (ye - dt.date.fromisoformat(w["start"])).days + 1
    return max(1, int(round(remaining_days / length(w))))


def remaining_quota(store: Store, w: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, int]:
    """Annual job plan shifts still owed at the start of this window."""
    y = store.year(w["year"])
    qw, qe = R.quota(c, w["year"])
    done = Y.jp_done(y, c["initials"], upto=dt.date.fromisoformat(w["start"]) - dt.timedelta(days=1))
    return {"weekday": max(0, qw - done["weekday"]), "weekend": max(0, qe - done["weekend"])}


# Most job plan shifts anyone can be given within one quarter, as a percentage of their annual
# job plan (weekday + weekend days), rounded down. None = no limit: the last quarter lets everyone
# finish what they owe. Quarters run April-June (1), July-September (2), October-December (3),
# January-March (4).
QUARTER_JP_LIMIT_PCT = {1: 50, 2: 50, 3: 80, 4: None}


def quarter_jp_limit(store: Store, w: Dict[str, Any], c: Dict[str, Any]) -> Optional[int]:
    """Job plan shifts this consultant may still be given in this window's quarter, or None for no limit.
    Job plan shifts already recorded earlier in the same quarter count towards the limit."""
    start = dt.date.fromisoformat(w["start"])
    pct = QUARTER_JP_LIMIT_PCT[cal.quarter_of(start)]
    if pct is None:
        return None
    qw, qe = R.quota(c, w["year"])
    limit = (qw + qe) * pct // 100
    q_start = dt.date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    y = store.year(w["year"])
    before = start - dt.timedelta(days=1)
    done_this_quarter = 0
    if q_start <= before:
        upto_before = Y.jp_done(y, c["initials"], upto=before)
        upto_q = Y.jp_done(y, c["initials"], upto=q_start - dt.timedelta(days=1))
        done_this_quarter = sum(upto_before.values()) - sum(upto_q.values())
    return max(0, limit - done_this_quarter)


def default_allowance(store: Store, w: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, int]:
    """Job plan this consultant can be given in the window: what they still owe of each type, and in
    total no more than the quarter limit."""
    rem = remaining_quota(store, w, c)
    owed = rem["weekday"] + rem["weekend"]
    lim = quarter_jp_limit(store, w, c)
    return {"weekday": rem["weekday"], "weekend": rem["weekend"], "total": owed if lim is None else min(owed, lim)}


def allowance(store: Store, w: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, int]:
    """Allowance actually used: the default, narrowed by any admin override, never more than owed."""
    out = default_allowance(store, w, c)
    ov = (w.get("allowances") or {}).get(c["initials"]) or {}
    for k in ("weekday", "weekend"):
        if ov.get(k) is not None:
            out[k] = min(out[k], int(ov[k]))
    if ov.get("total") is not None:
        out["total"] = int(ov["total"])
    out["total"] = min(out["total"], out["weekday"] + out["weekend"])
    return out


def set_allowance(store: Store, wid: str, initials: str, weekday: Optional[int] = None, weekend: Optional[int] = None, total: Optional[int] = None) -> Dict[str, Any]:
    w = store.window(wid)
    ini = R._norm(initials)
    R.get(store, ini)
    a = w.setdefault("allowances", {}).setdefault(ini, {})
    if weekday is not None:
        a["weekday"] = int(weekday)
    if weekend is not None:
        a["weekend"] = int(weekend)
    if total is not None:
        a["total"] = int(total)
    store.save_window(w)
    return w


def link(store: Store, w: Dict[str, Any], c: Dict[str, Any]) -> str:
    s = store.settings()
    rem = remaining_quota(store, w, c)
    q = {"c": c["initials"], "k": w["tokens"][c["initials"]], "n": R.first_name(c), "w": w["id"], "s": w["start"], "e": w["end"]}
    if w.get("deadline"):
        q["d"] = w["deadline"]
    q["jw"] = rem["weekday"]
    q["je"] = rem["weekend"]
    base = s.get("site_url", "").rstrip("/") + "/"
    return base + "?" + urlencode(q)


def links(store: Store, wid: str, include_inactive: bool = False) -> List[Dict[str, str]]:
    w = store.window(wid)
    ensure_tokens(store, w)
    out = []
    for c in R.consultants(store, include_inactive=include_inactive):
        out.append({"initials": c["initials"], "name": c["name"], "active": c.get("active", True), "url": link(store, w, c)})
    return out
