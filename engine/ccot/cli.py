"""ccot: the administrator's command line. Run `ccot -h` for the list of commands."""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import allocate, costing, dashboard, importer
from . import calendar as cal
from . import roster as R
from . import windows as W
from . import xlsx_export, xlsx_import
from . import years as Y
from .store import Store

REPO = Path(__file__).resolve().parents[2]


def _date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("dates are written YYYY-MM-DD, got %r" % s)


def _table(rows: List[List[Any]], head: List[str]) -> str:
    rows = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(head)]
    line = lambda r: "  ".join(v.ljust(widths[i]) for i, v in enumerate(r)).rstrip()
    return "\n".join([line(head), line(["-" * w for w in widths])] + [line(r) for r in rows])


def _limit(v) -> str:
    return "no limit" if not v else "at most %d shifts" % v


def _current_year() -> str:
    return cal.job_plan_year(dt.date.today())


# ---------------------------------------------------------------- commands
def cmd_init(a, st: Store):
    st.init()
    print("data folder: %s" % st.root)
    if a.from_workbook:
        rep = xlsx_import.import_workbook(st, a.from_workbook, a.year)
        print("imported %d consultants and %d shifts for %s; %d unfilled dates; history for %s" % (
            rep["consultants"], rep["shifts"], a.year, len(rep["unfilled"]), ", ".join(rep["history_years"]) or "no years"))
        _print_anomalies(rep["anomalies"])
    print("next: `ccot settings site-url https://YOUR-USER.github.io/ccot-rota/`")


def _print_anomalies(items: List[str]):
    if not items:
        print("no anomalies found")
        return
    print("\n%d things to check (fix with `ccot override`, `ccot kind` or `ccot roster quota`):" % len(items))
    for s in items:
        print("  - " + s)


def cmd_import_workbook(a, st: Store):
    rep = xlsx_import.import_workbook(st, a.path, a.year, replace_shifts=a.replace)
    print("imported %d consultants and %d shifts for %s; %d unfilled dates" % (rep["consultants"], rep["shifts"], a.year, len(rep["unfilled"])))
    _print_anomalies(rep["anomalies"])


def cmd_roster(a, st: Store):
    year = a.year or _current_year()
    if a.action == "list":
        rows = []
        y = st.year(year)
        for c in R.consultants(st):
            qw, qe = R.quota(c, year)
            done = Y.jp_done(y, c["initials"])
            loc = Y.locum_done(y, c["initials"])
            rows.append([c["initials"], c["name"], "yes" if c.get("active", True) else "no", "%d/%d" % (done["weekday"], qw), "%d/%d" % (done["weekend"], qe), loc["total"], c.get("notes") or ""])
        print("job plan year %s" % year)
        print(_table(rows, ["ini", "name", "active", "JP weekday", "JP weekend", "locum", "notes"]))
    elif a.action == "add":
        R.add(st, a.initials, a.name, year=year, weekday=a.weekday or 0, weekend=a.weekend or 0)
        print("added %s (%s) with quota %d/%d for %s" % (a.initials.upper(), a.name, a.weekday or 0, a.weekend or 0, year))
    elif a.action == "quota":
        c = R.set_quota(st, a.initials, year, a.weekday, a.weekend)
        print("%s quota for %s: %s" % (c["initials"], year, c["quotas"][year]))
    elif a.action in ("activate", "deactivate"):
        R.update(st, a.initials, active=(a.action == "activate"))
        print("%s is now %s" % (a.initials.upper(), "active" if a.action == "activate" else "inactive"))
    elif a.action == "remove":
        R.remove(st, a.initials)
        print("removed %s from the roster (their recorded shifts are kept)" % a.initials.upper())
    elif a.action == "rename":
        R.update(st, a.initials, name=a.name)
        print("renamed")
    elif a.action == "note":
        R.update(st, a.initials, notes=a.name)
        print("note saved")


