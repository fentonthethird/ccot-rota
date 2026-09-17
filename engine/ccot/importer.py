"""Import submitted codes, report who has and has not submitted, and show offers per date."""
from __future__ import annotations

import datetime as dt
import html
from typing import Any, Dict, List

from . import calendar as cal
from . import codec
from . import roster as R
from . import windows as W
from .store import Store


def import_text(store: Store, wid: str, text: str) -> Dict[str, Any]:
    w = store.window(wid)
    W.ensure_tokens(store, w)
    start = dt.date.fromisoformat(w["start"])
    length = W.length(w)
    report: Dict[str, Any] = {"accepted": [], "replaced": [], "rejected": []}
    codes = codec.extract_codes(text)
    if not codes and text.strip():
        codes = [text.strip()]
    for code in codes:
        try:
            ini = codec.peek_initials(code)
            token = w["tokens"].get(ini)
            if token is None:
                raise codec.CodeError("%s is not on the roster for this window" % ini)
            p = codec.decode(code, token)
            if p.start != start or p.length != length:
                raise codec.CodeError("code is for a different window (%s to %s, this window is %s to %s)" % (p.start, p.end, w["start"], w["end"]))
        except codec.CodeError as e:
            report["rejected"].append({"code": code, "error": str(e)})
            continue
        sub = {"code": code, "received": dt.datetime.now().isoformat(timespec="seconds"),
               "days": "".join(str(v) for v in p.days), "pairs": p.pairs,
               "available": sum(p.days)}
        existed = ini in w.setdefault("submissions", {})
        w["submissions"][ini] = sub
        (report["replaced"] if existed else report["accepted"]).append({"initials": ini, "available": sum(p.days), "pairs": len(p.pairs)})
    store.save_window(w)
    return report


def status(store: Store, wid: str) -> Dict[str, Any]:
    w = store.window(wid)
    subs = w.get("submissions") or {}
    active = R.consultants(store, include_inactive=False)
    inactive = [c for c in R.consultants(store) if not c.get("active", True)]
    out = {
        "window": wid, "deadline": w.get("deadline"), "status": w.get("status"),
        "submitted": [{"initials": c["initials"], "name": c["name"], "available": subs[c["initials"]]["available"], "received": subs[c["initials"]]["received"]} for c in active if c["initials"] in subs],
        "missing": [{"initials": c["initials"], "name": c["name"]} for c in active if c["initials"] not in subs],
        "inactive_submitted": [c["initials"] for c in inactive if c["initials"] in subs],
    }
    return out


def heatmap(store: Store, wid: str) -> List[Dict[str, Any]]:
    w = store.window(wid)
    start = dt.date.fromisoformat(w["start"])
    subs = w.get("submissions") or {}
    rows = []
    for i, d in enumerate(W.dates(w)):
        offers = sorted(ini for ini, s in subs.items() if i < len(s["days"]) and s["days"][i] == "1")
        rows.append({"date": d, "type": cal.day_type(d), "offers": offers, "count": len(offers)})
    return rows


def heatmap_text(rows: List[Dict[str, Any]]) -> str:
    lines = []
    for r in rows:
        mark = "!!" if r["count"] == 0 else " !" if r["count"] == 1 else "  "
        tag = {"bh": "BH ", "weekend": "WE ", "weekday": "   "}[r["type"]]
        lines.append("%s %s %s %2d  %s" % (mark, r["date"].strftime("%a %d %b"), tag, r["count"], " ".join(r["offers"])))
    zero = sum(1 for r in rows if r["count"] == 0)
    one = sum(1 for r in rows if r["count"] == 1)
    lines.append("")
    lines.append("%d dates with no offers (!!), %d with a single offer (!)" % (zero, one))
    return "\n".join(lines)


def heatmap_html(rows: List[Dict[str, Any]], title: str) -> str:
    def colour(n: int) -> str:
        return "#f4b6b0" if n == 0 else "#ffe3a3" if n == 1 else "#d4ead0" if n == 2 else "#9ed69a"
    cells = []
    first = rows[0]["date"]
    lead = first.weekday()
    cells.append("<tr>" + "".join("<th>%s</th>" % x for x in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) + "</tr><tr>" + "<td></td>" * lead)
    col = lead
    for r in rows:
        if col == 7:
            cells.append("</tr><tr>")
            col = 0
        cells.append('<td style="background:%s"><b>%s</b>%s<div class="n">%d</div><div class="who">%s</div></td>' % (
            colour(r["count"]), r["date"].strftime("%d %b"), ' <span class="bh">BH</span>' if r["type"] == "bh" else "", r["count"], html.escape(" ".join(r["offers"]))))
        col += 1
    cells.append("</tr>")
    return """<!doctype html><meta charset="utf-8"><title>%s</title>
<style>body{font-family:-apple-system,Helvetica,Arial,sans-serif;padding:16px}table{border-collapse:separate;border-spacing:4px}
td{vertical-align:top;width:120px;height:70px;border-radius:6px;padding:4px;font-size:12px}th{font-size:12px;color:#555}
.n{font-size:20px;font-weight:700}.who{color:#333;word-break:break-word}.bh{background:#ffb81c;border-radius:3px;padding:0 3px;font-size:10px}</style>
<h1>%s</h1><p>Number of consultants offering each date. Red: nobody. Amber: one person. Green: two or more.</p><table>%s</table>""" % (
        html.escape(title), html.escape(title), "".join(cells))
