"""Allocation engine scenarios. Dates in January 2027: Mon 4 Jan is the first Monday, no bank holidays after the 1st."""
import datetime as dt

from ccot import calendar as cal
from ccot.solver import Problem, solve
from conftest import D

MON = D("2027-01-04")


def days(n, start=MON):
    return [start + dt.timedelta(days=i) for i in range(n)]


def problem(dates, avail, allowance, pairs=None, ytd=None, prior=None, **kw):
    cs = sorted(avail)
    return Problem(dates=dates, consultants=cs, available={c: set(v) for c, v in avail.items()}, pairs={c: set(v) for c, v in (pairs or {}).items()},
                   allowance={c: dict(weekday=allowance.get(c, (0, 0))[0], weekend=allowance.get(c, (0, 0))[1]) for c in cs},
                   locum_ytd={c: (ytd or {}).get(c, 0) for c in cs}, prior=prior or {}, workers=1, **kw)


def holders(res):
    return {d: h for d, h in res.assignment.items()}


def test_over_subscribed_window_fills_everything_and_shares_the_extra():
    ds = days(14)  # two full weeks: 10 weekdays, 4 weekend days
    cs = ["A", "B", "C", "D", "E", "F"]
    res = solve(problem(ds, {c: ds for c in cs}, {c: (2, 0) for c in cs}))
    assert res.unfillable == []
    assert all(res.assignment[d] for d in ds)
    assert sum(v["weekday"] for v in res.jp.values()) == 10          # every weekday is a job plan shift
    assert sum(res.locum_new.values()) == 4                           # the 4 weekend days are extra
    assert max(res.locum_total.values()) == 1                         # nobody gets two while others have none
    assert all(s.optimal for s in res.stages)


def test_under_subscribed_window_lists_unfillable_dates():
    ds = days(14)
    res = solve(problem(ds, {"A": ds[0:3], "B": ds[3:5]}, {"A": (3, 0), "B": (2, 0)}))
    assert [d for d in ds if res.assignment[d]] == ds[0:5]
    assert res.unfillable == ds[5:]
    assert res.stages[0].value == 5


def test_consultant_who_offers_too_few_dates_gets_what_they_offered():
    ds = days(14)
    res = solve(problem(ds, {"A": ds[0:2], "B": ds}, {"A": (4, 0), "B": (10, 2)}))
    assert res.jp["A"]["weekday"] == 2 and sorted(d for d, h in res.assignment.items() if h == "A") == ds[0:2]
    assert res.jp["B"]["weekday"] == 8 and res.jp["B"]["weekend"] == 2
    assert res.unfillable == []


def test_pairing_request_yields_to_another_consultant_job_plan_shift():
    sat, sun = D("2027-01-09"), D("2027-01-10")
    ds = [sat, sun]
    # A wants both days together; B can only do Saturday and still owes a weekend shift.
    res = solve(problem(ds, {"A": ds, "B": [sat]}, {"A": (0, 1), "B": (0, 1)}, pairs={"A": [sat]}))
    assert res.assignment == {sat: "B", sun: "A"}
    assert res.pair_violations == [("A", sat)]
    assert res.stages[1].value == 2 and res.stages[2].value == 1


def test_pairing_request_is_honoured_when_it_costs_nothing_higher():
    sat, sun = D("2027-01-09"), D("2027-01-10")
    ds = [sat, sun]
    # Same as above but B has completed their job plan: fairness alone would split the weekend, pairing wins.
    res = solve(problem(ds, {"A": ds, "B": [sat]}, {"A": (0, 1), "B": (0, 0)}, pairs={"A": [sat]}))
    assert res.assignment == {sat: "A", sun: "A"}
    assert res.pair_violations == []


def test_pairing_outranks_fairness_and_never_blocks_coverage():
    sat, sun = D("2027-01-09"), D("2027-01-10")
    # Both have finished their job plans. Fairness alone would hand B the Saturday (B has fewer locum
    # shifts), but A asked for the weekend together and pairing sits above fairness in the hierarchy.
    res = solve(problem([sat, sun], {"A": [sat, sun], "B": [sat]}, {"A": (0, 0), "B": (0, 0)}, pairs={"A": [sat]}, ytd={"A": 3, "B": 0}))
    assert res.assignment == {sat: "A", sun: "A"}
    assert res.pair_violations == []
    # With no rest or cap constraints, giving someone both days can never leave a date unfilled,
    # so a pair is only ever split by objective 2 (another consultant's job plan shift).


def test_locum_tie_break_goes_to_fewest_locum_shifts_this_year():
    d = MON
    res = solve(problem([d], {"A": [d], "B": [d]}, {"A": (0, 0), "B": (0, 0)}, ytd={"A": 5, "B": 2}))
    assert res.assignment[d] == "B"
    # ... unless someone with job plan shifts outstanding is available: they come first.
    res = solve(problem([d], {"A": [d], "B": [d], "C": [d]}, {"A": (0, 0), "B": (0, 0), "C": (1, 0)}, ytd={"A": 5, "B": 0, "C": 9}))
    assert res.assignment[d] == "C" and res.jp["C"]["weekday"] == 1