def cmd_settings(a, st: Store):
    s = st.settings()
    if a.action == "show":
        print("admin:     %s <%s>" % (s["admin"].get("name"), s["admin"].get("email")))
        print("site url:  %s" % s.get("site_url"))
        print("rates (effective date: weekday hourly x hours, weekend hourly x hours):")
        for r in costing.rates_sorted(s):
            print("  %s: £%s x %sh = £%s weekday, £%s x %sh = £%s weekend" % (
                r["effective"], r["weekday"]["hourly"], r["weekday"]["hours"], r["weekday"]["hourly"] * r["weekday"]["hours"],
                r["weekend"]["hourly"], r["weekend"]["hours"], r["weekend"]["hourly"] * r["weekend"]["hours"]))
        print("budgets:   %s" % (s.get("budgets") or "none set"))
        print("data:      %s" % st.root)
    elif a.action == "site-url":
        s["site_url"] = a.value
        st.save_settings(s)
        print("site url set")
    elif a.action == "admin":
        s["admin"] = {"name": a.name or s["admin"].get("name"), "email": a.email or s["admin"].get("email")}
        st.save_settings(s)
        print("admin set to %s <%s>" % (s["admin"]["name"], s["admin"]["email"]))
    elif a.action == "rate":
        costing.add_rate(st, a.effective, a.weekday_hourly, a.weekday_hours, a.weekend_hourly, a.weekend_hours)
        print("rate added from %s: weekday £%s x %sh, weekend £%s x %sh. Shifts before that date keep the earlier rate." % (a.effective, a.weekday_hourly, a.weekday_hours, a.weekend_hourly, a.weekend_hours))
    elif a.action == "budget":
        s.setdefault("budgets", {})[a.year_label] = float(a.amount) if a.amount else None
        if a.amount is None:
            s["budgets"].pop(a.year_label, None)
        st.save_settings(s)
        print("budget for %s: %s" % (a.year_label, "£%.0f" % float(a.amount) if a.amount else "removed"))


def cmd_window(a, st: Store):
    if a.action == "create":
        w = W.create(st, a.id, a.start, a.end, a.deadline)
        print("created window %s: %s to %s (%d days), deadline %s, job plan year %s" % (w["id"], w["start"], w["end"], W.length(w), w["deadline"] or "none", w["year"]))
        print("next: `ccot links %s`" % w["id"])
    elif a.action == "list":
        rows = []
        for wid in st.window_ids():
            w = st.window(wid)
            rows.append([wid, w["year"], w["start"], w["end"], w.get("deadline") or "", w.get("status"), len(w.get("submissions") or {})])
        print(_table(rows, ["id", "year", "start", "end", "deadline", "status", "submitted"]))
    elif a.action == "show":
        w = st.window(a.id)
        print("%s: %s to %s, deadline %s, status %s" % (w["id"], w["start"], w["end"], w.get("deadline") or "none", w.get("status")))
        rows = []
        for c in R.consultants(st):
            al = W.allowance(st, w, c)
            rem = W.remaining_quota(st, w, c)
            ov = (w.get("allowances") or {}).get(c["initials"]) or {}
            sub = (w.get("submissions") or {}).get(c["initials"])
            rows.append([c["initials"], "yes" if c.get("active", True) else "no", "%d/%d" % (rem["weekday"], rem["weekend"]), "%d/%d" % (al["weekday"], al["weekend"]), "set" if ov else "", sub["available"] if sub else "-", (sub.get("max") or "none") if sub else "-"])
        print(_table(rows, ["ini", "active", "owed wd/we", "allowance wd/we", "override", "offered", "max wanted"]))
        print("allowance = what they still owe, spread over the %d window(s) left this year; change with `ccot window allowance`" % W.windows_left(w))
    elif a.action == "allowance":
        W.set_allowance(st, a.id, a.initials, a.weekday, a.weekend)
        print("allowance override saved for %s in %s" % (a.initials.upper(), a.id))
    elif a.action == "deadline":
        w = st.window(a.id)
        w["deadline"] = a.deadline.isoformat()
        st.save_window(w)
        print("deadline set")


