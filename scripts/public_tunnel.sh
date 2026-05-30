#!/usr/bin/env bash
# Expose the local OfficeLego web UI on a public HTTPS URL (Cloudflare Quick Tunnel).
# Requires: cloudflared — brew install cloudflared
#
# Usage:
#   export OFFICELEGO_AUTH_TOKEN="$(openssl rand -hex 16)"
#   python main.py --web --public --no-browser &
#   ./scripts/public_tunnel.sh 5757

set -euo pipefail
PORT="${1:-5757}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Install cloudflared first: brew install cloudflared"
  exit 1
fi

echo "Tunneling http://127.0.0.1:${PORT} to the internet…"
echo "Keep this terminal open. Share the https://*.trycloudflare.com URL with your token."
exec cloudflared tunnel --url "http://127.0.0.1:${PORT}"
