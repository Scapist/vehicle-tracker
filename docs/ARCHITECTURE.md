# Architecture

How the tracker is put together, and why. Read the sections in order: each builds on the one before.
For running and configuring it, see the [README](../README.md).

## 1. The big picture

There are three ways in, and they all lead to the same core:

```
   Browser (React app)          Telegram (your phone)          Clock (08:00 daily)
          │ HTTP/JSON                    │ long polling                  │
          ▼                              ▼                               ▼
   ┌─────────────┐              ┌─────────────────┐            ┌──────────────┐
   │  API routes │              │   Bot handlers  │            │  Scheduler   │
   │ backend/app/│              │ backend/app/bot/│            │ scheduler.py │
   │    api/     │              └────────┬────────┘            └──────┬───────┘
   └──────┬──────┘                       │                            │
          └──────────────┬───────────────┴────────────────────────────┘
                         ▼
              ┌─────────────────────┐      ┌───────────────────┐
              │  services/  (logic  │─────▶│ domain/ (pure     │
              │  that uses the DB)  │      │ math, no DB)      │
              └──────────┬──────────┘      └───────────────────┘
                         ▼
              ┌─────────────────────┐
              │ SQLite + receipts/  │   ./data on disk
              └─────────────────────┘
```

Everything runs as **one Python process in one Docker container**. FastAPI serves the API (`/api/v1/...`) and the
built React files. The Telegram bot and the scheduler run on background threads inside that same process
(started in the `lifespan` function in `backend/app/main.py`).

**Why one container?** On a home server, one process is much simpler to run, back up and debug than separate
frontend, backend and worker services. The trade-off is that it can't scale out across machines, which this app
will never need. Choosing simplicity on purpose is a real architectural decision.

## 2. Backend layers

The backend is split into layers, and **dependencies only point downward**:

| Layer | Folder | Knows about | Example |
|---|---|---|---|
| Pure logic | `app/domain/`, `app/bot/parser.py` | Nothing: plain values in, plain values out | `compute_due(rule, anchor, current_km, readings, today)` |
| Services | `app/services/` | The database and the domain | `services/status.py` loads rules and history, calls `compute_due`, returns `StatusItem`s |
| Entry points | `app/api/`, `app/bot/`, `app/scheduler.py` | HTTP, Telegram, time | `api/rules.py` turns `POST /rules/1/done` into a service call |

**Pure logic** is the "functional core". `domain/due.py` gets everything it needs as arguments, *including
today's date*, so it has no hidden inputs. `tests/test_due.py` just calls it with values and checks the answer,
with no database, mocks or clock tricks. The trickiest rules live there on purpose: month clamping
(Aug 31 + 6 months = Feb 28), km-per-day estimation, and "whichever comes first".

**One source for every cost.** `services/reports.cost_entries` turns services, tire purchases and recurring
payments into one list of dated entries. The yearly report, the spending filters, the monthly chart and the CSV
are all built from that list, so they can't disagree.

**Entry points stay thin**: validate input, call a service, format output. That's why `mark_rule_done` in
`api/rules.py` serves both the web **Done today** button and the Telegram one. Logic written inside an HTTP
handler would have to be copied for the bot.

## 3. Data model

Tables are SQLAlchemy classes in `backend/app/models.py`:

```
User ─┬─< Vehicle ─┬─< OdometerReading
      │            ├─< ServiceRecord ─┬─< ServiceRecordItem >── ServiceType
      │            │                  └─< Attachment (receipt file)
      │            ├─< ReminderRule >── ServiceType
      │            ├─< DateItem (registration, insurance, winter tires)
      │            ├─< RecurringCost (auto-paid insurance, financing…)
      │            └─< TireSet ─┬─< TireMount
      │                         └─< TireTread
      └─< Invite
AlertState, NotificationOutbox   (alert machinery, section 5)
```

Decisions worth noticing:

- **Money is integer cents** (`cost_cents`), never a float. Floats can't represent 0.10 exactly.
- **The odometer is a history, not a single number.** Current km is the latest valid reading. The history makes
  the km/day estimate possible. A correction doesn't delete anything: it marks higher readings `invalidated`.