def cmd_links(a, st: Store):
    s = st.settings()
    if "YOUR-GITHUB-USER" in s.get("site_url", ""):
        print("warning: site url is still the placeholder; set it with `ccot settings site-url ...`\n", file=sys.stderr)
    rows = W.links(st, a.id, include_inactive=a.all)
    lines = []
    for r in rows:
        lines.append("%s (%s)%s\n%s\n" % (r["name"], r["initials"], "" if r["active"] else " [inactive]", r["url"]))
    text = "\n".join(lines)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print("wrote %d links to %s" % (len(rows), a.out))
    else:
        print(text)


def cmd_import(a, st: Store):
    text = ""
    if a.codes:
        text = "\n".join(a.codes)
    elif a.file:
        text = Path(a.file).read_text(encoding="utf-8")
    else:
        print("paste the codes (or whole messages), then press Ctrl-D:", file=sys.stderr)
        text = sys.stdin.read()
    rep = importer.import_text(st, a.id, text)
    for r in rep["accepted"]:
        print("accepted  %s: %d dates offered, %d weekends together, %s" % (r["initials"], r["available"], r["pairs"], _limit(r.get("max"))))
    for r in rep["replaced"]:
        print("replaced  %s: %d dates offered, %d weekends together, %s (newer code replaces the earlier one)" % (r["initials"], r["available"], r["pairs"], _limit(r.get("max"))))
    for r in rep["rejected"]:
        print("REJECTED  %s: %s" % (r["code"], r["error"]))
    print()
    cmd_status(a, st)


def cmd_status(a, st: Store):
    s = importer.status(st, a.id)
    print("window %s, deadline %s, status %s" % (s["window"], s["deadline"] or "none", s["status"]))
    print("submitted (%d): %s" % (len(s["submitted"]), ", ".join("%s (%d%s)" % (x["initials"], x["available"], ", max %d" % x["max"] if x.get("max") else "") for x in s["submitted"]) or "nobody"))
    print("  (numbers are dates offered; 'max' is the most shifts that person wants this window)")
    print("missing (%d):   %s" % (len(s["missing"]), ", ".join("%s %s" % (x["initials"], x["name"]) for x in s["missing"]) or "nobody"))
    if s["inactive_submitted"]:
        print("inactive consultants who submitted: %s" % ", ".join(s["inactive_submitted"]))


def cmd_heatmap(a, st: Store):
    rows = importer.heatmap(st, a.id)
    if a.html:
        out = st.path("windows", "%s.heatmap.html" % a.id)
        out.write_text(importer.heatmap_html(rows, "Offers per date, window %s" % a.id), encoding="utf-8")
        print("wrote %s" % out)
        if sys.platform == "darwin" and not a.no_open:
            os.system('open "%s"' % out)
    else:
        print(importer.heatmap_text(rows))


def cmd_allocate(a, st: Store):
    w = st.window(a.id)
    if not w.get("submissions"):
        print("no submissions imported for %s yet" % a.id)
        return
    draft = allocate.run(st, a.id, time_limit=a.time_limit)
    print("draft saved. %d shifts filled, %d dates unfillable." % (sum(1 for v in draft["assignment"].values() if v), len(draft["unfillable"])))
    _print_review(a.id, draft, st)


def cmd_review(a, st: Store):
    w = st.window(a.id)
    if not w.get("draft"):
        print("no draft for %s; run `ccot allocate %s`" % (a.id, a.id))
        return
    _print_review(a.id, w["draft"], st)


