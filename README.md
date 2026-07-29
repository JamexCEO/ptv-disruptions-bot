# PTV Disruption Discord Bot

Polls the official Transport Victoria Timetable API every five minutes for Metro
Train, Metro Tram, and V/Line disruptions and posts new alerts to Discord.

The project can run in either of two modes:

- **Installable Discord app (`discord_app.py`)** — supports multiple servers,
  slash-command configuration, per-server role notifications, and SQLite storage.
- **Webhook bot (`bot.py`)** — posts to one Discord webhook and is configured
  entirely through environment variables.

## Requirements

- Python 3.10 or newer
- Transport Victoria Timetable API developer ID and API key
- A Discord bot token for the installable app, or a Discord webhook URL for the
  webhook bot

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace the relevant placeholders. Never commit or share this
file.

Both modes require:

```dotenv
PTV_DEV_ID=your_developer_id
PTV_API_KEY=your_api_key
```

## Installable Discord app

The installable app is the recommended mode when the bot will be added to one or
more Discord servers.

Add the bot token to `.env`:

```dotenv
DISCORD_BOT_TOKEN=your_bot_token
```

Install the app in Discord with the `bot` and `applications.commands` scopes.
Grant it View Channels, Send Messages, and Embed Links permissions in each alert
channel. Start it locally with:

```powershell
python discord_app.py
```

Server managers configure the app with these slash commands:

- `/setup` — choose the alert channel and enable alerts
- `/set-role` — map a Metro route, `tram`, or `vline` to a mention role
- `/remove-role` — remove a role mapping
- `/status` — show the server's current configuration
- `/disable` — stop alerts for the server

`/setup` marks all disruptions currently returned by PTV as seen, so only
disruptions that appear afterward are posted. Configuration, role mappings, and
seen disruption IDs are stored per server in `discord_app.db`.

Set `DATA_FILE` to use a different database location:

```dotenv
DATA_FILE=discord_app.db
```

The database must be kept on persistent storage in production.

## Webhook bot

Add the webhook URL to `.env`:

```dotenv
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook
```

### Safe first test

This contacts PTV and logs the disruptions it would post without contacting
Discord or updating `seen_disruptions.json`:

```powershell
python bot.py --once --dry-run
```

To perform one real poll:

```powershell
python bot.py --once
```

On a new installation, the first real poll posts every disruption currently
returned for trains, trams, and V/Line. Run the dry test first to see how many
alerts that would produce.

For continuous polling:

```powershell
python bot.py
```

Stop it with `Ctrl+C`.

### Role notifications

Role IDs for the webhook bot are optional and configured in `.env`:

```dotenv
DISCORD_LINE_ROLES={"Belgrave":"111111111111111111","Lilydale":"111111111111111111"}
DISCORD_TRAM_ROLE_ID=222222222222222222
DISCORD_VLINE_ROLE_ID=333333333333333333
```

Multiple route names may point to the same role. Metro route names are
case-insensitive and may include or omit a trailing `Line`. Tram disruptions use
the tram role and regional-train disruptions use the V/Line role. The bot limits
mentions to explicitly matched role IDs; ensure the webhook is allowed to mention
each configured role.

### Deduplication

After each successful webhook post, its disruption ID is added to
`seen_disruptions.json`. A failed post is not marked as seen and is retried during
a later poll.

Set `SEEN_FILE` to place this state file somewhere else:

```dotenv
SEEN_FILE=/path/to/seen_disruptions.json
```

The state file is ignored by Git and must be kept on persistent storage in
production.

## Linux deployment with systemd

The included installer deploys the installable Discord app to
`/opt/ptv-disruptions`, stores its database at
`/var/lib/ptv-disruptions/discord_app.db`, and registers the
`ptv-disruptions.service` systemd unit.

From a checkout that contains a completed `.env`, run:

```bash
sudo bash deploy/install.sh
```

The installer creates a restricted `ptvbot` system user, installs the Python
environment, enables the service, and restarts it. Re-running the installer
updates the deployed code and dependencies. If a local `discord_app.db` exists,
it is copied into persistent storage.

Useful service commands:

```bash
sudo systemctl status ptv-disruptions
sudo journalctl -u ptv-disruptions -f
sudo systemctl restart ptv-disruptions
```

## Troubleshooting

- `Missing required environment variable`: check that `.env` is beside the
  scripts and contains the variables required by the selected mode.
- HTTP 403 from PTV: recheck `PTV_DEV_ID` and `PTV_API_KEY`.
- HTTP 401/404 from Discord in webhook mode: recreate or recopy the webhook URL.
- The Discord app is online but cannot post: check its channel permissions and
  run `/status` to confirm the configured channel.
- Role mentions appear as plain text: allow the bot or webhook to mention the
  configured roles and verify the stored role IDs.
- Duplicate webhook alerts after deployment: persist `seen_disruptions.json`, or
  set `SEEN_FILE` to a persistent path.
- Duplicate app alerts after deployment: persist `discord_app.db`, or set
  `DATA_FILE` to a persistent path.

The API endpoint and response shape are documented in the
[official Transport Victoria Swagger UI](https://timetableapi.ptv.vic.gov.au/swagger/ui/index).
