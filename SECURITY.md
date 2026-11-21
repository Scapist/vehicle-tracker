# Security

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Instead, use GitHub's private reporting:
the repository's **Security** tab → **Report a vulnerability**. Include what's affected, how to reproduce it and
what an attacker could do.

You'll get an answer as soon as possible. This is a hobby project maintained in spare time, so there's no
guaranteed response time, but security reports come first.

## Supported versions

Only the latest release on `main` gets fixes. Update with `git pull && docker compose up -d --build`.

## Running it safely

This app is meant for your home network or a private network such as Tailscale, not the open internet. See the
[security notes in DEPLOY.md](docs/DEPLOY.md#security-notes): keep `BIND_ADDR` at `127.0.0.1` unless you know
why not, list your host names in `ALLOWED_HOSTS`, set `FORWARDED_ALLOW_IPS` behind a proxy, and treat bot tokens
and MCP tokens like passwords.
