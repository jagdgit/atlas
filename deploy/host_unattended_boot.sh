#!/usr/bin/env bash
# Host unattended boot: Wi-Fi autoconnect + GDM autologin + Atlas on power restore.
# Run once:  sudo bash deploy/host_unattended_boot.sh [--watchdog]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${ATLAS_HOST_USER:-jagd}"
ENABLE_WATCHDOG=0
for arg in "$@"; do
  case "$arg" in
    --watchdog) ENABLE_WATCHDOG=1 ;;
    -h|--help) echo "Usage: sudo bash $0 [--watchdog]"; exit 0 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0 [--watchdog]" >&2
  exit 1
fi

echo "==> NetworkManager + wait-online"
systemctl enable NetworkManager.service || true
systemctl enable NetworkManager-wait-online.service || true
systemctl start NetworkManager.service || true

if command -v nmcli >/dev/null 2>&1; then
  while IFS=: read -r name type _; do
    [[ "$type" == "802-11-wireless" ]] || continue
    [[ -n "$name" ]] || continue
    nmcli connection modify "$name" connection.autoconnect yes 2>/dev/null || true
    nmcli connection modify "$name" connection.autoconnect-retries 0 2>/dev/null || true
    echo "    wifi autoconnect: $name"
  done < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null || true)
fi

echo "==> GDM automatic login for ${USER_NAME}"
GDM_CONF=/etc/gdm3/custom.conf
if [[ -f "$GDM_CONF" ]]; then
  cp -a "$GDM_CONF" "${GDM_CONF}.bak.$(date +%Y%m%d%H%M%S)"
  python3 - "$GDM_CONF" "$USER_NAME" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
user = sys.argv[2]
lines = path.read_text().splitlines()
out = []
in_daemon = False
daemon_seen = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        in_daemon = stripped == "[daemon]"
        out.append(line)
        if in_daemon:
            daemon_seen = True
            out.append("AutomaticLoginEnable=true")
            out.append(f"AutomaticLogin={user}")
        continue
    if in_daemon and (
        stripped.startswith("AutomaticLoginEnable")
        or stripped.startswith("AutomaticLogin")
        or stripped.startswith("#AutomaticLogin")
        or stripped.startswith("#  AutomaticLogin")
    ):
        continue
    out.append(line)
if not daemon_seen:
    out.extend(["", "[daemon]", "AutomaticLoginEnable=true", f"AutomaticLogin={user}"])
path.write_text("\n".join(out) + "\n")
print(f"    wrote {path}")
PY
else
  echo "    WARN: $GDM_CONF missing — skip autologin"
fi

echo "==> Install / enable atlas.service"
bash "$ROOT/deploy/systemd/install.sh"

if [[ "$ENABLE_WATCHDOG" -eq 1 ]]; then
  echo "==> Install atlas-watchdog.timer"
  cat >/etc/systemd/system/atlas-watchdog.service <<'UNIT'
[Unit]
Description=Ensure Atlas service is running
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/systemctl start atlas.service
UNIT
  cat >/etc/systemd/system/atlas-watchdog.timer <<'UNIT'
[Unit]
Description=Watch Atlas every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Unit=atlas-watchdog.service

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable --now atlas-watchdog.timer
  systemctl --no-pager status atlas-watchdog.timer || true
fi

cat <<MSG

Done. Checklist:
  1. BIOS: Restore on AC Power Loss / Always On
  2. Wi-Fi autoconnect enabled
  3. GDM AutomaticLogin=${USER_NAME}
  4. atlas.service enabled at boot (no login required for Atlas)
  5. Optional --watchdog restarts Atlas if stopped

Verify:
  systemctl is-active atlas
  curl -sS http://127.0.0.1:8000/health
MSG
