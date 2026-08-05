#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 URL_FILE" >&2
  exit 64
fi

url_file="$1"

if [[ ! -f "$url_file" ]]; then
  echo "URL file not found: $url_file" >&2
  exit 66
fi

while IFS= read -r url || [[ -n "$url" ]]; do
  [[ -z "$url" || "$url" =~ ^[[:space:]]*# ]] && continue
  "$(dirname "$0")/download-one.sh" "$url"
done < "$url_file"
