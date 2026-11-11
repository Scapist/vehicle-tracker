# Vehicle Maintenance Tracker: Plan (v2)

## Status / how to resume
- **Status (2026-11-11):** all 10 build steps are done and verified (76 backend tests, `tsc` + production build, Playwright at 1280px and 390px, `docker compose up` checked). The real Telegram round trip is verified: mileage text, due-soon and overdue alerts, and **Done today**. Not yet exercised live: Undo, Snooze, `/due`, receipt photo/PDF.
- Project folder: `D:\Users\user\Documents\Github\vehicle-tracker`. This plan is copied there as `docs/PLAN.md`, which is the copy to keep up to date.
- To resume in a new session, open Claude Code in the Github folder and say: *"Read vehicle-tracker/docs/PLAN.md and continue from the next unchecked build step."*
- Tick each build step below (`[x]`) when it's done and verified.

## Context
This is a self-hosted tracker for mileage, services, costs, receipts and tire sets. It warns ahead of time when maintenance is due, by km or by date. It runs on a home server on the LAN. Two parts must stay modular because other personal tools will reuse them later: the **alert sender** (Telegram) and the **status/dashboard feed**. The project is new (greenfield), so there is no existing code to reuse.

Done when: `docker compose up` works, the UI works well on both phone and desktop, a service with a receipt can be logged, mileage can be texted to the bot, and a Telegram alert fires when an item becomes due.

## Stack
**Backend:** FastAPI (pure JSON API) · SQLAlchemy 2.0 + Alembic · SQLite (WAL) · python-telegram-bot v21 (long polling, so no public webhook) · APScheduler (daily job) · pydantic-settings · uv · pytest + time-machine.

**Frontend:** **React + Vite + TypeScript** · **Mantine** (AppShell, forms, `@mantine/dates`, `@mantine/charts`, notifications, built-in dark mode) · React Router · TanStack Query. The API client types are generated from FastAPI's OpenAPI schema with `openapi-typescript`, so frontend and backend can't drift apart.

**Packaging:** a multi-stage Dockerfile. Node builds the SPA into `/static`, and the final image is Python only. FastAPI serves the static files and the `/api`, so it stays **one container on one port**. For development, `vite dev` proxies `/api` to uvicorn.

Units and time: km and CAD, with money stored as integer cents. Timestamps are stored in UTC and shown in `America/Toronto`. "Today" is computed in Toronto time.

## UI
**Responsive, with desktop and mobile both first-class**, built on Mantine's AppShell:
- **Desktop (≥ md):** a left sidebar (Dashboard, Vehicles, Tires, Reports, Settings). The dashboard uses a multi-column grid of vehicle cards. Services, odometer history and tires use **sortable/filterable tables**. Forms open in modals, and receipts preview in a side drawer.
- **Mobile:** the sidebar becomes a bottom tab bar, tables become stacked cards, modals become full-screen sheets, and the receipt picker offers **Take photo** (camera capture).
- **Everywhere:** a **＋ Quick log** button (Mileage · Service · Receipt). Status always uses color + icon + plain words ("Oil change: ~600 km left, about Dec 3"; "Not enough driving data to estimate a date yet"). Each item gets a progress bar for how much of its interval is used. Defaults are prefilled (date = today, km = current). **Undo** notifications replace confirm dialogs. Empty states guide the next step. Dark mode follows the system, with a manual toggle. The app is installable as a PWA (manifest + icons).

```
Desktop                                              Mobile
┌────────────┬──────────────────────────────────────┐ ┌───────────────────┐
│ ⌂ Dashboard│ Civic 2019 · 84,500 km  [Update km][＋]│ │ Civic  84,500 km  │
│ 🚗 Vehicles │ ┌─Needs attention──────┐┌─Upcoming───┐ │ │ ⛔ Brakes 12d over │
│ ◎ Tires    │ │⛔ Brakes  12d overdue ││✓ Rotation  │ │ │ [Done] [Snooze]   │
│ ▤ Reports  │ │  [Done today][Snooze]││  ~4,100 km │ │ │ ⚠ Oil ~600 km     │
│ ⚙ Settings │ │⚠ Oil ~600km ≈Dec 3   ││✓ Reg. Jun30│ │ │ ████████░ 94%     │
│            │ └──────────────────────┘└────────────┘ │ │ ...               │
│            │ Recent services            2026: $1,240│ ├───────────────────┤
│            │ Date ▾ │ Work        │ km     │ Cost │📎│ │ ⌂  🚗  ◎  ▤   (＋) │
└────────────┴──────────────────────────────────────┘ └───────────────────┘
```