def _print_review(wid: str, d: Dict[str, Any], st: Store):
    print("\n== Draft allocation for %s (made %s) ==" % (wid, d["generated"]))
    f = d["fill"]
    print("fill: weekdays %d/%d, weekend days %d/%d, bank holidays %d/%d" % (
        f["weekday"]["filled"], f["weekday"]["total"], f["weekend"]["filled"], f["weekend"]["total"], f["bh"]["filled"], f["bh"]["total"]))
    held = {h["date"]: h["offered_by"] for h in d.get("held_back_by_limits", [])}
    nobody = [x for x in d["unfillable"] if x not in held]
    if nobody:
        print("UNFILLABLE (nobody available): " + ", ".join(dt.date.fromisoformat(x).strftime("%a %d %b") for x in nobody))
    if held:
        print("UNFILLED BECAUSE OF SHIFT LIMITS (everyone who offered has reached the most shifts they asked for):")
        for x, who in sorted(held.items()):
            print("  %s  offered by %s" % (dt.date.fromisoformat(x).strftime("%a %d %b"), ", ".join(who)))
        print("  ask one of them whether they will do one more, then `ccot override DATE INITIALS --reason ...`")
    if not d["unfillable"]:
        print("every date is covered")
    print("\nobjectives:")
    for s in d["stages"]:
        print("  %-3s %-45s %6s  %s" % (s["name"], s["objective"], s["value"], "optimal" if s["optimal"] else "NOT PROVEN OPTIMAL (" + s["status"] + ")"))
    sat = d["satisfied"]
    print("  fully satisfied: " + ", ".join(k for k, v in sat.items() if v))
    unmet = [k for k, v in sat.items() if not v]
    if unmet:
        print("  not fully satisfied: " + ", ".join(unmet))
    if d["pair_violations"]:
        print("  weekend pairs split: " + ", ".join("%s %s" % (p["c"], p["saturday"]) for p in d["pair_violations"]))
    print("  locum count spread after this window: %d to %d" % (d["locum_spread"]["min"], d["locum_spread"]["max"]))
    rows = []
    for ini, c in sorted(d["consultants"].items(), key=lambda kv: -kv[1]["allocated"]):
        if not c["submitted"] and not c["allocated"]:
            continue
        rows.append([ini, c["offered"], c.get("max") or "", c["allocated"],
                     "%d+%d=%d/%d" % (c["jp_before"]["weekday"], c["jp_window"]["weekday"], c["jp_after"]["weekday"], c["quota"]["weekday"]),
                     "%d+%d=%d/%d" % (c["jp_before"]["weekend"], c["jp_window"]["weekend"], c["jp_after"]["weekend"], c["quota"]["weekend"]),
                     "%d/%d" % (c["allowance"]["weekday"], c["allowance"]["weekend"]),
                     "%d+%d=%d" % (c["locum_before"], c["locum_window"], c["locum_after"])])
    print("\nper consultant (JP columns: before + this window = after / annual quota):")
    print(_table(rows, ["ini", "offered", "max", "got", "JP weekday", "JP weekend", "allow wd/we", "locum before+new=after"]))
    missing = [ini for ini, c in d["consultants"].items() if not c["submitted"] and c["active"]]
    if missing:
        print("\nno code received (treated as unavailable): " + ", ".join(missing))
    print("\nallocation:")
    line = []
    for k in sorted(d["assignment"]):
        dd = dt.date.fromisoformat(k)
        h = d["assignment"][k]
        tag = "BH" if cal.day_type(dd) == cal.BH else "  "
        line.append("%s %s %s %s" % (dd.strftime("%a %d %b"), tag, (h or "----").ljust(4), (d["kinds"].get(k, "") if h else "UNFILLED")))
    print("\n".join(line))
    print("\nnext: `ccot accept %s` to commit, or `ccot window allowance` / `ccot import` and re-run `ccot allocate`" % wid)


def cmd_accept(a, st: Store):
    y = allocate.accept(st, a.id)
    print("draft for %s written into %s. %d shifts now recorded for the year, %d unfilled dates." % (a.id, y["year"], len(y["shifts"]), len(y["unfilled"])))
    print("next: `ccot publish` when you are ready for consultants to see it")


def cmd_override(a, st: Store):
    label = cal.job_plan_year(a.date)
    ini = None if a.initials.lower() in ("none", "-", "unfilled") else a.initials.upper()
    y = Y.override(st, label, a.date, ini, a.reason, kind=a.kind)
    s = y["shifts"].get(a.date.isoformat())
    print("%s: %s" % (a.date, ("%s (%s)" % (s["c"], s["kind"])) if s else "unfilled"))


