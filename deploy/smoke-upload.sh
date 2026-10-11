#!/usr/bin/env bash
# Signs up, uploads a small PNG through a pre-signed link, completes it and downloads it
# again, all through the public entrance (Caddy). Usage: deploy/smoke-upload.sh <site-url>
set -euo pipefail
site=${1:?usage: smoke-upload.sh <site-url>}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cookies="$work/cookies"

api() { # method path [json]
  curl --fail-with-body --silent --show-error -b "$cookies" -c "$cookies" \
    -X "$1" -H 'Content-Type: application/json' ${3:+--data "$3"} "$site$2"
}

api POST /v1/auth/signup \
  "{\"email\":\"smoke-$RANDOM$RANDOM@example.com\",\"password\":\"smoke test password\",\"name\":\"Smoke\"}" >/dev/null
workspace=$(api GET /v1/workspaces | jq -r '.items[0].id')

# A 1x1 transparent PNG.
printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==' \
  | base64 -d >"$work/pixel.png"
size=$(wc -c <"$work/pixel.png")
sha=$(sha256sum "$work/pixel.png" | cut -d' ' -f1)

created=$(api POST "/v1/workspaces/$workspace/assets" \
  "{\"kind\":\"reference\",\"filename\":\"pixel.png\",\"content_type\":\"image/png\",\"size\":$size,\"sha256\":\"$sha\"}")
url=$(jq -r '.upload.url' <<<"$created")
asset=$(jq -r '.asset.id' <<<"$created")
mapfile -t headers < <(jq -r '.upload.headers | to_entries[] | "\(.key): \(.value)"' <<<"$created")
curl --fail-with-body --silent --show-error -X PUT "${headers[@]/#/-H}" \
  --data-binary "@$work/pixel.png" "$url" >/dev/null

done=$(api POST "/v1/workspaces/$workspace/assets/$asset/complete")
[[ $(jq -r '"\(.status) \(.width)x\(.height)"' <<<"$done") == "ready 1x1" ]] \
  || { echo "unexpected asset: $done"; exit 1; }
curl --fail-with-body --silent --show-error -o "$work/back.png" "$(jq -r '.download_url' <<<"$done")"
cmp "$work/pixel.png" "$work/back.png"
echo "upload through $site: ok"
