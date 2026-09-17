"""The rota for one job plan year: every shift, its holder, its kind, and a log of every change.

Shift kinds:
  JP      job plan shift, already paid within the job plan
  LOCUM   extra shift beyond the job plan allowance, paid as WLI
  BH      bank holiday shift: always extra, counts as locum for fairness, not in the WLI bill
Unfilled dates are listed separately.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from . import calendar as cal
from .store import Store

JP, LOCUM, BH = "JP", "LOCUM", "BH"
KINDS = (JP, LOCUM, BH)


def _iso(d: dt.date) -> str:
    return d.isoformat()


def shifts_for(year: Dict[str, Any], initials: str, upto: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    out = []
    for k, s in year.get("shifts", {}).items():
        if s.get("c") == initials and (upto is None or dt.date.fromisoformat(k) <= upto):
            out.append(dict(s, date=k))
    out.sort(key=lambda s: s["date"])
    return out


def jp_done(year: Dict[str, Any], initials: str, upto: Optional[dt.date] = None) -> Dict[str, int]:
    """Job plan shifts already recorded, split weekday and weekend."""
    out = {"weekday": 0, "weekend": 0}
    for s in shifts_for(year, initials, upto):
        if s["kind"] == JP:
            t = cal.day_type(dt.date.fromisoformat(s["date"]))
            if t in out:
                out[t] += 1
    return out


def locum_done(year: Dict[str, Any], initials: str, upto: Optional[dt.date] = None) -> Dict[str, int]:
    out = {"weekday": 0, "weekend": 0, "bh": 0, "total": 0}
    for s in shifts_for(year, initials, upto):
        if s["kind"] == LOCUM:
            out[cal.day_type(dt.date.fromisoformat(s["date"]))] += 1
            out["total"] += 1
        elif s["kind"] == BH:
            out["bh"] += 1
            out["total"] += 1
    return out


def holder(year: Dict[str, Any], d: dt.date) -> Optional[str]:
    s = year.get("shifts", {}).get(_iso(d))
    return s.get("c") if s else None


def log(year: Dict[str, Any], event: str, **fields: Any) -> None:
    entry = {"at": dt.datetime.now().isoformat(timespec="seconds"), "event": event}
    entry.update(fields)
    year.setdefault("log", []).append(entry)


def set_shift(year: Dict[str, Any], d: dt.date, initials: str, kind: str, source: str, note: Optional[str] = None) -> None:
    if kind not in KINDS:
        raise ValueError("kind must be one of %s" % ", ".join(KINDS))
    if cal.day_type(d) == cal.BH and kind != BH:
        kind = BH
    year.setdefault("shifts", {})[_iso(d)] = {"c": initials, "kind": kind, "src": source, "note": note}
    if _iso(d) in year.get("unfilled", []):
        year["unfilled"].remove(_iso(d))


def clear_shift(year: Dict[str, Any], d: dt.date, mark_unfilled: bool = True) -> Optional[Dict[str, Any]]:
    old = year.get("shifts", {}).pop(_iso(d), None)
    if mark_unfilled and _iso(d) not in year.setdefault("unfilled", []):
        year["unfilled"].append(_iso(d))
        year["unfilled"].sort()
    return old


def override(store: Store, label: str, d: dt.date, initials: Optional[str], reason: str, kind: Optional[str] = None) -> Dict[str, Any]:
    """Administrator changes who holds a date (or clears it). Logged with the reason."""
    y = store.year(label)
    old = y.get("shifts", {}).get(_iso(d))
    if initials is None:
        clear_shift(y, d)
        log(y, "override", date=_iso(d), before=old, after=None, reason=reason)
    else:
        k = kind or (old["kind"] if old and old.get("c") == initials else default_kind(store, label, d, initials))
        set_shift(y, d, initials, k, "override", note=reason)
        log(y, "override", date=_iso(d), before=old, after=y["shifts"][_iso(d)], reason=reason)
    store.save_year(y)
    return y


def swap(store: Store, label: str, d: dt.date, from_initials: str, to_initials: str, reason: str) -> Dict[str, Any]:
    """A consultant hands a published shift to a colleague. Logged; the log is published."""
    y = store.year(label)
    old = y.get("shifts", {}).get(_iso(d))
    if not old or old.get("c") != from_initials:
        raise ValueError("%s is not held by %s (held by %s)" % (_iso(d), from_initials, old.get("c") if old else "nobody"))
    kind = default_kind(store, label, d, to_initials)
    set_shift(y, d, to_initials, kind, "swap", note=reason)
    log(y, "swap", date=_iso(d), from_=from_initials, to=to_initials, kind_before=old["kind"], kind_after=kind, reason=reason)
    store.save_year(y)
    return y


def reclassify(store: Store, label: str, d: dt.date, kind: str, reason: str) -> Dict[str, Any]:
    """Mark a held shift as job plan or locum regardless of the running count, e.g. a cover arrangement."""
    y = store.year(label)
    s = y.get("shifts", {}).get(_iso(d))
    if not s:
        raise ValueError("%s is not filled" % _iso(d))
    if kind not in (JP, LOCUM):
        raise ValueError("kind must be JP or LOCUM")
    if cal.day_type(d) == cal.BH:
        raise ValueError("a bank holiday shift is always a bank holiday shift")
    before = s["kind"]
    s["kind"] = kind
    s["note"] = reason
    s["src"] = "reclassify"
    log(y, "reclassify", date=_iso(d), c=s["c"], before=before, after=kind, reason=reason)
    store.save_year(y)
    return y


def default_kind(store: Store, label: str, d: dt.date, initials: str) -> str:
    """Kind a new shift would take: bank holiday if it is one, else job plan while the annual quota is
    not yet met, else locum. Allocation applies the finer per-window allowance; this is for manual edits."""
    from . import roster as R  # local import to avoid a cycle on module load

    if cal.day_type(d) == cal.BH:
        return BH
    y = store.year(label)
    c = R.get(store, initials)
    qw, qe = R.quota(c, label)
    done = jp_done(y, initials)
    t = cal.day_type(d)
    q = qw if t == cal.WEEKDAY else qe
    return JP if done[t] < q else LOCUM


def counts(year: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Per consultant totals for the whole year file."""
    out: Dict[str, Dict[str, int]] = {}
    for k, s in year.get("shifts", {}).items():
        c = out.setdefault(s["c"], {"jp_weekday": 0, "jp_weekend": 0, "locum_weekday": 0, "locum_weekend": 0, "bh": 0, "total": 0})
        t = cal.day_type(dt.date.fromisoformat(k))
        c["total"] += 1
        if s["kind"] == BH or t == cal.BH:
            c["bh"] += 1
        elif s["kind"] == JP:
            c["jp_" + t] += 1
        else:
            c["locum_" + t] += 1
    return out
