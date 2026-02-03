#!/usr/bin/env sh
set -eu

# If APNs key is provided as base64, write it to the expected path
if [ -n "${APNS_AUTH_KEY_B64:-}" ] && [ -n "${APNS_AUTH_KEY_PATH:-}" ]; then
  mkdir -p "$(dirname "$APNS_AUTH_KEY_PATH")"
  echo "$APNS_AUTH_KEY_B64" | base64 -d > "$APNS_AUTH_KEY_PATH"
fi

exec "$@"
