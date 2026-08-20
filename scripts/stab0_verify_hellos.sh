#!/usr/bin/env bash
set -euo pipefail
KEY="${ATLAS_API_KEY:-}"
if [[ -z "$KEY" ]]; then
  KEY=$(grep '^ATLAS_API_KEYS=' /data/atlas/.env | cut -d= -f2- | cut -d, -f1 | tr -d '"' | tr -d "'")
fi
curl -sS -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"dry_run":true,"zombie_types":["hello_watcher"]}' \
  http://127.0.0.1:8000/v1/ops/cleanup | python3 -c '
import sys,json
d=json.load(sys.stdin)
print("ok", d.get("ok"), "candidates", (d.get("counts") or {}).get("candidates"))
for c in d.get("candidates") or []:
    print(" ", c.get("type"), c.get("worker_id"), c.get("status"), c.get("mission_status"), c.get("reason"))
if not (d.get("candidates") or []):
    print("CLEAN — no hello_watcher zombies left")
'
