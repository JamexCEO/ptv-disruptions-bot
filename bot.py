"""Poll Transport Victoria disruptions and post new ones to Discord."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

API_BASE = "https://timetableapi.ptv.vic.gov.au"
DISRUPTIONS_PATH = "/v3/disruptions"
SEEN_FILE = Path(
    os.getenv(
        "SEEN_FILE",
        str(Path(__file__).with_name("seen_disruptions.json")),
    )
)
MELBOURNE = ZoneInfo("Australia/Melbourne")
POLL_SECONDS = 300
MAX_ATTEMPTS = 3
USER_AGENT = "MHS-Train-Club-Disruptions/1.0"

COLOURS = {
    "information": 0x3498DB,
    "hurstbridge": 0xBE1014,
    "mernda": 0xBE1014,
    "belgrave": 0x152C6B,
    "lilydale": 0x152C6B,
    "alamein": 0x152C6B,
    "glen waverley": 0x152C6B,
    "frankston": 0x028430,
    "stony point": 0x028430,
    "cranbourne": 0x279FD5,
    "pakenham": 0x279FD5,
    "sunbury": 0x279FD5,
    "werribee": 0xF178AF,
    "sandringham": 0xF178AF,
    "williamstown": 0xF178AF,
    "craigieburn": 0xFFBE00,
    "upfield": 0xFFBE00
}


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def signed_url(dev_id: str, api_key: str) -> str:
    query = urlencode(
        [("route_types", route_type) for route_type in (0, 1, 3)]
        + [("devid", dev_id)]
    )
    raw = f"{DISRUPTIONS_PATH}?{query}"
    signature = hmac.new(
        api_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha1
    ).hexdigest().upper()
    return f"{API_BASE}{raw}&signature={signature}"


def request_json(
    request: Request, *, attempts: int = MAX_ATTEMPTS
) -> dict[str, Any]:
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"Request failed after {attempts} attempts: {exc}") from exc
            delay = 2 ** (attempt - 1)
            logging.warning("Request failed (%s); retrying in %ss", exc, delay)
            time.sleep(delay)
    raise AssertionError("unreachable")


def fetch_disruptions(dev_id: str, api_key: str) -> list[dict[str, Any]]:
    request = Request(signed_url(dev_id, api_key), headers={"User-Agent": USER_AGENT})
    payload = request_json(request)
    groups = payload.get("disruptions") or {}
    if not isinstance(groups, dict):
        raise RuntimeError("Unexpected PTV response: 'disruptions' is not an object")

    disruptions: list[dict[str, Any]] = []
    for mode in ("metro_train", "metro_tram", "regional_train"):
        items = groups.get(mode) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    item["_ptv_mode"] = mode
                    disruptions.append(item)
    return disruptions


def load_seen() -> set[int]:
    if not SEEN_FILE.exists():
        return set()
    try:
        values = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return {int(value) for value in values}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read {SEEN_FILE.name}: {exc}") from exc


def save_seen(seen: set[int]) -> None:
    temporary = SEEN_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(sorted(seen), indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(SEEN_FILE)


def clean_text(value: Any, limit: int) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return "No details supplied."
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def format_date(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=MELBOURNE)
        local = parsed.astimezone(MELBOURNE)
        hour = local.strftime("%I").lstrip("0") or "0"
        return f"{local:%d %b %Y}, {hour}:{local:%M %p}"
    except (ValueError, TypeError):
        return str(value)


def route_names(disruption: dict[str, Any]) -> str:
    names: list[str] = []
    for route in disruption.get("routes") or []:
        if not isinstance(route, dict):
            continue
        name = route.get("route_name") or route.get("route_number")
        if name and str(name) not in names:
            names.append(str(name))
    return ", ".join(names) if names else "Network-wide / unspecified"

def route_identify(disruption: dict[str, Any]) -> str:
    names: list[str] = []
    for route in disruption.get("routes") or []:
        if not isinstance(route, dict):
            continue
        name = route.get("route_name") or route.get("route_number")
        if name and str(name) not in names:
            names.append(str(name))
    return names[0]

def make_embed(disruption: dict[str, Any]) -> dict[str, Any]:
    status = str(disruption.get("disruption_status") or "Information")
    line = route_identify(disruption)
    fields = [
        {"name": "Status", "value": status, "inline": True},
        {
            "name": "Lines",
            "value": clean_text(route_names(disruption), 1024),
            "inline": False,
        },
    ]
    start = format_date(disruption.get("from_date"))
    end = format_date(disruption.get("to_date"))
    if start:
        fields.append({"name": "From", "value": start, "inline": True})
    if end:
        fields.append({"name": "Until", "value": end, "inline": True})

    title  = str(clean_text(disruption.get("title") or "PTV disruption", 256))
    desc = str(clean_text(disruption.get("description"), 4096))
    if title != desc:
        embed: dict[str, Any] = {
            "title": clean_text(disruption.get("title") or "PTV disruption", 256),
            "description": clean_text(disruption.get("description"), 4096),
            "color": COLOURS.get(line.casefold(), COLOURS["information"]),
            "fields": fields,
            "footer": {
                "text": f"Transport Victoria • ID {disruption.get('disruption_id', 'unknown')}"
            },
        }
        url = disruption.get("url")
        if url:
            embed["url"] = str(url)
        return embed
    
    else:
        embed: dict[str, Any] = {
            "title": clean_text(disruption.get("title") or "PTV disruption", 256),
            "color": COLOURS.get(line.casefold(), COLOURS["information"]),
            "fields": fields,
            "footer": {
                "text": f"Transport Victoria • ID {disruption.get('disruption_id', 'unknown')}"
            },
        }
        url = disruption.get("url")
        if url:
            embed["url"] = str(url)
        return embed


def normalize_route_name(value: Any) -> str:
    name = str(value or "").strip().casefold()
    return re.sub(r"\s+line$", "", name)


def load_role_config() -> tuple[dict[str, str], str | None, str | None]:
    raw = os.getenv("DISCORD_LINE_ROLES", "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DISCORD_LINE_ROLES must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("DISCORD_LINE_ROLES must be a JSON object")

    line_roles = {
        normalize_route_name(route): str(role_id).strip()
        for route, role_id in parsed.items()
        if str(route).strip() and str(role_id).strip()
    }
    tram_role = os.getenv("DISCORD_TRAM_ROLE_ID", "").strip() or None
    vline_role = os.getenv("DISCORD_VLINE_ROLE_ID", "").strip() or None
    return line_roles, tram_role, vline_role


def matching_role_ids(
    disruption: dict[str, Any],
    line_roles: dict[str, str],
    tram_role: str | None,
    vline_role: str | None,
) -> list[str]:
    matches: list[str] = []
    mode = disruption.get("_ptv_mode")
    if mode == "metro_tram" and tram_role:
        matches.append(tram_role)
    if mode == "regional_train" and vline_role:
        matches.append(vline_role)

    for route in disruption.get("routes") or []:
        if not isinstance(route, dict):
            continue
        role_id = line_roles.get(normalize_route_name(route.get("route_name")))
        if role_id and role_id not in matches:
            matches.append(role_id)
    return matches


def post_to_discord(
    webhook_url: str,
    disruption: dict[str, Any],
    line_roles: dict[str, str],
    tram_role: str | None,
    vline_role: str | None,
) -> None:
    role_ids = matching_role_ids(disruption, line_roles, tram_role, vline_role)
    payload = json.dumps(
        {
            "username": "PTV Disruption Alerts",
            "content": " ".join(f"<@&{role_id}>" for role_id in role_ids),
            "allowed_mentions": {"parse": [], "roles": role_ids},
            "embeds": [make_embed(disruption)],
        }
    ).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    request_json(request)


def poll_once(
    dev_id: str,
    api_key: str,
    webhook_url: str,
    seen: set[int],
    dry_run: bool,
    line_roles: dict[str, str],
    tram_role: str | None,
    vline_role: str | None,
) -> int:
    disruptions = fetch_disruptions(dev_id, api_key)
    posted = 0
    for disruption in disruptions:
        try:
            disruption_id = int(disruption["disruption_id"])
        except (KeyError, TypeError, ValueError):
            logging.warning("Skipping disruption without a valid ID")
            continue
        if disruption_id in seen:
            continue

        role_ids = matching_role_ids(
            disruption, line_roles, tram_role, vline_role
        )
        if dry_run:
            logging.info(
                "[DRY RUN] Would post %s%s: %s",
                disruption_id,
                f" and ping {len(role_ids)} role(s)" if role_ids else "",
                disruption.get("title", "Untitled"),
            )
        else:
            post_to_discord(
                webhook_url, disruption, line_roles, tram_role, vline_role
            )
            seen.add(disruption_id)
            save_seen(seen)
            logging.info("Posted disruption %s", disruption_id)
        posted += 1
    logging.info("Poll complete: %s returned, %s new", len(disruptions), posted)
    return posted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Poll once, then exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch and log without posting or saving"
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        dev_id = require_env("PTV_DEV_ID")
        api_key = require_env("PTV_API_KEY")
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not args.dry_run and not webhook_url:
            raise RuntimeError("Missing required environment variable: DISCORD_WEBHOOK_URL")
        line_roles, tram_role, vline_role = load_role_config()
        seen = load_seen()

        while True:
            try:
                poll_once(
                    dev_id,
                    api_key,
                    webhook_url,
                    seen,
                    args.dry_run,
                    line_roles,
                    tram_role,
                    vline_role,
                )
            except RuntimeError as exc:
                logging.error("%s", exc)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(POLL_SECONDS)
    except (RuntimeError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            logging.info("Stopped")
            return 130
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
