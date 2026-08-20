#!/usr/bin/env bash
# Force-stop remaining hello_watcher orphans, then verify clean.
set -euo pipefail
KEY="${ATLAS_API_KEY:-}"
if [[ -z "$KEY" ]]; then
  KEY=$(grep '^ATLAS_API_KEYS=' /data/atlas/.env | cut -d= -f2- | cut -d, -f1 | tr -d '"' | tr -d "'")
fi
H=(-H "Authorization: Bearer $KEY" -H "Content-Type: application/json")
BASE="${ATLAS_BASE_URL:-http://127.0.0.1:8000}"

echo "== apply remaining hello_watcher via cleanup =="
curl -sS "${H[@]}" \
  -d '{"dry_run":false,"zombie_types":["hello_watcher"],"reason":"stab0 d5 force-stop remaining hello_watcher"}' \
  "$BASE/v1/ops/cleanup" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print("ok", d.get("ok"), "message", d.get("message"))
print("applied", len(d.get("applied") or []), "errors", len(d.get("errors") or []))
for a in d.get("applied") or []:
    print(" +", a.get("action"), a.get("worker_id"), a.get("type"))
for e in d.get("errors") or []:
    print(" !", e)
'

echo "== direct stop any still listed =="
mapfile -t WIDS < <(curl -sS "${H[@]}" \
  -d '{"dry_run":true,"zombie_types":["hello_watcher"]}' \
  "$BASE/v1/ops/cleanup" | python3 -c '
import sys, json
d = json.load(sys.stdin)
for c in d.get("candidates") or []:
    wid = c.get("worker_id")
    if wid:
        print(wid)
')

if [[ ${#WIDS[@]} -eq 0 ]]; then
  echo "(none left after cleanup apply)"
else
  for wid in "${WIDS[@]}"; do
    echo "direct stop $wid"
    curl -sS "${H[@]}" -d '{"reason":"stab0 d5 direct stop hello_watcher"}' \
      "$BASE/v1/workers/$wid/stop" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(" ", d.get("status") or d.get("detail") or list(d)[:6])
'
  done
fi

echo "== verify =="
bash "$(dirname "$0")/stab0_verify_hellos.sh"