def cmd_swap(a, st: Store):
    label = cal.job_plan_year(a.date)
    y = Y.swap(st, label, a.date, a.from_initials.upper(), a.to_initials.upper(), a.reason)
    s = y["shifts"][a.date.isoformat()]
    print("%s: now %s (%s). Logged." % (a.date, s["c"], s["kind"]))


def cmd_kind(a, st: Store):
    label = cal.job_plan_year(a.date)
    y = Y.reclassify(st, label, a.date, a.kind.upper(), a.reason)
    s = y["shifts"][a.date.isoformat()]
    print("%s: %s is now %s. Logged." % (a.date, s["c"], s["kind"]))


def cmd_credit(a, st: Store):
    label = cal.job_plan_year(a.date)
    ini = a.initials.upper()
    R.get(st, ini)
    t = "weekday" if a.weekday else "weekend"
    n = a.weekday or a.weekend
    Y.add_credit(st, label, ini, t, n, a.date, a.reason)
    done = Y.jp_done(st.year(label), ini)
    qw, qe = R.quota(R.get(st, ini), label)
    print("%s credited with %d job plan %s shift%s (dated %s). Job plan now %d/%d weekday, %d/%d weekend. Logged." % (
        ini, n, t, "" if n == 1 else "s", a.date, done["weekday"], qw, done["weekend"], qe))


def cmd_year(a, st: Store):
    label = a.year or _current_year()
    m = dashboard.year_metrics(st, label)
    y = st.year(label)
    print("job plan year %s (decided through %s)" % (label, m["decided_through"] or "nothing yet"))
    pt = m["per_type"]
    for t, name in ((cal.WEEKDAY, "weekdays"), (cal.WEEKEND, "weekend days"), (cal.BH, "bank holidays")):
        p = pt[t]
        print("  %-14s %3d filled of %3d decided (%3d in year): %3d job plan, %3d extra" % (name, p["filled"], p["decided"], p["total"], p["jp"], p["locum"]))
    w = m["wli"]
    print("  WLI bill: £%.0f to date, £%.0f committed, £%.0f projected for the year%s" % (
        w["spend_to_date"], w["committed"], w["projected"],
        (" (%.0f%% of the £%.0f budget%s)" % (w["budget_pct"], w["budget"], ", PROJECTED OVERSPEND" if w["overspend"] else "")) if w["budget"] else " (no budget set)"))
    print("  bank holiday shifts: %d (paid outside the WLI bill)" % w["bank_holiday_shifts"])
    rows = []
    counts = Y.counts(y)
    for c in R.consultants(st):
        qw, qe = R.quota(c, label)
        k = counts.get(c["initials"], {"jp_weekday": 0, "jp_weekend": 0, "locum_weekday": 0, "locum_weekend": 0, "bh": 0, "total": 0})
        rows.append([c["initials"], "%d/%d%s" % (k["jp_weekday"], qw, " done" if k["jp_weekday"] >= qw else ""), "%d/%d%s" % (k["jp_weekend"], qe, " done" if k["jp_weekend"] >= qe else ""), k["locum_weekday"], k["locum_weekend"], k["bh"], k["total"]])
    print(_table(rows, ["ini", "JP weekday", "JP weekend", "locum wd", "locum we", "BH", "shifts"]))
    if y.get("unfilled"):
        print("unfilled: " + ", ".join(y["unfilled"]))


def cmd_export(a, st: Store):
    label = a.year or _current_year()
    out = a.out or str(st.path("exports", "CCOT rota %s.xlsx" % cal.year_label_long(label)))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    xlsx_export.export(st, label, out)
    print("wrote %s" % out)


