# Engine and admin tool

Python, runs only on the administrator's Mac. Nothing here is ever deployed.

## One-time setup

```bash
python3 -m venv engine/.venv
engine/.venv/bin/pip install -e "engine[test]"
./ccot init --from-workbook "path/to/Outreach Cons Rota v2.xlsx" --year 2026-27
./ccot settings site-url https://YOUR-USER.github.io/ccot-rota/
```

`init` creates the data folder (default `~/Documents/Claude/CCOT Rota App/CCOT Rota Data`, or `$CCOT_DATA`, or `--data DIR`)
and seeds the roster, quotas, this year's allocations and the Summary history from the workbook.
Everything in that folder is plain JSON you can read and back up. It is outside the repository
on purpose: the repository is public.

Run the tests with `engine/.venv/bin/python -m pytest engine/tests`.

## Each quarter

```bash
./ccot window create 2026-27-Q4 --start 2027-01-01 --end 2027-03-31 --deadline 2026-11-30
./ccot links 2026-27-Q4            # one personalised link per active consultant; send them out
./ccot import 2026-27-Q4           # paste codes or whole messages, Ctrl-D to finish
./ccot status 2026-27-Q4           # who has and has not replied
./ccot heatmap 2026-27-Q4 --html   # offers per date, spot gaps before the deadline
./ccot window show 2026-27-Q4      # what each person owes and their allowance for this window
./ccot allocate 2026-27-Q4         # solve and print the draft
./ccot review 2026-27-Q4           # print the saved draft again
./ccot accept 2026-27-Q4           # commit the draft into the year
./ccot publish                     # encrypt both dashboards: docs/ccotrota/ (consultants) and docs/ccotrota/admin/ (admin)
git add docs && git commit -m "Publish rota" && git push
```

Consultants who have not sent a code by the time you run `allocate` are treated as unavailable.
A consultant may also say the most shifts they want in the window; the allocation never goes over it.
`ccot status` and `ccot review` show each limit, and the review lists any date left unfilled only
because everyone who offered it had reached their limit.
Import more codes and run `allocate` again as often as you like before `accept`.

## After publication

```bash
./ccot swap 2027-02-03 AW XW --reason "childcare"          # consultant-requested swap, logged and published
./ccot override 2027-02-04 DL --reason "..." [--kind LOCUM] # set (or `none` to clear) who holds a date, logged
./ccot kind 2027-02-05 LOCUM --reason "cover for AWB"      # reclassify a held shift, logged
./ccot publish && git add docs && git commit -m "Publish rota" && git push
```

## Roster, rates, budget

```bash
./ccot roster list
./ccot roster add LDC "Leonel De Caires" --weekday 10 --weekend 2
./ccot roster quota LDC --weekday 10 --weekend 2 --year 2026-27
./ccot roster deactivate EL          # keeps them and their history; no link unless `links --all`
./ccot roster activate EL
./ccot settings rate --effective 2027-04-01 --weekday-hourly 130 --weekday-hours 12 --weekend-hourly 160 --weekend-hours 10
./ccot settings budget --year-label 2026-27 --amount 202500
./ccot year 2026-27                  # per-consultant counts, fill rates and WLI position
./ccot export-xlsx --year 2026-27    # workbook in the existing layout and colours
```

Rates are effective-dated: a new rate applies to shifts from its date onwards and earlier shifts
keep the rate that applied when they were worked.

## How the allocation works

`ccot/solver.py` builds an integer programme (OR-Tools CP-SAT) with two hard constraints, "only
dates the consultant marked available" and "one consultant per date", and solves these objectives
in strict order, fixing each optimum before moving to the next:

1. maximise shifts filled (dates nobody offered are reported as unfillable);
2. maximise job plan shifts delivered, each consultant up to what they owe and their job plan limit
   for the quarter;
3. minimise weekend pairs split against a "both days together" request;
4. share extra (locum) shifts as evenly as possible within the quarter: first the highest number
   anyone gets, then the sum of squares. Bank holidays are left out of this and shared evenly on
   their own;
5. minimise runs longer than four consecutive days;
6. minimise second shifts for one person in the same week;
7. tie-breaks for people level for the quarter: fewest extra shifts since 1 April (bank holidays
   included), then the biggest annual job plan quota (weekday plus weekend);
8. a fixed tie-break so the same inputs always give the same draft.

Job plan limit per quarter. Within one quarter a consultant can be given at most this share of their
annual job plan (weekday plus weekend days), rounded down: April to June 50%, July to September
50%, October to December 80%. January to March has no limit, so everyone can finish what they owe.
Once someone reaches the limit, further shifts they are given are locum, including days only they
offered. This stops anyone doing nearly all of their job plan in one quarter just because they had
lots of availability then. `ccot window allowance ID INI --total N` overrides one person's limit.
Within a window a consultant's first shifts up to the allowance are job plan
and the rest are locum, in date order. Bank holiday shifts are always extra, count as locum for
the year total, and are left out of the WLI bill.

## Publishing

`ccot publish` builds both dashboards. It asks for each passphrase once and checks it against
the one already in use, so a typo is caught straight away. It only asks you to type it twice
when you are setting a new passphrase. `--only consultant` or `--only admin` publishes one.
Every code received is kept in the window file, so the admin dashboard can show earlier
versions of someone's request as well as the one used.
