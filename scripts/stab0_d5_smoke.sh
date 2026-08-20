#!/usr/bin/env bash
# OI-STAB0 D5 — post-bounce smoke (run on host)
# Auth: Authorization: Bearer <key> from ATLAS_API_KEYS
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${ATLAS_BASE_URL:-http://127.0.0.1:8000}"

if [[ -z "${ATLAS_API_KEY:-}" ]]; then
  ATLAS_API_KEY="$(python3 - <<'PY'
from pathlib import Path
for p in (Path("/data/atlas/.env"), Path("/etc/atlas/atlas.env")):
    if not p.exists():
        continue
    try:
        text = p.read_text()
    except PermissionError:
        continue
    for line in text.splitlines():
        if line.startswith("ATLAS_API_KEYS="):
            print(line.split("=", 1)[1].split(",")[0].strip().strip('"').strip("'"))
            raise SystemExit
print("", end="")
PY
)"
fi

if [[ -z "${ATLAS_API_KEY}" ]]; then
  echo "ERROR: no ATLAS_API_KEY — set it or ensure $ROOT/.env is readable" >&2
  exit 1
fi

H=(-H "Authorization: Bearer ${ATLAS_API_KEY}")
echo "== health =="
curl -sS -m 5 -o /dev/null -w "HTTP %{http_code}\n" "$BASE/v1/health" || true

echo "== budgets =="
curl -sS -m 8 "${H[@]}" "$BASE/v1/resources/budgets" | python3 -m json.tool | head -40

echo "== guard =="
curl -sS -m 8 "${H[@]}" "$BASE/v1/resources/guard" | python3 -c '
import sys,json
d=json.load(sys.stdin)
if d.get("detail"):
    print("  ERROR:", d.get("detail")); raise SystemExit(1)
for k in ("version","max_concurrent_ticks","max_archive_workers","configured_max_archive_workers","archive_rth_clamped","archive_workers_running"):
    print(f"  {k}: {d.get(k)}")
'

echo "== market-data =="
curl -sS -m 8 "${H[@]}" "$BASE/v1/market-data/status" | python3 -m json.tool | head -45

echo "== session-readiness =="
curl -sS -m 8 "${H[@]}" "$BASE/v1/market/session-readiness" | python3 -m json.tool | head -90

echo "== activity/today =="
curl -sS -m 8 "${H[@]}" "$BASE/v1/activity/today" | python3 -c '
import sys,json
d=json.load(sys.stdin)
if d.get("detail"):
    print("  ERROR:", d.get("detail")); raise SystemExit(1)
print("  day", d.get("day_ist"), "count", d.get("count") or len(d.get("events") or []))
'

echo "== cleanup dry-run (duplicates) =="
curl -sS -m 20 "${H[@]}" -H "Content-Type: application/json" \
  -d '{"dry_run":true,"include_duplicates":true}' \
  "$BASE/v1/ops/cleanup" | python3 -c '
import sys,json
d=json.load(sys.stdin)
if d.get("detail"):
    print("  ERROR:", d.get("detail")); raise SystemExit(1)
print("  ok", d.get("ok"), d.get("message"))
print("  counts", d.get("counts"))
dups=[c for c in (d.get("candidates") or []) if "duplicate" in str(c.get("reason","")).lower()]
print("  duplicate candidates", len(dups))
for c in dups[:10]:
    print("   ", c.get("type"), c.get("worker_id"), c.get("mission_id"), c.get("reason"))
z=[c for c in (d.get("candidates") or []) if str(c.get("reason","")).startswith("zombie")]
print("  zombie candidates", len(z))
for c in z[:10]:
    print("   ", c.get("type"), c.get("worker_id"), c.get("mission_id"), c.get("reason"))
other=[c for c in (d.get("candidates") or []) if c not in dups and c not in z]
print("  other candidates", len(other))
for c in other[:10]:
    print("   ", c.get("type"), c.get("worker_id"), c.get("reason"))
'

echo "DONE — for apply duplicates (after review):"
echo "  curl -sS -H \"Authorization: Bearer \$ATLAS_API_KEY\" -H Content-Type:application/json \\"
echo "    -d '{\"dry_run\":false,\"include_duplicates\":true,\"reason\":\"stab0 d5 retire duplicates\"}' \\"
echo "    $BASE/v1/ops/cleanup"