**Review checkpoint:** after the dashboard and vehicle pages are built against the seed data, I'll send desktop + phone screenshots (light and dark) for your feedback before building the remaining screens.

## Data model
| Table | Key fields | Notes |
|---|---|---|
| `vehicle` | id, nickname, make, model, year, vin?, archived | `nickname` is used by the Telegram bot |
| `odometer_reading` | vehicle_id, km, recorded_at, source (`ui`/`telegram`/`service`), is_correction | Source of truth for current km |
| `service_type` | key, name, default_interval_km/months, default_soon_km/days | Seeded with oil, tire rotation, brake inspection, engine air filter, cabin filter, battery |
| `service_record` | vehicle_id, date, odometer_km, cost_cents, vendor, notes | One visit |
| `service_record_item` | service_record_id, service_type_id, cost_cents? | A visit can cover several types. Unallocated cost shows as "General" |
| `attachment` | service_record_id, orig_name, stored_name (uuid), mime, size, sha256 | Files go in `data/receipts/YYYY/` |
| `reminder_rule` | vehicle_id, service_type_id, interval_km?, interval_months?, soon_km, soon_days, baseline_date?, baseline_km?, enabled | Needs at least one interval. Soon windows are per rule, prefilled from defaults |
| `date_item` | vehicle_id?, kind (registration/insurance/winter_install/winter_remove/custom), title, due_date, recurs_yearly, soon_days | "Mark done" rolls the date forward 1 year |
| `tire_set` | vehicle_id, label, season, size, brand_model, dot_code, purchase_date, cost_cents, storage_location, retired | |
| `tire_mount` | tire_set_id, mounted_date/km, removed_date?/km? | km per set = sum of mounts. Only one set mounted at a time |
| `tire_tread` | tire_set_id, date, depth_mm | Flagged at ≤4 mm (winter) or ≤3 mm (other) |
| `alert_state` | subject (`rule:12`/`date:5`), cycle_key, status, changed_at, snoozed_until? | One alert per state change |
| `notification_outbox` | source, dedupe_key, title, body, actions_json, sent_at?, attempts, last_error | Separates deciding to alert from sending |

Winter tires (the Quebec rule is Dec 1 – Mar 15) are two yearly date items: "Install by Dec 1" with a 30-day window, and "Can remove after Mar 15", which is informational. Marking either as done asks which tire set was mounted.

## Due-date logic (`app/domain/due.py`, pure)
- **km:** `due_km = last_km + interval_km`. The date estimate uses the average km/day over the last 90 days (≥2 readings spanning ≥14 days). If that's not available it falls back to the full history. If that fails too, there is no estimate and the reason says "not enough mileage data".
- **time:** `last_date + interval_months`, clamped to the end of the month when needed.
- **whichever-first:** the effective date is the earlier one. The item is overdue if either limit has passed, and due soon if either is inside its window.
- **no history and no baseline:** status is `unknown` with the prompt "log when this was last done". The app never guesses.
- **odometer going backwards:** rejected unless flagged as a correction. A correction invalidates the readings above it.

## Alerting (modular)
- `evaluator.py` runs daily at 08:00 Toronto time and after any odometer or service change. On a transition **into** due_soon or overdue for a `(subject, cycle_key)`, it writes a row to the outbox. Logging a service starts a new cycle. After a snooze expires, an item that is still due re-alerts once.
- `app/notify/` holds the `Notifier.send(title, body, actions=[Action(label, callback_id)])` protocol, `TelegramNotifier`, `LogNotifier`, and the outbox dispatcher with retry. It has **no imports from the vehicle domain**.
- `app/feed/`: `GET /api/v1/status` returns a normalized item list (`source, subject, title, status, due, detail_url`) for the future shared dashboard.

