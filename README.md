# Vehicle Maintenance Tracker

Self-hosted tracker for mileage, services, costs, receipts and tire sets. It warns you ahead of time
(by km, by date, or whichever comes first) through Telegram or Discord, you can text it your odometer reading,
and an AI assistant such as Claude can read and log for you over MCP.

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

### Accounts

Each person has their own account and their own, completely separate vehicles, records and receipts.

1. **First start.** With no accounts yet, the server prints a one-time setup code in its log:

   ```sh
   docker compose logs tracker | grep -A1 "setup code"
   ```

   Open the app, enter that code and create your account. You become the **owner**. Anything entered before
   accounts existed (from an older version) is attached to this account.
2. **Inviting someone.** In Settings → *Invite people*, create a link and send it to them. Each link makes one
   account and expires after 7 days. There is no open sign-up.
3. **Signing in** keeps a device signed in for 30 days. Changing your password signs out your other devices;
   *Sign out on all devices* does the same without a password change. After five wrong passwords, sign-in from
   that device or for that email is paused for a growing time (30 s up to 15 min).

Passwords are stored as salted scrypt hashes. Nothing about accounts lives in `.env`.

### Reach it from your phone

The login protects your data, but traffic on plain `http://` is unencrypted on your Wi-Fi.
By default the app only listens on `127.0.0.1`, so only the machine running it can open it.
It only answers to host names in `ALLOWED_HOSTS` (default `localhost,127.0.0.1`) and refuses cross-site
writes, so a website you visit can't use your browser to change or read your data.

Pick one way to reach it from your phone:

- **Tailscale (recommended).** Install Tailscale on the server and your phone, keep `BIND_ADDR=127.0.0.1`,
  and run `tailscale serve --bg 8000` on the server. Add the server's tailnet name to `ALLOWED_HOSTS`
  (e.g. `ALLOWED_HOSTS=localhost,127.0.0.1,myserver.tailnet-name.ts.net`). Only your own devices can reach it,
  over an encrypted connection, from anywhere.
- **Straight on the LAN.** Set `BIND_ADDR` and add the same address to `ALLOWED_HOSTS`:

  ```
  BIND_ADDR=192.168.1.50
  ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50
  ```

  Devices on your Wi-Fi then need the password, but traffic (including the password when you sign in) is
  unencrypted plain HTTP. Fine on a home network you trust; put guests and IoT devices on a separate guest network.
- **Reverse proxy with a password.** Keep `BIND_ADDR=127.0.0.1` (otherwise the proxy can be bypassed on port 8000)
  and let only the proxy listen on the LAN. Caddy example (`caddy hash-password` makes the hash):

  ```
  tracker.home.lan {
      basicauth {
          me <hashed-password>
      }
      reverse_proxy 127.0.0.1:8000
  }
  ```

  Add `tracker.home.lan` to `ALLOWED_HOSTS`. Any name you open the app by must be listed there: it is also
  how the app recognises its own pages when a proxy rewrites the `Host` header (nginx does by default).
  If the proxy runs on another machine or in another container, also set `FORWARDED_ALLOW_IPS` to the proxy's
  IP, so sign-in limits apply to each real device rather than to the proxy as a whole.

On a phone, use "Add to Home Screen" to install it as an app.

The app runs as an unprivileged user (uid 10001). On start, the container hands `./data` to that user if needed
(for example when it was created by your own account or an older image), then drops all privileges.
Before applying a database migration it saves a copy in `data/backups/`.

## Chat apps: Telegram and Discord

You can use either or both. Each person links their own apps in Settings → **Chat apps**, can text their km to any
of them, and picks one under **Send alerts to** when both are linked. The bots only answer direct messages, and
only for linked accounts.

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. In `.env`, then `docker compose up -d`:

   ```
   NOTIFIER=telegram
   TELEGRAM_BOT_TOKEN=123456:ABC...
   ```

3. Each person links their own Telegram: in the app, Settings → Telegram → **Connect** shows a code; send
   `/link CODE` to the bot. The bot then answers that chat as that account (their vehicles only) and sends
   their alerts there. Unlinked chats only get instructions on how to link, and group chats are ignored.

### Discord

1. At <https://discord.com/developers/applications> create an application, open **Bot**, reset and copy the
   token, and turn **Public Bot** off (so only you can add it anywhere). No privileged intents are needed.
2. In `.env`, then `docker compose up -d`:

   ```
   NOTIFIER=telegram          # any value except "log" turns the chat apps on
   DISCORD_BOT_TOKEN=...
   # optional: ignore every Discord user except these ids
   # DISCORD_ALLOWED_USER_IDS=123456789012345678
   ```

3. Open a DM with the bot: in the developer portal, **Installation** → install it as a *User Install* and open the
   link, or share a server with it, then right-click the bot → *Message*.
4. In the app, Settings → Chat apps → Discord → **Connect**, and send the bot the `!link CODE` it shows.

Commands are `!due`, `!vehicles` and `!help`; everything else (km readings, receipt files, buttons) works as on
Telegram.

Both bots connect out to Telegram/Discord, so no public URL is needed. What they understand:

| You send | Result |
|---|---|
| `84500`, `84,500 km`, `84 500`, `84.500`, `84.5k` | Logs mileage. With several vehicles it picks the one whose current km is the closest below, and replies with a **Wrong vehicle** button. |
| `civic 84500` / `84500 civic` | A nickname always wins. |
| A lower number | Asks "Is that a correction?" |
| A jump of more than 5,000 km | Asks you to confirm. |
| A photo or PDF | Attached to the latest service from the last 7 days, or saved as a receipt-only entry. |
| `/due`, `/vehicles`, `/help` | Status commands. |

**Mileage nudge.** Km-based reminders are only as accurate as the latest reading, so if a vehicle with a km
reminder has had no reading for 2 weeks, the bot asks for the odometer at 18:00 (and again every 2 weeks while
it stays quiet). Just reply with the number. Change the interval or turn it off per vehicle on its *Odometer*
tab, or tap **Stop asking** on the message.

Alerts arrive with **Done today** (logs the service at the current km) and **Snooze 7 d** buttons.
An alert fires once when an item moves into *due soon* or *overdue*; logging a service starts a new cycle,
and a snoozed item that is still due re-alerts once after the snooze ends. With `NOTIFIER=log` (the default)
alerts are only written to the container log, which is handy for testing.

## AI assistants (MCP)

The app can act as an [MCP](https://modelcontextprotocol.io) server, so an assistant such as Claude can answer
"when is my next oil change?" or "log an oil change today at 85,000 km, $86.40 at Speedy". Show Claude a receipt
photo and it can read it and log it for you.

It can read your vehicles, what's due, service history and spending, log odometer readings and services, and
attach receipts. It **can't edit or delete** anything. It acts as one account and sees only that account's data.

1. In `.env`: `MCP_ENABLED=true`, then `docker compose up -d`. By default (`MCP_USERS=owner`) only the owner
   account can use it; `MCP_USERS=all` lets every account make their own tokens.
2. In the app, Settings → **AI assistants** → **Create token**. Copy it: it's shown once (only a hash is stored).
   Revoke it there if it leaks.
3. Connect your assistant (the Settings card shows these with your address filled in):

   ```sh
   # Claude Code
   claude mcp add --transport http tracker http://<your-server>:8000/mcp --header "Authorization: Bearer <token>"
   ```

   Claude Desktop, in `claude_desktop_config.json` (`mcp-remote` runs on your computer and forwards to the server):

   ```json
   { "mcpServers": { "tracker": { "command": "npx", "args": ["mcp-remote", "http://<your-server>:8000/mcp",
     "--allow-http", "--header", "Authorization:Bearer <token>"] } } }
   ```

`/mcp` is on the same port as the app, so it's exactly as reachable as the app: with the default `BIND_ADDR` and a
LAN or Tailscale setup, nothing on the internet can reach it, and every request needs a token on top. Assistants
that run in the cloud (claude.ai, the Claude phone app) need a public HTTPS address with OAuth sign-in, which
this version doesn't offer.

## How reminders work

Each reminder has a km interval, a months interval, or both (whichever comes first), plus "warn this far ahead"
windows. The date for a km limit is estimated from your average km/day over the last 90 days (falling back to all
history). If there isn't enough data it says so instead of guessing. A reminder with no service history and no
"last done" baseline shows as *Unknown* until you log one. The odometer can't go backwards unless you mark the
entry as a correction.

Winter tires: "Add winter-tire reminders" on a vehicle's *Reminders & dates* tab creates "Install by Dec 1" and
"Can remove after Mar 15". Marking either done asks which tire set is on the car.

## Services

Built in: oil change, tire rotation, brake inspection, engine and cabin air filters, battery, wheel alignment,
transmission fluid, coolant, spark plugs, brake fluid and wiper blades. For anything else, type its name in
"What was done?" (or in a reminder's Service field) and pick **+ Add "…"**. Your own services are only visible
to you, work for reminders, and get their own line in Reports. Rename or delete them in Settings → *Your
services*; one that's already in your history or a reminder can only be renamed.

## Spending and recurring payments

**Reports** shows what you spent in a period (this month, last month, this year, last year, the last 12 months
or a custom range), filtered by vehicle and category. It has a month-by-month chart, a breakdown by category,
every entry, and a `spending.csv` export of exactly what's on screen. The filters are kept in the address, so
you can bookmark a view.

Payments taken automatically (insurance, financing, registration, parking…) go on a vehicle's **Payments** tab:
the amount, how often (every 1, 3, 6 or 12 months), the first payment and, optionally, the last one. Each payment
counts as spent on its date with nothing to confirm; ones still to come in the period are shown as *scheduled*.
**Change amount…** starts a new price from a date and keeps earlier payments at the old one. Archiving a vehicle
ends its payments. Yearly payments can send a Telegram heads-up a set number of days before they renew.

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

## Deploy to the home server

The server (`<user>@<server-ip>`) has a git repo with a deploy hook. `origin` pushes to both GitHub and the
server, so shipping a change is a normal push:

```sh
git push               # GitHub + server (deploys)
git push home main     # server only
```

The push output shows the deploy. The hook snapshots the database to `data/pre-deploy/` (last 10 kept),
checks out the code into `~/vehicle-tracker`, rebuilds, and waits for `/healthz`. If the new version doesn't
become healthy, it puts the previous code and database back and restarts that instead. `.env` and `data/` on
the server are never touched. Only `main` deploys; pushes of other branches are ignored.

One-time setup on a new PC (needs your SSH key on the server):

```sh
git remote add home <user>@<server-ip>:git/vehicle-tracker.git
git remote set-url --add --push origin https://github.com/Scapist/vehicle-tracker.git
git remote set-url --add --push origin <user>@<server-ip>:git/vehicle-tracker.git
```

The server is only reachable on the home network, so away from home the server half of `git push` fails
(GitHub still updates); push again once you're back. The hook itself lives at `~/git/vehicle-tracker.git/hooks/post-receive`.

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
For a guided tour of the design, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Limits

20 MB per upload; JPEG, PNG, WebP, HEIC and PDF only (checked by file content). HEIC files are stored and
downloadable but not previewed in the browser.
