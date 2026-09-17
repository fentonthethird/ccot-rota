"""The consultant roll: names, initials, active flag and per-year job plan quotas."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .store import Store


def _norm(initials: str) -> str:
    ini = (initials or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", ini):
        raise ValueError("initials must be 1 to 3 letters, got %r" % initials)
    return ini


def consultants(store: Store, include_inactive: bool = True) -> List[Dict[str, Any]]:
    cs = store.roster().get("consultants", [])
    return [c for c in cs if include_inactive or c.get("active", True)]


def get(store: Store, initials: str) -> Dict[str, Any]:
    ini = _norm(initials)
    for c in store.roster().get("consultants", []):
        if c["initials"] == ini:
            return c
    raise KeyError("no consultant with initials %s" % ini)


def quota(c: Dict[str, Any], year: str) -> Tuple[int, int]:
    """(weekday, weekend) job plan quota for the year. Missing means 0, e.g. someone not started yet."""
    q = (c.get("quotas") or {}).get(year) or {}
    return int(q.get("weekday", 0) or 0), int(q.get("weekend", 0) or 0)


def add(store: Store, initials: str, name: str, year: Optional[str] = None, weekday: int = 0, weekend: int = 0, active: bool = True, notes: str = "") -> Dict[str, Any]:
    ini = _norm(initials)
    r = store.roster()
    if any(c["initials"] == ini for c in r["consultants"]):
        raise ValueError("%s already exists" % ini)
    c: Dict[str, Any] = {"initials": ini, "name": name.strip(), "active": bool(active), "quotas": {}, "notes": notes}
    if year:
        c["quotas"][year] = {"weekday": int(weekday), "weekend": int(weekend)}
    r["consultants"].append(c)
    store.save_roster(r)
    return c


def update(store: Store, initials: str, **fields: Any) -> Dict[str, Any]:
    ini = _norm(initials)
    r = store.roster()
    for c in r["consultants"]:
        if c["initials"] == ini:
            for k, v in fields.items():
                if v is not None:
                    c[k] = v
            store.save_roster(r)
            return c
    raise KeyError("no consultant with initials %s" % ini)


def set_quota(store: Store, initials: str, year: str, weekday: Optional[int] = None, weekend: Optional[int] = None) -> Dict[str, Any]:
    ini = _norm(initials)
    r = store.roster()
    for c in r["consultants"]:
        if c["initials"] == ini:
            q = c.setdefault("quotas", {}).setdefault(year, {"weekday": 0, "weekend": 0})
            if weekday is not None:
                q["weekday"] = int(weekday)
            if weekend is not None:
                q["weekend"] = int(weekend)
            store.save_roster(r)
            return c
    raise KeyError("no consultant with initials %s" % ini)


def remove(store: Store, initials: str) -> None:
    ini = _norm(initials)
    r = store.roster()
    before = len(r["consultants"])
    r["consultants"] = [c for c in r["consultants"] if c["initials"] != ini]
    if len(r["consultants"]) == before:
        raise KeyError("no consultant with initials %s" % ini)
    store.save_roster(r)


def first_name(c: Dict[str, Any]) -> str:
    return (c.get("name") or "").split()[0] if c.get("name") else c["initials"]
