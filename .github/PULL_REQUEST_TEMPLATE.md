## What and why

<!-- What does this change, and why? Link the issue if there is one: "Closes #12" -->

## Checklist

- [ ] `cd backend && uv run pytest -q` passes
- [ ] `cd frontend && npm run build` passes (and `npm run e2e` for UI changes)
- [ ] Tests added for new behaviour, including another user's data staying hidden
- [ ] API types regenerated if the API changed (`frontend/openapi.json`, `src/api/schema.d.ts`)
- [ ] Migration added and safe on existing data (if the database changed)
- [ ] Docs updated (`docs/GUIDE.md`, `docs/DEPLOY.md`, `.env.example`, `docs/ARCHITECTURE.md` as relevant)
- [ ] Checked on a phone-sized screen (UI changes); screenshot attached
- [ ] No secrets or personal data
