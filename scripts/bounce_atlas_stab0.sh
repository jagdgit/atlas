#!/usr/bin/env bash
# OI-STAB0 — bounce hung atlas serve + sync systemd env from repo .env
# Run on the host as root:  sudo bash scripts/bounce_atlas_stab0.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -f "$ROOT/.env" && -d /etc/atlas ]]; then
  install -m 0640 -o root -g root "$ROOT/.env" /etc/atlas/atlas.env
  echo "Synced /etc/atlas/atlas.env from $ROOT/.env"
fi

if command -v systemctl >/dev/null 2>&1 && [[ -f /etc/systemd/system/atlas.service ]]; then
  systemctl stop atlas.service || true
fi
pkill -TERM -f '/data/atlas/.venv/bin/atlas serve' 2>/dev/null || true
sleep 3
pkill -9 -f '/data/atlas/.venv/bin/atlas serve' 2>/dev/null || true
sleep 1

if command -v systemctl >/dev/null 2>&1 && [[ -f /etc/systemd/system/atlas.service ]]; then
  systemctl reset-failed atlas.service 2>/dev/null || true
  systemctl start atlas.service
  echo "started via systemd"
else
  cd "$ROOT"
  nohup .venv/bin/atlas serve >> /data/atlas_data/logs/atlas_serve_stdout.log 2>&1 &
  echo "started pid $!"
fi

for i in $(seq 1 40); do
  code=$(curl -sS -m 2 -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/v1/health 2>/dev/null || echo 000)
  if [[ "$code" == "401" || "$code" == "200" ]]; then
    echo "up=$code after ${i}s"
    exit 0
  fi
  sleep 1
done
echo "WARN: health not up" >&2
exit 1