- **One visit, many jobs.** `ServiceRecordItem` is a join table: one visit (oil change plus rotation) links to
  several service types, each with an optional cost.
- **Times are stored in UTC and shown in local time** (`app/clock.py`). Mixed time zones in storage cause
  "off by one day" bugs around midnight.
- **Recurring payments store a rule, not rows.** A `RecurringCost` says "$142 every month from Jan 5"; the
  individual payments are calculated when needed (`domain/recurring.py`). A price change ends one row and starts
  another, so past payments keep their old price without a separate history table.
- **Receipts are files, not blobs.** They're saved under `data/receipts/YYYY/<uuid>.<ext>`; the database keeps
  the name, type and sha256.

### Migrations

`backend/alembic/versions/` holds versioned scripts that change the schema: `0001` creates the tables, `0002`
adds accounts and per-user data. They run automatically at startup (`run_migrations` in `main.py`), after
a backup to `data/backups/`.

SQLite can't alter some structures in place, so Alembic rebuilds the table: create a new one, copy the rows, drop
the old one. With foreign keys switched on, dropping the old `vehicle` table **cascade-deleted every reading,
service and rule**. This was caught by running the migration on a copy of real data. The fix in `alembic/env.py`:
foreign keys are off during migrations, and `PRAGMA foreign_key_check` runs afterwards and fails loudly if anything
is broken. `tests/test_migrations.py` keeps it fixed.

## 4. One request, end to end

What happens when you click **Done today** on "Oil change":

1. **React** (`frontend/src/components/ItemCard.tsx`) calls `api("/rules/1/done", { method: "POST" })`.
2. **`frontend/src/api/client.ts`** sends it; the browser attaches the session cookie automatically.
3. **Middleware** (`main.py`, `security.py`) runs before any route code, outermost first:
   - `BodySizeLimit` counts the bytes received and stops oversized uploads;
   - `TrustedHostMiddleware` rejects host names not in `ALLOWED_HOSTS`;
   - `guard` blocks cross-site writes, does a cheap cookie-signature check, and adds safety headers.
4. **Routing** matches `POST /api/v1/rules/{rule_id}/done` in `api/rules.py`.
5. **Dependency injection.** The route declares `user = Depends(current_user)` and `db = Depends(get_db)`.
   FastAPI runs those first: `current_user` (`auth.py`) verifies the cookie and loads your `User`, and `get_db`
   opens a database session. Routes stay short, and tests can swap in a test database
   (`app.dependency_overrides` in `tests/conftest.py`).
6. **Ownership check.** `owned_rule(db, user, 1)` (`api/deps.py`) confirms the rule's vehicle is yours. If not,
   the answer is **404**, never 403, so nobody can probe which IDs exist. Every ownership rule goes through
   `find_owned_vehicle`, so there is one place to get it right.
7. **Service logic.** `mark_rule_done` logs a service record at today's date and the current km.
8. **Alerts re-checked.** `services/evaluator_hook.after_change` re-evaluates your reminders (section 5).
9. **Response.** The record goes out through a Pydantic schema (`schemas.py`), which controls exactly which fields
   leave the server.
10. **Back in React**, the data is refreshed and an **Undo** toast appears. Undo sends `DELETE /services/{id}`.

Every endpoint follows the same shape: thin route → dependencies → ownership check → service → schema.

## 5. Alerts

The goal is to alert **exactly once** when something becomes due soon or overdue: no spam, nothing missed. There
are three steps, each in its own place.

**Decide: `app/evaluator.py`.** For each reminder it computes the current status and compares it with what it
recorded last time (`AlertState`).

- It's a small state machine, ok → due soon → overdue. It alerts only when moving *up*. Ten days overdue is one
  alert, not ten.
- `cycle_key` identifies one round of a reminder, based on when it was last done. Logging a service starts a new
  cycle, so the next "due soon" alerts again.
