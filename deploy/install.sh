#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR=/opt/ptv-disruptions
SERVICE_NAME=ptv-disruptions.service

for required in bot.py requirements.txt .env seen_disruptions.json; do
  if [[ ! -f "$SOURCE_DIR/$required" ]]; then
    echo "Missing $SOURCE_DIR/$required" >&2
    exit 1
  fi
done

apt-get update
apt-get install -y python3 python3-venv

if ! id ptvbot >/dev/null 2>&1; then
  useradd --system --home-dir "$TARGET_DIR" --shell /usr/sbin/nologin ptvbot
fi

install -d -o root -g ptvbot -m 0750 "$TARGET_DIR"
install -o root -g ptvbot -m 0640 "$SOURCE_DIR/bot.py" "$TARGET_DIR/bot.py"
install -o root -g ptvbot -m 0640 "$SOURCE_DIR/requirements.txt" "$TARGET_DIR/requirements.txt"
install -o root -g ptvbot -m 0640 "$SOURCE_DIR/.env" "$TARGET_DIR/.env"
install -d -o ptvbot -g ptvbot -m 0750 /var/lib/ptv-disruptions
install -o ptvbot -g ptvbot -m 0640 \
  "$SOURCE_DIR/seen_disruptions.json" \
  /var/lib/ptv-disruptions/seen_disruptions.json

python3 -m venv "$TARGET_DIR/.venv"
"$TARGET_DIR/.venv/bin/python" -m pip install --upgrade pip
"$TARGET_DIR/.venv/bin/python" -m pip install -r "$TARGET_DIR/requirements.txt"
chown -R root:ptvbot "$TARGET_DIR/.venv"
chmod -R g=rX,o= "$TARGET_DIR/.venv"

install -o root -g root -m 0644 "$SOURCE_DIR/deploy/$SERVICE_NAME" "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME"