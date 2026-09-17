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


def default_allowance(store: Store, w: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, int]:
    """Pro-rata share of what is still owed, spread over the windows left in the year."""
    rem = remaining_quota(store, w, c)
    n = windows_left(w)
    return {k: int(math.ceil(v / n)) for k, v in rem.items()}


def allowance(store: Store, w: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, int]:
    """Allowance actually used: the admin's override if set, else the pro-rata default, never more than owed."""
    rem = remaining_quota(store, w, c)
    base = default_allowance(store, w, c)
    ov = (w.get("allowances") or {}).get(c["initials"]) or {}
    out = {}
    for k in ("weekday", "weekend"):
        v = ov.get(k)
        out[k] = min(rem[k], int(v) if v is not None else base[k])
    return out


def set_allowance(store: Store, wid: str, initials: str, weekday: Optional[int] = None, weekend: Optional[int] = None) -> Dict[str, Any]:
    w = store.window(wid)
    ini = R._norm(initials)
    R.get(store, ini)
    a = w.setdefault("allowances", {}).setdefault(ini, {})
    if weekday is not None:
        a["weekday"] = int(weekday)
    if weekend is not None:
        a["weekend"] = int(weekend)
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
