# Static site

Published by GitHub Pages from this folder. Holds code only, never data.

## Preference app (`index.html`)

Opened from a personalised link. Everything after `?` is the consultant's identity and the
booking window; the site itself has no roster.

| Parameter | Meaning | Example |
|---|---|---|
| `c` | initials, 1 to 3 letters | `AWB` |
| `k` | link token, hex, per consultant per window | `7f3a9c` |
| `n` | first name for the greeting, optional | `Adam` |
| `w` | booking window id | `2026-27-Q4` |
| `s`, `e` | window start and end, inclusive, ISO dates | `2027-01-01`, `2027-03-31` |
| `d` | submission deadline, ISO date, optional | `2026-11-30` |
| `jw`, `je` | job plan weekday and weekend shifts still owed this year | `4`, `0` |

The admin tool (`ccot links`) generates these. The app remembers the last link on the device, so
the installed home screen app opens with no parameters and still knows who it is.

Availability, weekend pairs and the optional "most shifts I want this quarter" limit are saved to
`localStorage` on every change. Blank means no limit. The limit travels inside the code (schema
version 2) and the engine never gives that person more shifts in the window. Version 1 codes,
made before the limit existed, are still accepted and mean no limit.

Availability is saved to `localStorage` on every tap. The code is produced by `codec.js`; the
format is documented at the top of that file.

## Dashboards

Two encrypted dashboards, each with its own passphrase. Both are built by `ccot publish`.

| Page | For | Shows |
|---|---|---|
| `rota/` "CCOT Consultant Rota" | all consultants | rota by month (job plan and extra colouring), job plan progress, notes, swaps and changes |
| `admin/` "CCOT Consultant Rota Admin" | rota lead and senior leadership | everything above plus locum counts, Summary and WLI spend, and every availability code each consultant sent |

The consultant file is built separately and contains no locum totals, money or availability
requests, so the consultant passphrase cannot reveal them. The admin passphrase must differ.

## Deploying

Push to `main`. GitHub Pages must be set to serve from the `docs/` folder. When you change any
file under `docs/`, bump `VERSION` in `sw.js` so installed copies update.
