"""Allocation by integer programming (OR-Tools CP-SAT), solved lexicographically.

Stages, each solved to optimality and then fixed before the next:
  1  maximise shifts filled
  2  maximise job plan shifts delivered (each consultant up to what they owe of each type, and in
     total no more than their job plan limit for the quarter)
  3  minimise weekend pairs split against the consultant's request
  4a minimise the highest number of extra (locum) shifts anyone gets this quarter, bank holidays aside
  4b minimise the sum of squares of those quarter counts (as level as possible)
  4c share this quarter's bank holidays the same way, on their own
  5  minimise runs of more than `max_run` consecutive days
  6  minimise extra shifts for one consultant in the same week (spreads shifts out)
  7a tie-break: extra shifts go to whoever has fewest since 1 April (bank holidays included)
  7b tie-break: then to whoever has the biggest annual job plan quota
  8  deterministic tie-break so the same inputs always give the same draft
Hard constraints: only dates a consultant marked available; one consultant per date; never more
shifts in the window than the consultant's own stated maximum, when they gave one.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ortools.sat.python import cp_model

from . import calendar as cal


@dataclass
class Problem:
    dates: List[dt.date]
    consultants: List[str]
    available: Dict[str, Set[dt.date]]
    pairs: Dict[str, Set[dt.date]]            # flagged Saturdays per consultant
    allowance: Dict[str, Dict[str, int]]      # {c: {"weekday": n, "weekend": n, "total": n}}; total optional
    locum_ytd: Dict[str, int]                 # locum shifts (incl. bank holidays) already this year
    prior: Dict[dt.date, str] = field(default_factory=dict)  # holders of dates just before the window
    contract: Dict[str, int] = field(default_factory=dict)  # annual job plan quota, weekday + weekend
    max_shifts: Dict[str, int] = field(default_factory=dict)  # most new shifts each consultant will take; absent = no limit
    max_run: int = 4
    time_limit: float = 60.0
    seed: int = 0
    workers: int = 8


@dataclass
class Stage:
    name: str
    objective: str
    value: int
    status: str
    optimal: bool


@dataclass
class Result:
    assignment: Dict[dt.date, Optional[str]]
    unfillable: List[dt.date]
    jp: Dict[str, Dict[str, int]]
    locum_new: Dict[str, int]
    locum_total: Dict[str, int]
    pair_violations: List[Tuple[str, dt.date]]
    stages: List[Stage]
    offers: Dict[dt.date, List[str]]


def solve(p: Problem) -> Result:
    m = cp_model.CpModel()
    x: Dict[Tuple[str, dt.date], cp_model.IntVar] = {}
    for c in p.consultants:
        for d in p.dates:
            if d in p.available.get(c, ()):
                x[c, d] = m.NewBoolVar("x_%s_%s" % (c, d))
    offers = {d: [c for c in p.consultants if (c, d) in x] for d in p.dates}
    for d in p.dates:
        if offers[d]:
            m.Add(sum(x[c, d] for c in offers[d]) <= 1)
    # each consultant's own limit on how many shifts they want in this window
    for c, cap in p.max_shifts.items():
        terms = [x[c, d] for d in p.dates if (c, d) in x]
        if terms and cap is not None and cap < len(terms):
            m.Add(sum(terms) <= max(0, int(cap)))

    # job plan shifts delivered, per consultant and day type, capped by the window allowance
    n: Dict[Tuple[str, str], object] = {}
    jp: Dict[Tuple[str, str], cp_model.IntVar] = {}
    for c in p.consultants:
        for t in (cal.WEEKDAY, cal.WEEKEND):
            terms = [x[c, d] for d in p.dates if (c, d) in x and cal.day_type(d) == t]
            n[c, t] = sum(terms) if terms else 0
            cap = max(0, int(p.allowance.get(c, {}).get(t, 0)))
            v = m.NewIntVar(0, cap, "jp_%s_%s" % (c, t))
            if terms:
                m.Add(v <= sum(terms))
            else:
                m.Add(v == 0)
            jp[c, t] = v

    for c in p.consultants:
        tot = p.allowance.get(c, {}).get("total")
        if tot is not None:
            m.Add(jp[c, cal.WEEKDAY] + jp[c, cal.WEEKEND] <= max(0, int(tot)))
    stages: List[Stage] = []
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = p.time_limit
    solver.parameters.num_search_workers = p.workers
    solver.parameters.random_seed = p.seed

    def run(name: str, desc: str, expr, maximize: bool) -> int:
        if isinstance(expr, int):
            stages.append(Stage(name, desc, expr, "TRIVIAL", True))
            return expr
        if maximize:
            m.Maximize(expr)
        else:
            m.Minimize(expr)
        st = solver.Solve(m)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError("stage %s: no solution (%s)" % (name, solver.StatusName(st)))
        val = int(round(solver.ObjectiveValue()))
        stages.append(Stage(name, desc, val, solver.StatusName(st), st == cp_model.OPTIMAL))
        m.Add(expr == val)
        return val

    # 1 fill
    run("1", "shifts filled", sum(x.values()) if x else 0, True)
    # 2 job plan
    run("2", "job plan shifts delivered", sum(jp.values()) if jp else 0, True)
    # 3 pairing
    viol = []
    for c in p.consultants:
        for sat in sorted(p.pairs.get(c, ())):
            sun = sat + dt.timedelta(days=1)
            if (c, sat) in x and (c, sun) in x:
                v = m.NewBoolVar("split_%s_%s" % (c, sat))
                m.Add(v >= x[c, sat] - x[c, sun])
                m.Add(v >= x[c, sun] - x[c, sat])
                viol.append((c, sat, v))
    run("3", "weekend pairs split", sum(v for _, _, v in viol) if viol else 0, False)
    # 4 fairness within this quarter
    def level(name: str, desc: str, counts: Dict[str, object], ubs: Dict[str, int]) -> None:
        vs = {}
        for c in p.consultants:
            v = m.NewIntVar(0, max(0, ubs[c]), "%s_%s" % (name, c))
            m.Add(v == counts[c])
            vs[c] = v
        top = max(ubs.values()) if ubs else 0
        if not vs or top == 0:
            stages.append(Stage(name, "highest " + desc, 0, "TRIVIAL", True))
            stages.append(Stage(name + "+", "sum of squared " + desc, 0, "TRIVIAL", True))
            return
        vmax = m.NewIntVar(0, top, name + "_max")
        for c in p.consultants:
            m.Add(vmax >= vs[c])
        run(name, "highest " + desc, vmax, False)
        sq = []
        for c in p.consultants:
            s = m.NewIntVar(0, ubs[c] * ubs[c], "%s_sq_%s" % (name, c))
            m.AddMultiplicationEquality(s, [vs[c], vs[c]])
            sq.append(s)
        run(name + "+", "sum of squared " + desc, sum(sq), False)

    q_locum: Dict[str, object] = {}
    q_bh: Dict[str, object] = {}
    q_ub: Dict[str, int] = {}
    bh_ub: Dict[str, int] = {}
    for c in p.consultants:
        bh_terms = [x[c, d] for d in p.dates if (c, d) in x and cal.day_type(d) == cal.BH]
        q_locum[c] = (n[c, cal.WEEKDAY] - jp[c, cal.WEEKDAY]) + (n[c, cal.WEEKEND] - jp[c, cal.WEEKEND])
        q_bh[c] = sum(bh_terms) if bh_terms else 0
        q_ub[c] = sum(1 for d in p.available.get(c, ()) if d in offers and cal.day_type(d) != cal.BH)
        bh_ub[c] = len(bh_terms)
    level("4a", "extra shifts this quarter (bank holidays aside)", q_locum, q_ub)
    level("4c", "bank holidays this quarter", q_bh, bh_ub)
    # year-to-date totals, used for the tie-break and the report
    L: Dict[str, cp_model.IntVar] = {}
    ubs = {}
    for c in p.consultants:
        ub = p.locum_ytd.get(c, 0) + len(p.available.get(c, ()))
        ubs[c] = ub
        v = m.NewIntVar(0, ub, "L_%s" % c)
        m.Add(v == p.locum_ytd.get(c, 0) + q_locum[c] + q_bh[c])
        L[c] = v
    # 5 consecutive days
    runs = []
    span_len = p.max_run + 1
    for c in p.consultants:
        for d0 in p.dates:
            span = [d0 - dt.timedelta(days=k) for k in range(span_len)]
            terms = []
            const = 0
            for d in span:
                if (c, d) in x:
                    terms.append(x[c, d])
                elif d not in p.dates and p.prior.get(d) == c:
                    const += 1
            if not terms or const + len(terms) <= p.max_run:
                continue
            v = m.NewIntVar(0, 1, "run_%s_%s" % (c, d0))
            m.Add(v >= sum(terms) + const - p.max_run)
            runs.append(v)
    run("5", "runs longer than %d days" % p.max_run, sum(runs) if runs else 0, False)
    # 6 spread within the window
    weeks: Dict[Tuple[int, int], List[dt.date]] = {}
    for d in p.dates:
        weeks.setdefault(d.isocalendar()[:2], []).append(d)
    clus = []
    for c in p.consultants:
        for wk, ds in weeks.items():
            terms = [x[c, d] for d in ds if (c, d) in x]
            if len(terms) <= 1:
                continue
            v = m.NewIntVar(0, len(terms), "wk_%s_%s_%s" % (c, wk[0], wk[1]))
            m.Add(v >= sum(terms) - 1)
            clus.append(v)
    run("6", "extra shifts for one person in the same week", sum(clus) if clus else 0, False)
    # 7 tie-breaks among people level for the quarter
    if L:
        sqy = []
        for c in p.consultants:
            s = m.NewIntVar(0, ubs[c] * ubs[c], "ysq_%s" % c)
            m.AddMultiplicationEquality(s, [L[c], L[c]])
            sqy.append(s)
        run("7a", "extra shifts since 1 April (squared, lower first)", sum(sqy), False)
        weighted = [int(p.contract.get(c, 0)) * (q_locum[c] + q_bh[c]) for c in p.consultants if not isinstance(q_locum[c] + q_bh[c], int)]
        run("7b", "extra shifts weighted by job plan quota (higher first)", sum(weighted) if weighted else 0, True)
    else:
        stages.append(Stage("7a", "extra shifts since 1 April", 0, "TRIVIAL", True))
        stages.append(Stage("7b", "extra shifts weighted by job plan quota", 0, "TRIVIAL", True))
    # 8 deterministic tie-break
    ci = {c: i for i, c in enumerate(p.consultants)}
    di = {d: i for i, d in enumerate(p.dates)}
    tie = sum(((ci[c] * 31 + di[d] * 17) % 23 + 1) * v for (c, d), v in x.items()) if x else 0
    run("8", "tie-break", tie, False)

    assignment: Dict[dt.date, Optional[str]] = {}
    for d in p.dates:
        holder = None
        for c in offers[d]:
            if solver.Value(x[c, d]):
                holder = c
                break
        assignment[d] = holder
    unfillable = [d for d in p.dates if assignment[d] is None]
    jp_out = {c: {t: int(solver.Value(jp[c, t])) for t in (cal.WEEKDAY, cal.WEEKEND)} for c in p.consultants}
    locum_total = {c: int(solver.Value(L[c])) for c in p.consultants} if L else {}
    locum_new = {c: locum_total[c] - p.locum_ytd.get(c, 0) for c in p.consultants} if L else {}
    pv = [(c, sat) for c, sat, v in viol if solver.Value(v)]
    return Result(assignment, unfillable, jp_out, locum_new, locum_total, pv, stages, offers)
