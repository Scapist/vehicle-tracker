# Deploying and running it

Everything runs in one Docker container on one port (8000), with the data in `./data` next to
`docker-compose.yml`. A Raspberry Pi 4, an old laptop or any small home server is plenty.

- [Install](#install)
- [Configuration (`.env`)](#configuration-env)
- [Accounts](#accounts)
- [Reaching it from your phone](#reaching-it-from-your-phone)
- [Telegram and Discord bots](#telegram-and-discord-bots)
- [AI assistants (MCP)](#ai-assistants-mcp)
- [Updating](#updating)
- [Backup and restore](#backup-and-restore)
- [Optional: push-to-deploy](#optional-push-to-deploy)
- [Security notes](#security-notes)

## Install

```sh
git clone https://github.com/Scapist/vehicle-tracker.git
cd vehicle-tracker
cp .env.example .env
nano .env                       # at least TIMEZONE; see below
docker compose up -d --build
```

The database is created and migrated automatically on start. Open <http://localhost:8000> on the machine
running it (see [Reaching it from your phone](#reaching-it-from-your-phone) for other devices). API docs for
signed-in users are at `/docs`.

On first start the container hands `./data` to the app's unprivileged user (uid 10001) and then drops all
privileges, so from the host you'll need `sudo` to read or copy files in `./data`. Before applying a database
migration it saves a copy in `data/backups/`.

## Configuration (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `TIMEZONE` | `America/Toronto` | Your timezone ([tz name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), e.g. `Europe/Paris`). Decides what "today" is and when the daily alerts (08:00) and odometer nudges (18:00) go out. |
| `BIND_ADDR` | `127.0.0.1` | Which address port 8000 listens on. `127.0.0.1` = only this machine. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Every host name or IP you open the app by (protects against DNS rebinding). |
| `FORWARDED_ALLOW_IPS` | unset | The IP of a reverse proxy or `tailscale serve`, so sign-in limits see real devices. See below. |
| `NOTIFIER` | `log` | `log` = alerts only go to the container log (testing). `telegram`, `discord` or `chat` = send them through the bots configured below. |
| `TELEGRAM_BOT_TOKEN` | empty | Turns on the Telegram bot. |
| `DISCORD_BOT_TOKEN` | empty | Turns on the Discord bot. |
| `DISCORD_ALLOWED_USER_IDS` | empty | Optional: the Discord bot ignores everyone not listed. |
| `MCP_ENABLED` | `false` | Turns on the MCP server for AI assistants at `/mcp`. |
| `MCP_USERS` | `owner` | `owner` = only the owner account can create MCP tokens; `all` = every account (each sees only their own data). |

After changing `.env`, run `docker compose up -d` (add `--force-recreate` if the change doesn't take).

## Accounts

Each person has their own account with completely separate vehicles, records and receipts.

1. **First start.** With no accounts yet, the server prints a one-time setup code in its log:

   ```sh
   docker compose logs tracker | grep -A1 "setup code"
   ```

   Open the app, enter the code and create your account. You become the **owner**.
2. **Inviting someone.** Settings → *Invite people* creates a link. Each link makes one account and expires after
   7 days. There is no open sign-up.
3. **Signing in** keeps a device signed in for 30 days. Changing your password signs out your other devices;
   *Sign out on all devices* does the same without a password change. Repeated wrong passwords pause sign-in for
   that device or email for a growing time (30 s up to 15 min).

Passwords are stored as salted scrypt hashes. Nothing about accounts lives in `.env`.

## Reaching it from your phone

By default the app only listens on `127.0.0.1`, so only the machine running it can open it. It only answers to
host names in `ALLOWED_HOSTS` and refuses cross-site writes, so a website you visit can't use your browser to
change or read your data. Pick one way in:

- **Tailscale (recommended).** Install [Tailscale](https://tailscale.com) on the server and your phone, keep
  `BIND_ADDR=127.0.0.1`, and run `tailscale serve --bg 8000` on the server. Add the server's tailnet name to
  `ALLOWED_HOSTS` (e.g. `ALLOWED_HOSTS=localhost,127.0.0.1,myserver.tailnet-name.ts.net`) and set
  `FORWARDED_ALLOW_IPS` (see the note below). Only your own devices can reach it, encrypted, from anywhere.
- **Straight on your home network.** Set `BIND_ADDR` to the server's LAN IP and add it to `ALLOWED_HOSTS`:

  ```
  BIND_ADDR=192.168.1.50
  ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50
  ```

  Devices on your Wi-Fi then need the password, but traffic (including the password when you sign in) is plain,
  unencrypted HTTP. Fine on a home network you trust; put guests and smart-home devices on a guest network.
- **Reverse proxy.** Keep `BIND_ADDR=127.0.0.1` (otherwise the proxy can be bypassed on port 8000) and let only the
  proxy listen on the network. Caddy example (`caddy hash-password` makes the hash):

  ```
  tracker.home.lan {
      basicauth {
          me <hashed-password>
      }
      reverse_proxy 127.0.0.1:8000
  }
  ```

  Add `tracker.home.lan` to `ALLOWED_HOSTS`: every name you open the app by must be listed, which is also how
  the app recognises its own pages when a proxy rewrites the `Host` header.

**`FORWARDED_ALLOW_IPS` with a proxy or `tailscale serve`.** Requests from a proxy reach the container from
Docker's gateway address, not from the real device. Unless you tell the app to trust that address's
`X-Forwarded-For` header, every device looks like the same one, and sign-in limits apply to all of them
together (one person guessing passwords could lock everyone out for a while). Set it to the address the proxy
connects from:

- proxy or `tailscale serve` **on the same machine:** Docker's gateway, usually `172.17.0.1` (check with
  `docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'`; Compose projects often use their own
  network, e.g. `172.18.0.1`; `docker inspect vehicle-tracker` shows it);
- proxy on **another machine or container:** that machine's or container's IP.

Only list addresses you control: whoever connects from them can claim to be any device.

On a phone, use "Add to Home Screen" to install the app.

## Telegram and Discord bots

You can run either or both. Each person links their own apps in Settings → **Chat apps** with a one-time code;
the bots only answer direct messages, and only for linked accounts. Both connect *out* to Telegram/Discord, so no
public address is needed. Set `NOTIFIER=telegram` (or `discord`/`chat`, they mean the same) to send alerts
through them.

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. In `.env`: `NOTIFIER=telegram` and `TELEGRAM_BOT_TOKEN=123456:ABC...`, then `docker compose up -d`.
3. In the app, Settings → Chat apps → Telegram → **Connect**, and send the bot the `/link CODE` it shows.

### Discord

1. At <https://discord.com/developers/applications> create an application.
2. **Installation:** set *Install Link* to **None** and save. **Bot:** reset and copy the token, turn **Public
   Bot** off and leave all *Privileged Gateway Intents* off.
3. A bot can only DM you if you share a server with it. Create a private server just for it (Discord: **+** →
   *Create My Own*), then in the developer portal **OAuth2 → URL Generator** tick **bot**, open the generated
   link and add the bot to that server. Don't leave the server later, or alerts stop.
4. In `.env`: `NOTIFIER=telegram` (or `chat`) and `DISCORD_BOT_TOKEN=...`, then `docker compose up -d`. The log
   should say `Discord bot connected as ...`.
5. In the app, Settings → Chat apps → Discord → **Connect**, and DM the bot the `!link CODE` it shows.
6. Optional: to make the bot ignore everyone else, turn on Developer Mode in Discord (Settings → Advanced),
   right-click your name → *Copy User ID*, and set `DISCORD_ALLOWED_USER_IDS=<that id>`.

What the bots understand is in the [user guide](GUIDE.md#chat-bots).

## AI assistants (MCP)

The MCP server lets an assistant such as Claude read your data, log km and services, attach receipts and set up
vehicles, reminders, dates, tire sets and payments. It **can't edit or delete** anything, and it acts as one
account, seeing only that account's data.

1. In `.env`: `MCP_ENABLED=true`, then `docker compose up -d`. With the default `MCP_USERS=owner` only the owner
   account can use it.
2. In the app: Settings → **AI assistants** → **Create token**. Copy it: it's shown once (only a hash is stored).
   Revoke it there if it leaks. Use one token per assistant.
3. Connect your assistant. The Settings card shows these commands with your address filled in.

   **Claude Code:**

   ```sh
   claude mcp add --scope user --transport http tracker http://<your-server>:8000/mcp \
     --header "Authorization: Bearer <token>"
   ```

   (`--scope user` makes it available in every folder; without it, only in the folder you ran it in.)

   **Claude Desktop**, in `claude_desktop_config.json` (`mcp-remote` runs on your computer and forwards to the
   server; drop `--allow-http` if you use HTTPS):

   ```json
   { "mcpServers": { "tracker": { "command": "npx", "args": ["mcp-remote", "http://<your-server>:8000/mcp",
     "--allow-http", "--header", "Authorization:Bearer <token>"] } } }
   ```

   Other MCP clients: it's a Streamable HTTP server at `/mcp` with `Authorization: Bearer <token>`.

`/mcp` is on the same port as the app, so it's exactly as reachable as the app, and every request needs a token
on top. Assistants that run in the cloud (claude.ai, the Claude phone app) would need a public HTTPS address with
OAuth sign-in, which this version doesn't offer.

How to use it is in the [user guide](GUIDE.md#setting-up-with-an-ai-assistant).

## Updating

```sh
git pull
docker compose up -d --build
```

Database migrations run on start, after an automatic backup to `data/backups/`.

## Backup and restore

Back up `./data`: the database and the receipt files.

```sh
# safe while the app is running
sudo sqlite3 data/tracker.sqlite3 ".backup 'backup/tracker-$(date +%F).sqlite3'"
sudo tar czf backup/receipts-$(date +%F).tgz -C data receipts
```

Cron example (daily at 03:00, as root):

```
0 3 * * * cd /srv/vehicle-tracker && mkdir -p backup && sqlite3 data/tracker.sqlite3 ".backup 'backup/tracker-$(date +\%F).sqlite3'" && tar czf backup/receipts-$(date +\%F).tgz -C data receipts
```

Copy the backups somewhere other than the server too.

**Restore:** `docker compose down`, put the `.sqlite3` back as `data/tracker.sqlite3` (delete any `-wal`/`-shm`
files next to it), extract the receipts archive into `data/`, then `docker compose up -d`.

## Optional: push-to-deploy

If you develop on one computer and run the app on a server you can reach over SSH, a bare git repository with a
`post-receive` hook on the server lets `git push` deploy:

```sh
# on the server, once
git init --bare ~/git/vehicle-tracker.git
# then write ~/git/vehicle-tracker.git/hooks/post-receive (and chmod +x it), roughly:
#   for main only: git --work-tree=$HOME/vehicle-tracker checkout -f main
#                  cd $HOME/vehicle-tracker && docker compose up -d --build
#                  wait for http://127.0.0.1:8000/healthz, roll back to the previous commit if it never comes up

# on your computer, once: push to GitHub and the server together
git remote set-url --add --push origin https://github.com/<you>/vehicle-tracker.git
git remote set-url --add --push origin <user>@<server>:git/vehicle-tracker.git
```

Keep `.env` and `data/` outside what the hook overwrites, and snapshot `data/tracker.sqlite3` before each deploy.

## Security notes

- Keep it off the open internet. Use Tailscale or your home network; if you put it behind a public proxy, add the
  proxy's own authentication and set `FORWARDED_ALLOW_IPS`.
- Never run `python -m app.seed --demo` against real data: it creates a `demo@example.com` account with a known
  password.
- The bot tokens and MCP tokens in `.env` and Settings are as good as your password. Anyone with shell access as
  a user in the `docker` group can read everything; protect the server account (SSH keys, no password logins).
- Report vulnerabilities as described in [SECURITY.md](../SECURITY.md).
