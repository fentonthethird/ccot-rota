"""Allocation by integer programming (OR-Tools CP-SAT), solved lexicographically.

Stages, each solved to optimality and then fixed before the next:
  1  maximise shifts filled
  2  maximise job plan shifts delivered (each consultant up to their window allowance)
  3  minimise weekend pairs split against the consultant's request
  4a minimise the highest year-to-date locum count
  4b minimise the sum of squared year-to-date locum counts (spreads the rest evenly)
  5  minimise runs of more than `max_run` consecutive days
  6  minimise extra shifts for one consultant in the same week (spreads shifts out)
  7  deterministic tie-break so the same inputs always give the same draft
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
    allowance: Dict[str, Dict[str, int]]      # {c: {"weekday": n, "weekend": n}}
    locum_ytd: Dict[str, int]                 # locum shifts (incl. bank holidays) already this year
    prior: Dict[dt.date, str] = field(default_factory=dict)  # holders of dates just before the window
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
    # 4 fairness on year-to-date locum counts
    L: Dict[str, cp_model.IntVar] = {}
    ubs = {}
    for c in p.consultants:
        bh_terms = [x[c, d] for d in p.dates if (c, d) in x and cal.day_type(d) == cal.BH]
        expr = p.locum_ytd.get(c, 0) + (n[c, cal.WEEKDAY] - jp[c, cal.WEEKDAY]) + (n[c, cal.WEEKEND] - jp[c, cal.WEEKEND]) + (sum(bh_terms) if bh_terms else 0)
        ub = p.locum_ytd.get(c, 0) + len(p.available.get(c, ()))
        ubs[c] = ub
        v = m.NewIntVar(0, ub, "L_%s" % c)
        m.Add(v == expr)
        L[c] = v
    if L:
        lmax = m.NewIntVar(0, max(ubs.values()), "Lmax")
        for c in p.consultants:
            m.Add(lmax >= L[c])
        run("4a", "highest year-to-date locum count", lmax, False)
        sq = []
        for c in p.consultants:
            s = m.NewIntVar(0, ubs[c] * ubs[c], "sq_%s" % c)
            m.AddMultiplicationEquality(s, [L[c], L[c]])
            sq.append(s)
        run("4b", "sum of squared locum counts", sum(sq), False)
    else:
        stages.append(Stage("4a", "highest year-to-date locum count", 0, "TRIVIAL", True))
        stages.append(Stage("4b", "sum of squared locum counts", 0, "TRIVIAL", True))
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
    # 7 deterministic tie-break
    ci = {c: i for i, c in enumerate(p.consultants)}
    di = {d: i for i, d in enumerate(p.dates)}
    tie = sum(((ci[c] * 31 + di[d] * 17) % 23 + 1) * v for (c, d), v in x.items()) if x else 0
    run("7", "tie-break", tie, False)

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