def test_bank_holiday_is_never_a_job_plan_shift():
    bh = D("2027-01-01")
    assert cal.day_type(bh) == cal.BH
    res = solve(problem([bh], {"A": [bh]}, {"A": (5, 2)}))
    assert res.assignment[bh] == "A" and res.jp["A"] == {"weekday": 0, "weekend": 0} and res.locum_total["A"] == 1


def test_long_runs_are_avoided_when_there_is_a_choice():
    ds = days(10)  # 8 weekdays + a weekend
    res = solve(problem(ds, {"A": ds, "B": ds}, {"A": (4, 1), "B": (4, 1)}))
    for c in ("A", "B"):
        run = best = 0
        for d in ds:
            run = run + 1 if res.assignment[d] == c else 0
            best = max(best, run)
        assert best <= 4, c
    assert next(s for s in res.stages if s.name == "5").value == 0


def test_prior_shifts_before_the_window_count_towards_runs():
    ds = days(3)
    prior = {MON - dt.timedelta(days=k): "A" for k in (1, 2, 3, 4)}  # A worked the four days before the window
    res = solve(problem(ds, {"A": ds, "B": ds}, {"A": (3, 0), "B": (3, 0)}, prior=prior))
    assert res.assignment[ds[0]] == "B"


def test_results_are_deterministic():
    ds = days(28)
    avail = {c: [d for i, d in enumerate(ds) if (i * 7 + ord(c)) % 3] for c in "ABCDEFG"}
    p = problem(ds, avail, {c: (3, 1) for c in "ABCDEFG"}, ytd={c: i for i, c in enumerate("ABCDEFG")})
    a, b = solve(p), solve(p)
    assert a.assignment == b.assignment


def test_stated_maximum_is_never_exceeded_and_others_fill_the_rest():
    ds = days(14)
    res = solve(problem(ds, {"A": ds, "B": ds}, {"A": (10, 2), "B": (0, 0)}, max_shifts={"A": 3}))
    got_a = [d for d in ds if res.assignment[d] == "A"]
    assert len(got_a) == 3 and res.jp["A"]["weekday"] + res.jp["A"]["weekend"] == 3
    assert res.unfillable == [] and all(res.assignment[d] for d in ds)


def test_maximum_can_leave_a_date_unfilled_and_it_is_reported():
    ds = days(5)
    res = solve(problem(ds, {"A": ds}, {"A": (5, 0)}, max_shifts={"A": 2}))
    assert sum(1 for d in ds if res.assignment[d] == "A") == 2
    assert len(res.unfillable) == 3 and all(res.offers[d] == ["A"] for d in res.unfillable)


def test_no_maximum_means_only_availability_limits():
    ds = days(7)
    res = solve(problem(ds, {"A": ds}, {"A": (5, 2)}, max_shifts={}))
    assert all(res.assignment[d] == "A" for d in ds)


def test_extra_shifts_are_shared_within_the_quarter_not_the_year():
    ds = days(2)  # Mon, Tue
    # A has had far more extra shifts this year, but within this quarter both start level, so one each.
    res = solve(problem(ds, {"A": ds, "B": ds}, {"A": (0, 0), "B": (0, 0)}, ytd={"A": 10, "B": 0}))
    assert sorted(res.assignment.values()) == ["A", "B"]


def test_level_for_the_quarter_goes_to_fewest_since_april_then_biggest_contract():
    d = MON
    res = solve(problem([d], {"A": [d], "B": [d]}, {"A": (0, 0), "B": (0, 0)}, ytd={"A": 5, "B": 2}))
    assert res.assignment[d] == "B"
    p = problem([d], {"A": [d], "B": [d]}, {"A": (0, 0), "B": (0, 0)}, ytd={"A": 3, "B": 3})
    p.contract = {"A": 12, "B": 17}
    assert solve(p).assignment[d] == "B"
    p.contract = {"A": 17, "B": 12}
    assert solve(p).assignment[d] == "A"


def test_bank_holidays_do_not_count_towards_the_quarter_share():
    bh, wd = D("2027-01-01"), D("2027-01-05")
    # Only A can do the weekday, so A has 1 extra shift this quarter. The bank holiday is shared
    # on its own, so it goes on the year total (A 0, B 10) to A rather than "evening up" to B.
    res = solve(problem([bh, wd], {"A": [bh, wd], "B": [bh]}, {"A": (0, 0), "B": (0, 0)}, ytd={"A": 0, "B": 10}))
    assert res.assignment == {bh: "A", wd: "A"}


def test_bank_holidays_are_shared_evenly_among_themselves():
    gf, em = D("2027-03-26"), D("2027-03-29")  # Good Friday, Easter Monday
    res = solve(problem([gf, em], {"A": [gf, em], "B": [gf, em]}, {"A": (0, 0), "B": (0, 0)}, ytd={"A": 0, "B": 30}))
    assert sorted(res.assignment.values()) == ["A", "B"]
