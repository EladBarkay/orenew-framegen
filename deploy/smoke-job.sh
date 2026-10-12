#!/usr/bin/env bash
# Signs up, starts a demo job and polls it until it ends, all through the public entrance
# (Caddy); checks that the worker ran it. Usage: deploy/smoke-job.sh <site-url>
set -euo pipefail
site=${1:?usage: smoke-job.sh <site-url>}
cookies=$(mktemp)
trap 'rm -f "$cookies"' EXIT

api() { # method path [json]
  curl --fail-with-body --silent --show-error -b "$cookies" -c "$cookies" \
    -X "$1" -H 'Content-Type: application/json' ${3:+--data "$3"} "$site$2"
}

api POST /v1/auth/signup \
  "{\"email\":\"smoke-$RANDOM$RANDOM@example.com\",\"password\":\"smoke test password\",\"name\":\"Smoke\"}" >/dev/null
workspace=$(api GET /v1/workspaces | jq -r '.items[0].id')
job=$(api POST "/v1/workspaces/$workspace/jobs/demo" '{"steps":3}' | jq -r '.id')

for _ in $(seq 60); do
  status=$(api GET "/v1/workspaces/$workspace/jobs/$job" | jq -r '.status')
  case $status in
    succeeded) echo "demo job through $site: ok"; exit 0 ;;
    failed) echo "demo job failed: $(api GET "/v1/workspaces/$workspace/jobs/$job")"; exit 1 ;;
  esac
  sleep 1
done
echo "demo job still $status after a minute"
exit 1
