# CLAUDE.md

Context for AI coding assistants (and humans) working on this repository. Read this first; read
`docs/ARCHITECTURE.md` for the longer guided tour.

## What this is

A self-hosted vehicle maintenance tracker. People record vehicles, odometer readings, services (with receipt
files), maintenance reminders (by km and/or months), dates (insurance, registration, winter tires), tire sets and
automatic payments. The app computes what's *ok / due soon / overdue / unknown* and alerts through Telegram or
Discord bots. An MCP server lets AI assistants read and add data. Multi-user (invite-only), each account fully
isolated. Units: km and dollars. Single Docker container, SQLite.

## Stack and layout

```
backend/                 Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite (WAL), APScheduler
  app/
    main.py              app wiring: middleware, routers, /mcp route, lifespan (migrations, scheduler, bots, MCP)
    config.py            settings from env (.env): TIMEZONE, NOTIFIER, bot tokens, MCP_ENABLED, ...
    models.py            all SQLAlchemy models
    schemas.py           Pydantic request/response models (the API contract)
    auth.py              accounts, sessions (signed cookie), invites, chat-app link codes
    security.py          host/CSRF guard, body size limit, log redaction
    domain/              PURE logic, no DB: due-date math (due.py), status, recurring payment dates
    services/            DB logic shared by API, bots and MCP: status.py (what's due), records.py, odometer.py,
                         reports.py (cost_entries is the single source for money), evaluator_hook.py
    api/                 HTTP routes; deps.py has ALL ownership checks (owned_vehicle, owned_service, ...)
    evaluator.py         decides when to alert (state per subject + cycle), writes to the outbox
    notify/              domain-free sending: Notifier protocol, Telegram/Discord/Routing notifiers, outbox
    bot/                 logic.py (channel-agnostic bot behaviour) + runner.py (Telegram) + discord_runner.py
    mcp_server.py        MCP tools (read/log/receipts) + bearer-token auth + one-time upload page
    mcp_setup.py         MCP setup tools (add vehicle/reminder/date/tire set/payment); call the API route functions
    nudge.py, scheduler.py   daily jobs (08:00 alerts, 18:00 odometer nudges, outbox every 30 s)
  alembic/versions/      migrations 0001..NNNN (backed up automatically before running)
  tests/                 pytest; conftest.py has fixtures (db, user, client, demo) and freezes time at 2026-11-11
frontend/                React + Vite + TypeScript + Mantine + TanStack Query
  src/api/               client.ts (fetch wrapper), hooks.ts, schema.d.ts (GENERATED from openapi.json)
  src/pages/             Dashboard, Vehicles, VehiclePage (tabs), Tires, Reports, Settings, History
  src/components/        shared UI (QuickLog, ItemCard, ChatAppsCard, AssistantsCard, ...)
  e2e/smoke.spec.ts      Playwright tests at desktop and phone sizes; also writes docs/screenshots
docs/                    GUIDE.md (users), DEPLOY.md (operators), ARCHITECTURE.md (design)
```

Data model in one line: `User` owns `Vehicle`s; a vehicle has `OdometerReading`s, `ServiceRecord`s (with
`ServiceRecordItem`s per `ServiceType` and `Attachment`s), `ReminderRule`s (one per service type), `DateItem`s,
`TireSet`s and `RecurringCost`s. `ServiceType.user_id` NULL = built-in, otherwise that user's custom type.

## Commands

```sh
cd backend
uv sync                                   # install
uv run pytest -q                          # all backend tests (must pass)
uv run uvicorn app.main:app --reload      # dev server on :8000 (uses ../data)
uv run alembic revision -m "what"         # new migration (write it by hand; see rules below)

cd frontend
npm install
npm run dev                               # Vite on :5173, proxies /api to :8000
npm run build                             # tsc --noEmit + build (must pass)
npm run e2e                               # Playwright (builds nothing: run `npm run build` first)
npm run gen:api                           # regenerate src/api/schema.d.ts from openapi.json

# after changing any API schema or route:
cd backend && uv run python -c "import json;from app.main import app;print(json.dumps(app.openapi()))" > ../frontend/openapi.json
cd ../frontend && npm run gen:api
```

## Rules that matter

1. **Ownership on every access.** Anything reached by id goes through `app/api/deps.py` (`owned_vehicle`,
   `owned_service`, ...) or filters by `user_id`. Someone else's object is a **404, never a 403** (ids can't be
   probed). Bot callbacks and MCP tools re-check ownership too; never trust an id because your own code made it.
2. **One place per rule.** Business logic lives in `services/` or `domain/`, not in routes, bots or MCP tools.
   The bots and MCP call the same functions as the API (the MCP setup tools literally call the route
   functions), so behaviour stays identical. `reports.cost_entries` is the only source for money figures.
3. **Pure where possible.** `domain/` has no database access and gets plain unit tests.
4. **Migrations must be safe on existing data.** Prefer plain `op.add_column` / new tables. SQLite table rebuilds
   (`batch_alter_table`) run with foreign keys OFF (see `alembic/env.py`), never cascade-delete. Add a test to
   `tests/test_migrations.py` (it asserts the head revision) and bump the expected head.
5. **No secrets in code, tests, logs or fixtures.** Use fake values (`1:x`, `5550001234`, `@example.com`).
   Tokens are redacted from logs by `security._TOKEN`; keep new token formats covered.
6. **Alerts go through the outbox.** Never send from a request handler. Queue with `notify.outbox.enqueue` and a
   unique `dedupe_key`; recipients are `user:<id>` and resolved when sending.
7. **MCP tools only add or read.** No edit/delete tools. Guard anything an LLM could get wrong (big odometer
   jumps, corrections) with explicit confirm flags and readable `ToolError` messages.
8. **Times:** store UTC, compute "today" with `app.clock.today_local()` (uses `TIMEZONE`). Tests run frozen at
   2026-11-11 12:00 America/Toronto.
9. **Keep the UI usable on a phone** (390 px wide): modals go full screen on mobile, the e2e tests run both sizes.

## When you add a feature

- [ ] Model + migration (if data changes), schemas, service logic, route with ownership checks
- [ ] Tests: pure logic in `domain`, API behaviour including "another user's id gives 404"
- [ ] Regenerate `frontend/openapi.json` and `schema.d.ts` if the API changed
- [ ] UI, checked at desktop and phone widths; an e2e test for the main flow
- [ ] If it's something users set up or log: consider an MCP tool (`mcp_setup.py` / `mcp_server.py`) and the
      table in `docs/GUIDE.md`
- [ ] Docs: `docs/GUIDE.md` (how to use it), `docs/DEPLOY.md` (new settings), `docs/ARCHITECTURE.md` (design),
      `.env.example` (new variables)
- [ ] `uv run pytest -q` and `npm run build` pass

## Gotchas

- The test client is `httpx2` (pulled in by the MCP SDK); to replace a cookie, `cookies.clear()` first.
- The MCP SDK is v2 (`mcp.server.mcpserver.MCPServer`, not v1's FastMCP). Tool calls run in a background task, so
  the user is passed through the request scope (`scope["state"]["mcp_user_id"]`), not a contextvar.
- `NOTIFIER=log` (default) means bots don't start and alerts only go to the log; tests rely on that.
- Playwright serves the built `frontend/dist`: rebuild before running e2e after UI changes.
