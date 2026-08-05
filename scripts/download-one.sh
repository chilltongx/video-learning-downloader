#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 VIDEO_URL" >&2
  echo "Optional env: OUTPUT_DIR, QUALITY, COOKIES_FROM_BROWSER" >&2
  exit 64
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
url="$1"
output_dir="${OUTPUT_DIR:-$HOME/video}"
quality="${QUALITY:-1080}"
cookies_from_browser="${COOKIES_FROM_BROWSER:-}"

args=(
  "$script_dir/download-for-editing.py"
  "$url"
  --output-dir "$output_dir"
  --quality "$quality"
)

if [[ -n "$cookies_from_browser" ]]; then
  args+=(--cookies-from-browser "$cookies_from_browser")
fi

exec python3 "${args[@]}"
