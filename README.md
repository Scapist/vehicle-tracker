# Vehicle Maintenance Tracker

Self-hosted tracker for mileage, services, costs, receipts and tire sets. It warns you ahead of time
(by km, by date, or whichever comes first) through Telegram, and you can text it your odometer reading.

- **Backend:** FastAPI, SQLAlchemy 2 + Alembic, SQLite (WAL), APScheduler, python-telegram-bot
- **Frontend:** React + Vite + TypeScript, Mantine (responsive, dark mode, installable PWA)
- **One container, one port.** Units are km and CAD; times are stored in UTC and shown in `America/Toronto`.

## Run it

```sh
cp .env.example .env      # optional; defaults work for a first look
docker compose up -d --build
```

Open <http://localhost:8000>. API docs are at `/docs`. Data lives in `./data` (SQLite file + `receipts/`).
The database is migrated automatically on start. The first vehicle is added in the app (Vehicles → Add vehicle).

### Reach it from your phone (LAN)

By default the port is bound to `127.0.0.1`. Set your server's LAN IP in `.env`:

```
BIND_ADDR=192.168.1.50
```

The app has **no login**; keep it on the LAN. If you expose it further, put a reverse proxy with auth in front.
Caddy example with basic auth (`caddy hash-password` makes the hash):

```
tracker.home.lan {
    basicauth {
        me <hashed-password>
    }
    reverse_proxy 127.0.0.1:8000
}
```

On a phone, use "Add to Home Screen" to install it as an app.

## Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Find your chat ID (message [@userinfobot](https://t.me/userinfobot)).
3. In `.env`:

```
NOTIFIER=telegram
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_CHAT_IDS=111111111          # comma-separated; everyone else is ignored
```

4. `docker compose up -d` again.

The bot uses long polling, so no public URL is needed. What it understands:

| You send | Result |
|---|---|
| `84500`, `84,500 km`, `84 500`, `84.500`, `84.5k` | Logs mileage. With several vehicles it picks the one whose current km is the closest below, and replies with a **Wrong vehicle** button. |
| `civic 84500` / `84500 civic` | A nickname always wins. |
| A lower number | Asks "Is that a correction?" |
| A jump of more than 5,000 km | Asks you to confirm. |
| A photo or PDF | Attached to the latest service from the last 7 days, or saved as a receipt-only entry. |
| `/due`, `/vehicles`, `/help` | Status commands. |

Alerts arrive with **Done today** (logs the service at the current km) and **Snooze 7 d** buttons.
An alert fires once when an item moves into *due soon* or *overdue*; logging a service starts a new cycle,
and a snoozed item that is still due re-alerts once after the snooze ends. With `NOTIFIER=log` (the default)
alerts are only written to the container log, which is handy for testing.

## How reminders work

Each reminder has a km interval, a months interval, or both (whichever comes first), plus "warn this far ahead"
windows. The date for a km limit is estimated from your average km/day over the last 90 days (falling back to all
history). If there isn't enough data it says so instead of guessing. A reminder with no service history and no
"last done" baseline shows as *Unknown* until you log one. The odometer can't go backwards unless you mark the
entry as a correction.

Winter tires: "Add winter-tire reminders" on a vehicle's *Reminders & dates* tab creates "Install by Dec 1" and
"Can remove after Mar 15". Marking either done asks which tire set is on the car.

## Backup and restore

```sh
# safe while the app is running
sqlite3 data/tracker.sqlite3 ".backup 'backup/tracker-$(date +%F).sqlite3'"
tar czf backup/receipts-$(date +%F).tgz -C data receipts
```

Cron example (daily 03:00):

```
0 3 * * * cd /srv/vehicle-tracker && mkdir -p backup && sqlite3 data/tracker.sqlite3 ".backup 'backup/tracker-$(date +\%F).sqlite3'" && tar czf backup/receipts-$(date +\%F).tgz -C data receipts
```

Restore: `docker compose down`, put the `.sqlite3` back as `data/tracker.sqlite3` (delete any `-wal`/`-shm` files next to it),
extract the receipts tarball into `data/`, then `docker compose up -d`.

## Development

```sh
# backend (needs uv)
cd backend && uv sync
uv run pytest
uv run alembic upgrade head && uv run python -m app.seed --demo   # demo data in ../data
uv run uvicorn app.main:app --reload

# frontend (separate terminal; proxies /api to :8000)
cd frontend && npm install && npm run dev
npm run build            # tsc --noEmit + production build
npm run e2e              # Playwright at 1280px and 390px; also writes docs/screenshots
```

After changing API models, regenerate the TypeScript types:

```sh
cd backend && uv run python -c "import json;from app.main import app;print(json.dumps(app.openapi()))" > ../frontend/openapi.json
cd ../frontend && npm run gen:api
```

Schema changes: `cd backend && uv run alembic revision --autogenerate -m "what changed"`.

### Layout

`backend/app/domain` is pure logic (due dates, mileage parsing); `services` hold DB logic; `api` are the routes;
`bot` is the Telegram side. `app/notify` (Notifier protocol, Telegram/log senders, outbox with retry) has no
imports from the vehicle code so other tools can reuse it. `GET /api/v1/status` is the normalized feed
(`source, subject, title, status, due, detail_url`) for a shared dashboard.

## Limits

20 MB per upload; JPEG, PNG, WebP, HEIC and PDF only (checked by file content). HEIC files are stored and
downloadable but not previewed in the browser.