- Snooze sets `snoozed_until`; when that passes and the item is still due, it re-alerts once (`realerted`).

**Queue: the outbox pattern, `app/notify/outbox.py`.** The evaluator never sends anything. It writes a row to
`NotificationOutbox`, and `dispatch` (every 30 s) sends pending rows.

- Deciding and sending are separate, so a Telegram outage doesn't lose the alert. The row stays pending and is
  retried with growing delays.
- `dedupe_key` is unique, so the same alert can't be queued twice even if two evaluations race.
- The recipient is stored as `user:5`, not a chat ID, and resolved when sending (`resolve_recipient`). If you
  relink Telegram, queued alerts follow you. If you haven't linked yet, alerts wait (up to 7 days) instead of
  being dropped.

**Send: `app/notify/base.py`.** `Notifier` is a protocol (an interface) with two implementations:
`TelegramNotifier`, and `LogNotifier`, which just logs and is used in development and tests.
**`app/notify/` never imports vehicle code**, so it can be reused by other tools. The evaluator knows about
vehicles; the notify package only knows "send this text to this address".

## 6. The Telegram bot

The same pure → logic → glue layering:

| File | Role | Needs Telegram to test? |
|---|---|---|
| `bot/parser.py` | Text → number (`84,500 km`, `84.5k`); guesses which vehicle. Pure. | No |
| `bot/logic.py` | "Given this user and this message, what happens and what's the reply?" Returns a `Reply(text, buttons)`. | No, just a test database |
| `bot/runner.py` | python-telegram-bot glue: receives updates, finds the user by chat ID, calls `logic`, sends the reply. | Kept too thin to need it |

The network is pushed to a thin edge, so the bot tests never talk to Telegram.

Button presses carry raw IDs (`done:rule:12`), and anyone can craft one. So `logic.py` re-checks ownership on
**every** callback. Never trust data just because your own code produced it earlier.

## 7. Accounts and security

### Accounts (`app/auth.py`)

- **Passwords** are hashed with scrypt and a random salt. Only a slow, one-way fingerprint is stored.
- **Sessions** are a signed cookie: `user_id.version.expiry.signature`. The HMAC signature means it can't be
  forged or edited. `HttpOnly` keeps JavaScript from reading it; `SameSite=Lax` keeps other sites from sending it
  with their forms. No session table is needed.
- **`session_version`** is in both the cookie and the database. Changing the password or "sign out everywhere"
  increments it, which instantly invalidates every older cookie.
- **The setup code** is printed in the log when there are no accounts. It keeps someone else on the network from
  claiming the owner account first.
- **Invites** store only a hash of the link's secret, so a leaked database doesn't reveal working links. Claiming
  one is a single conditional `UPDATE`, so two people can't use the same link at once.
- **Lockouts** slow down password guessing per device and per device+email pair.

### Defense in depth (`app/security.py` and others)

| Threat | Protection |
|---|---|
| DNS rebinding (a malicious site pointing its domain at your server) | Host allowlist (`ALLOWED_HOSTS`) |
| CSRF (another site making your browser submit requests) | Origin / `Sec-Fetch-Site` check on writes, plus `SameSite` cookies |
| Disk or memory exhaustion | Byte-counting body limit, per-file size and count caps, container memory limit |
| Malicious uploads | File type detected from the bytes, not the name; uuid file names; `nosniff` and CSP headers |
| Formula injection in CSV exports | Cells starting with `= + - @` (and tab/CR) get a leading `'` |
| Token leaks | Bot token redacted from logs and stored errors |
| Container compromise | Runs as uid 10001 with all capabilities dropped |

No single protection is perfect, so they're layered.

## 8. The frontend (`frontend/src/`)

React and TypeScript, with Mantine for components, dark mode and responsive layout; React Router for pages; and
TanStack Query for server data.

**TanStack Query is the main idea.** Components don't keep API data in their own state. They call a hook such as
`useDashboard(id)` (`api/hooks.ts`), and the library fetches, caches and refreshes the data. After a change,
`useInvalidate()` marks the cache stale and screens refetch. This removes a whole class of "the screen shows old
data" bugs.

