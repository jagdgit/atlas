#!/usr/bin/env bash
# Install / refresh the Atlas systemd unit (boot start + stop/restart).
# Run on the host:  sudo bash deploy/systemd/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
UNIT_SRC="$ROOT/deploy/systemd/atlas.service"
UNIT_DST=/etc/systemd/system/atlas.service
ENV_DST=/etc/atlas/atlas.env
ENV_SRC="$ROOT/.env"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

if [[ ! -f "$UNIT_SRC" ]]; then
  echo "missing unit: $UNIT_SRC" >&2
  exit 1
fi

install -d -m 0755 /etc/atlas
if [[ -f "$ENV_SRC" ]]; then
  # Keep secrets out of the unit file; refresh env from repo .env.
  install -m 0640 -o root -g jagd "$ENV_SRC" "$ENV_DST"
  echo "Installed $ENV_DST from $ENV_SRC"
else
  echo "WARNING: $ENV_SRC not found — create $ENV_DST manually" >&2
fi

# Ensure runtime data dirs are writable by the service user.
install -d -m 0775 -o jagd -g jagd /data/atlas_data
chown -R jagd:jagd /data/atlas_data 2>/dev/null || true

install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable atlas.service
systemctl restart atlas.service
systemctl --no-pager --full status atlas.service || true

cat <<'EOF'

Atlas is managed by systemd now.

  sudo systemctl status atlas     # health
  sudo systemctl stop atlas       # intentional stop (stays down)
  sudo systemctl start atlas      # start
  sudo systemctl restart atlas    # bounce
  journalctl -u atlas -f          # live logs

Enabled on boot (WantedBy=multi-user.target).
Do not also run `atlas serve` in a terminal — that fights this unit for ports/RAM.
EOF