def _passphrase(label: str, env: str, given: Optional[str], existing: Path) -> str:
    """Ask once if the passphrase opens what is already published; ask twice only when it is new."""
    pw = os.environ.get(env) or given
    if pw:
        return pw
    while True:
        pw = getpass.getpass("%s passphrase: " % label)
        if not pw:
            continue
        state = dashboard.opens(existing, pw)
        if state:
            print("  matches the %s passphrase already in use" % label)
            return pw
        if state is False:
            print("  this is NOT the %s passphrase currently in use." % label)
            ans = input("  set it as a new passphrase? Everyone will need the new one. [y/N] ").strip().lower()
            if ans != "y":
                print("  try again")
                continue
        else:
            print("  no %s dashboard published yet; this sets its passphrase" % label)
        if pw == getpass.getpass("  again, to confirm the new passphrase: "):
            return pw
        print("  those did not match; try again")


def cmd_publish(a, st: Store):
    label = a.year or _current_year()
    targets = [("consultant", "CONSULTANT dashboard (shared with all consultants)", "CCOT_PASSPHRASE", REPO / "docs" / "rota" / "payload.enc"),
               ("admin", "ADMIN dashboard (you and senior leadership)", "CCOT_ADMIN_PASSPHRASE", REPO / "docs" / "admin" / "payload.enc")]
    if a.only:
        targets = [t for t in targets if t[0] == a.only]
    chosen = {}
    for view, what, env, path in targets:
        chosen[view] = _passphrase(what, env, a.passphrase if a.only else None, path)
    if chosen.get("consultant") and chosen.get("consultant") == chosen.get("admin"):
        print("error: the admin passphrase must be different from the consultant one, or every consultant could open the admin dashboard", file=sys.stderr)
        sys.exit(1)
    sw = None if a.no_bump else REPO / "docs" / "sw.js"
    for view, what, env, path in targets:
        payload = dashboard.publish(st, label, chosen[view], path, sw, view=view)
        print("wrote %s dashboard: %s (%d consultants, %d shifts)" % (view, path.relative_to(REPO), len(payload["consultants"]), len(payload["rota"])))
    print("next: push it:\n  git add docs && git commit -m \"Publish rota %s\" && git push" % label)


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ccot", description="CCOT consultant rota: admin tools and allocation engine.")
    p.add_argument("--data", help="data folder (default: $CCOT_DATA or ~/Documents/Claude/CCOT Rota App/CCOT Rota Data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create the data folder, optionally seeded from the existing workbook")
    s.add_argument("--from-workbook", help="path to Outreach Cons Rota .xlsx")
    s.add_argument("--year", default=_current_year(), help="job plan year to import, e.g. 2026-27")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("import-workbook", help="import (or re-import) a year from the workbook")
    s.add_argument("path")
    s.add_argument("--year", default=_current_year())
    s.add_argument("--replace", action="store_true", help="discard recorded shifts for the year first")
    s.set_defaults(fn=cmd_import_workbook)

    s = sub.add_parser("roster", help="manage consultants and quotas")
    s.add_argument("action", choices=["list", "add", "quota", "activate", "deactivate", "remove", "rename", "note"])
    s.add_argument("initials", nargs="?")
    s.add_argument("name", nargs="?")
    s.add_argument("--year", help="job plan year for quotas (default: current)")
    s.add_argument("--weekday", type=int)
    s.add_argument("--weekend", type=int)
    s.set_defaults(fn=cmd_roster)

    s = sub.add_parser("settings", help="site url, admin details, WLI rates, budgets")
    s.add_argument("action", choices=["show", "site-url", "admin", "rate", "budget"])
    s.add_argument("value", nargs="?", help="site url")
    s.add_argument("--name")
    s.add_argument("--email")
    s.add_argument("--effective", type=_date, help="rate: first date the new rate applies")
    s.add_argument("--weekday-hourly", type=float)
    s.add_argument("--weekday-hours", type=float)
    s.add_argument("--weekend-hourly", type=float)
    s.add_argument("--weekend-hours", type=float)
    s.add_argument("--year-label", help="budget: job plan year, e.g. 2026-27")
    s.add_argument("--amount", help="budget: amount in pounds, or omit to remove")
    s.set_defaults(fn=cmd_settings)

    s = sub.add_parser("window", help="booking windows")
    s.add_argument("action", choices=["create", "list", "show", "allowance", "deadline"])
    s.add_argument("id", nargs="?")
    s.add_argument("initials", nargs="?")
    s.add_argument("--start", type=_date)
    s.add_argument("--end", type=_date)
    s.add_argument("--deadline", type=_date)
    s.add_argument("--weekday", type=int)
    s.add_argument("--weekend", type=int)
    s.set_defaults(fn=cmd_window)

    s = sub.add_parser("links", help="print the personalised links for a window")
    s.add_argument("id")
    s.add_argument("--all", action="store_true", help="include inactive consultants")
    s.add_argument("--out", help="write to a file instead of printing")
    s.set_defaults(fn=cmd_links)

    s = sub.add_parser("import", help="import submitted codes (arguments, a file, or pasted on stdin)")
    s.add_argument("id")
    s.add_argument("codes", nargs="*")
    s.add_argument("--file")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("status", help="who has and has not submitted")
    s.add_argument("id")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("heatmap", help="offers per date")
    s.add_argument("id")
    s.add_argument("--html", action="store_true", help="write an HTML calendar and open it")
    s.add_argument("--no-open", action="store_true")
    s.set_defaults(fn=cmd_heatmap)

    s = sub.add_parser("allocate", help="solve the window and save a draft")
    s.add_argument("id")
    s.add_argument("--time-limit", type=float, default=60.0, help="seconds per objective stage")
    s.set_defaults(fn=cmd_allocate)

    s = sub.add_parser("review", help="print the saved draft")
    s.add_argument("id")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("accept", help="commit the draft into the year")
    s.add_argument("id")
    s.set_defaults(fn=cmd_accept)

    s = sub.add_parser("override", help="set or clear who holds a date (logged)")
    s.add_argument("date", type=_date)
    s.add_argument("initials", help="initials, or 'none' to leave the date unfilled")
    s.add_argument("--reason", required=True)
    s.add_argument("--kind", choices=["JP", "LOCUM"])
    s.set_defaults(fn=cmd_override)

    s = sub.add_parser("swap", help="hand a published shift from one consultant to another (logged, published)")
    s.add_argument("date", type=_date)
    s.add_argument("from_initials")
    s.add_argument("to_initials")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_swap)

    s = sub.add_parser("credit", help="count job plan shifts as done without a rota shift, e.g. lost to leave (logged)")
    s.add_argument("initials")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--weekday", type=int, help="number of weekday job plan shifts to credit (negative to undo)")
    g.add_argument("--weekend", type=int, help="number of weekend job plan shifts to credit (negative to undo)")
    s.add_argument("--date", type=_date, required=True, help="the date the credit relates to")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_credit)

    s = sub.add_parser("kind", help="reclassify a held shift as JP or LOCUM (logged)")
    s.add_argument("date", type=_date)
    s.add_argument("kind", choices=["JP", "LOCUM", "jp", "locum"])
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_kind)

    s = sub.add_parser("year", help="summary of a job plan year")
    s.add_argument("year", nargs="?")
    s.set_defaults(fn=cmd_year)

    s = sub.add_parser("export-xlsx", help="write the year as an .xlsx in the workbook's layout")
    s.add_argument("--year")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("publish", help="build and encrypt both dashboards: consultant (docs/rota/) and admin (docs/admin/)")
    s.add_argument("--year")
    s.add_argument("--only", choices=["consultant", "admin"], help="publish just one of the two dashboards")
    s.add_argument("--passphrase", help="with --only (or set CCOT_PASSPHRASE / CCOT_ADMIN_PASSPHRASE; otherwise you are prompted)")
    s.add_argument("--no-bump", action="store_true", help="do not change the service worker version")
    s.set_defaults(fn=cmd_publish)
    return p


def main(argv=None) -> None:
    p = build_parser()
    a = p.parse_args(argv)
    st = Store(a.data)
    if a.cmd != "init" and not st.exists():
        print("no data folder at %s. Run `ccot init` (optionally with --from-workbook) first." % st.root, file=sys.stderr)
        sys.exit(2)
    try:
        a.fn(a, st)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)