**Generated types.** `api/schema.d.ts` is generated from the backend's OpenAPI description (`npm run gen:api`).
If the backend renames a field, the TypeScript build fails instead of the app breaking quietly. The contract
between frontend and backend is checked by the compiler.

**Structure:**

- `main.tsx` sets up providers: theme, notifications, query cache, router.
- `App.tsx` wraps everything in `AuthGate` (setup, login or sign-up until you're signed in), then
  `QuickLogProvider`, a React context so any button can open the Quick log.
- `layout/Shell.tsx`: sidebar on desktop, bottom tabs on phones.
- `pages/`: one file per screen. `components/`: reusable pieces.

## 9. Tests

| Kind | Where | What it gives you |
|---|---|---|
| Unit | `test_due.py`, `test_parser.py` | Fast, exhaustive checks of the pure logic |
| API | `test_api.py`, `test_accounts.py`, `test_security.py` | FastAPI `TestClient` against an in-memory SQLite database, fresh per test |
| Bot | `test_bot.py`, `test_bot_wiring.py` | Bot logic without Telegram; handlers are registered |
| Regression | `test_review_fixes.py`, `test_review2_fixes.py` | One test per bug found in review, so each stays fixed |
| Migration | `test_migrations.py` | Runs the real migration on a database with rows and compares counts |
| End-to-end | `frontend/e2e/smoke.spec.ts` | Playwright drives a real browser at desktop and phone sizes |

`tests/conftest.py` builds the fixtures (`demo`, `client`, `demo_client`, ...) and freezes time with
`time_machine`, so date logic gives the same answer on every run.

Several real bugs were caught by tests rather than by reading code: the sign-in screen that didn't advance, the
Telegram relink crash, the lockout using the wrong limit, and the upload cap FastAPI was silently bypassing.

## 10. Packaging

`Dockerfile` is a **multi-stage build**: a Node stage builds the React app, then a Python stage installs the
backend with `uv` and copies in only the built files. Node isn't in the final image.

`docker-entrypoint.sh` starts as root only long enough to make `./data` writable for the app user, then drops to
uid 10001 with no capabilities. `docker-compose.yml` publishes the port on `BIND_ADDR`, mounts `./data`, and sets
the resource and security limits.

## 11. Lessons from building it

- **Test migrations on a copy of real data.** The SQLite table rebuild with foreign keys on deleted child rows.
- **Frameworks can swallow your errors.** Raising inside the body-size limit became a 400 because FastAPI turns
  any form-parsing error into one. The fix was to send the 413 directly.
- **Order of writes matters with unique constraints.** Moving a Telegram chat to another account failed until the
  old link was cleared (flushed) before setting the new one.
- **Small naming choices have real effects.** A lockout key starting with `ip:` silently got the looser per-device
  limit.
- **Don't drop what you can't deliver yet.** Alerts for users without a linked chat were first discarded; now they
  wait.

## Suggested reading order

1. `backend/app/domain/due.py` with `backend/tests/test_due.py`: pure logic next to its tests.
2. `backend/app/models.py`: the data.
3. `backend/app/api/vehicles.py` and `backend/app/api/deps.py`: the request pattern.
4. `backend/app/auth.py`: passwords and sessions.
5. `backend/app/evaluator.py` and `backend/app/notify/outbox.py`: the state machine and the outbox.
6. `backend/app/bot/logic.py`: the same core through a different door.
7. `frontend/src/api/hooks.ts`, then `frontend/src/pages/VehiclePage.tsx`: how the UI gets its data.

## Exercises

- **Easy:** add a `color` field to vehicles. You'll touch the model, a migration, the schema, the form and the
  generated types. See what the compiler complains about.
- **Medium:** add a `/km` bot command that shows km driven this month: `bot/logic.py`, `bot/runner.py`, a test.
- **Harder:** a mileage nudge. A scheduler job finds vehicles with no reading in 14 days and queues an outbox
  message.
