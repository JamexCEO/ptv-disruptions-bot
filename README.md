# PTV Disruption Discord Bot

Polls the official Transport Victoria Timetable API every five minutes for Metro Train, Metro Tram, and V/Line disruptions, then posts new disruptions to a Discord webhook.

## Setup

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace the placeholders with your PTV developer ID, PTV API key,
and Discord webhook URL. Never commit or share that file.

## Safe first test

This contacts PTV and prints the disruptions it would post, but does not contact
Discord or update the seen-disruptions file:

```powershell
python bot.py --once --dry-run
```

To perform one real poll:

```powershell
python bot.py --once
```

On a brand-new installation, that command posts every currently returned train and
tram disruption. If there are many, use the dry run first. For continuous polling:

```powershell
python bot.py
```

Stop it with `Ctrl+C`.

## Line, tram, and V/Line role notifications

Members follow a service by assigning themselves one of the existing Discord roles.
For each new disruption, the bot mentions every matching Metro line role. All tram
disruptions mention the tram role, and all regional-train disruptions mention the
V/Line role.

Role IDs are configured in `.env`:

```dotenv
DISCORD_LINE_ROLES={"Belgrave":"111111111111111111","Lilydale":"111111111111111111"}
DISCORD_TRAM_ROLE_ID=222222222222222222
DISCORD_VLINE_ROLE_ID=333333333333333333
```

Multiple route names may point to the same group role. The bot accepts names with
or without a trailing `Line`, and restricts Discord mentions to the explicitly
matched role IDs. Ensure the webhook may mention each configured role.

## How deduplication works

After each successful Discord post, the disruption ID is added to
`seen_disruptions.json`. The file is intentionally ignored by Git, but must be kept
on persistent storage when deploying. A failed Discord post is not marked as seen,
so it will be retried on a later poll.

## Troubleshooting

- `Missing required environment variable`: check that `.env` exists beside
  `bot.py` and contains all three values.
- HTTP 403 from PTV: recheck the developer ID and API key.
- HTTP 401/404 from Discord: recreate or recopy the webhook URL.
- Duplicate alerts after deployment: configure persistent storage for
  `seen_disruptions.json`.

The API endpoint and response shape are documented in the
[official Transport Victoria Swagger UI](https://timetableapi.ptv.vic.gov.au/swagger/ui/index).