## Telegram bot (inbound, `app/bot/`)
- Accepts messages only from `TELEGRAM_ALLOWED_CHAT_IDS`.
- Mileage parser (pure): handles `84,500 km`, `84500`, `84 500` (including the nbsp separator), `84.500` and `84.5k`, with an optional nickname. It rejects ambiguous or absurd values.
- **Vehicle guess, then confirm:** a bare number goes to the vehicle whose current km is the closest value below it, and the reply has a `[Wrong vehicle]` button. A nickname always overrides. If nothing is plausible, the bot asks. A lower value than current → "Correction?". A huge jump → confirmation.
- Alert buttons: **Done today** (logs the service at the current km) and **Snooze 7 d**.
- Photo/PDF → attaches to the latest visit from the last 7 days, or offers to pick a visit or create a "receipt only" one.
- Commands: `/due`, `/vehicles`, `/help`.

## API (`/api/v1`, documented automatically at `/docs`)
`vehicles` · `vehicles/{id}/odometer` · `services` (multipart, with receipts) · `attachments/{id}` · `rules` · `date-items` (+ `/{id}/done`) · `tire-sets`, `tire-sets/{id}/mount|unmount|tread` · `vehicles/{id}/dashboard` (aggregated view model) · `reports?vehicle=&year=` · `export/{services,odometer,tires}.csv` · `status` · `/healthz`. Any path other than `/api` falls back to the SPA's `index.html`.

## Reports & export
A Reports page with cost per year × category (bar chart + table), cost per km, and km per year. CSV exports. A printable service history for resale at the `/vehicles/:id/history` route, with print CSS.

## Project layout
```
vehicle-tracker/
  docker-compose.yml  Dockerfile  .env.example  README.md
  backend/
    pyproject.toml  alembic/
    app/ main.py config.py db.py models.py seed.py scheduler.py evaluator.py
         domain/ (due, mileage_parser, status)   services/   api/   bot/
         notify/   feed/                          # reusable, domain-free
    tests/
  frontend/
    package.json  vite.config.ts
    src/ api/ (generated types + query hooks)  layout/ (AppShell)  pages/  components/
  data/ (volume) tracker.sqlite3  receipts/
```

## Deployment & security
- Compose port: `"${BIND_ADDR:-127.0.0.1}:8000:8000"`. The README covers setting `BIND_ADDR` to the LAN IP, plus a reverse-proxy snippet (Caddy with basic auth).
- Secrets live only in a git-ignored `.env`. `.env.example` is committed.
- Uploads: 20 MB cap, MIME sniffing (jpeg/png/webp/heic/pdf), uuid filenames.
- Backup: the `sqlite3 .backup` command (safe while the app is running) + a tar of `receipts/`, with a cron example and restore steps.

## Later (not in MVP)
Fuel log, ICS calendar feed, weekly digest, warranty tracking, specs card, VIN decode, recalls, OBD.

## Build steps (run after each)
- [x] 1. Scaffold backend + frontend, `/healthz`, multi-stage Dockerfile, compose → the SPA shell loads via `docker compose up`
- [x] 2. Models + migration + seed (1 vehicle with readings, services, rules, date items, 2 tire sets)
- [x] 3. `due.py` + tests
- [x] 4. Vehicle/dashboard API + AppShell, dashboard and vehicle pages → **screenshot checkpoint**
- [x] 5. Odometer and service forms with receipt upload, plus the Quick log
- [x] 6. Rules, date items + Mark done, tire sets
- [x] 7. Evaluator + outbox + notifiers + transition/snooze tests
- [x] 8. Telegram bot: parser, vehicle guess, callbacks, receipt intake + tests
- [x] 9. Reports, CSV, printable history, status feed
- [x] 10. README

## Verification
- `pytest`: due logic (km, time, whichever-first, missing data, backwards odometer, month clamping), mileage parser, vehicle guess, evaluator (no repeats, new cycle after service, single re-alert after snooze), tire km and the one-mounted rule, report cost allocation, API smoke tests.
- Frontend: `tsc --noEmit` + a production build. A Playwright smoke test at 1280px and 390px: open the dashboard, log a service with a JPEG/PDF, check the file lands in `data/receipts`.
- With `NOTIFIER=log`, push the odometer past a threshold. The outbox should get exactly one alert, and a second evaluation run should add none.
- Real Telegram round trip (needs your token and chat ID in `.env`): text `84,500 km`, get the confirmation, cross a threshold, receive the alert, then tap **Done today**.
