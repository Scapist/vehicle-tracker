# Contributing

Thanks for wanting to help! Bug fixes, improvements and new features are welcome. Every change is reviewed by the
maintainer before it's merged, so for anything bigger than a small fix, **open an issue first** to describe what
you'd like to build. That saves you from spending time on something that doesn't fit.

## How to propose a change

1. **Fork** the repository and create a branch from `main` (`feature/short-name` or `fix/short-name`).
2. Make the change, with tests (see below).
3. Make sure everything passes:

   ```sh
   cd backend && uv run pytest -q
   cd ../frontend && npm run build
   ```

   For UI changes, also run `npm run e2e` (it checks desktop and phone sizes).
4. Open a **pull request** against `main`, describe what and why, and add a screenshot for UI changes. The CI runs
   the tests automatically.
5. The maintainer reviews it and may ask for changes. Merging is at the maintainer's discretion.

## Setting up

You need Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node.js 22.

```sh
cd backend && uv sync
uv run alembic upgrade head && uv run python -m app.seed --demo   # demo data, sign in as demo@example.com
uv run uvicorn app.main:app --reload

cd frontend && npm install && npm run dev   # http://localhost:5173
```

Sign in as `demo@example.com` with the password `demo-password` (or set `DEMO_PASSWORD` before seeding).

## What a good change looks like

[CLAUDE.md](CLAUDE.md) has the project layout, the commands and the rules every change must follow; it's written
for AI assistants but it's the best summary for people too. The short version:

- **Ownership checks on every access** to user data (`app/api/deps.py`); another user's id is a 404.
- **Business logic in `services/` or `domain/`**, shared by the API, bots and MCP, not duplicated in routes.
- **Tests** for new behaviour, including "another user can't see or change it".
- **Migrations** that are safe on existing databases, with the migration test updated.
- **Regenerated API types** (`frontend/openapi.json`, `src/api/schema.d.ts`) when the API changes.
- **Docs** updated: `docs/GUIDE.md` for users, `docs/DEPLOY.md` and `.env.example` for new settings,
  `docs/ARCHITECTURE.md` for design changes.
- **Works on a phone** (390 px wide).
- **No secrets or personal data** in code, tests, fixtures or screenshots.

Keep pull requests focused: one feature or fix each.

## Using AI assistants

You're welcome to use Claude Code or other AI tools. The repository includes [CLAUDE.md](CLAUDE.md) (also linked
as [AGENTS.md](AGENTS.md)) so your assistant knows how the app is built and what the rules are. You're responsible
for what you submit: read and understand the change, and run the tests.

## Reporting bugs and ideas

Use the issue templates. For security problems, **don't open a public issue**; see [SECURITY.md](SECURITY.md).

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
