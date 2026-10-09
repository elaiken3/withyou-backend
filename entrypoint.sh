#!/usr/bin/env sh
set -eu

# If the APNs key is provided as base64 (APNS_AUTH_KEY_B64), write it to the file
# the app reads (APNS_AUTH_KEY_PATH).
#
# The container runs as a non-root user that can only write under /app. If the
# configured path's directory isn't writable, the key goes to $APP_SECRETS_DIR
# instead and APNS_AUTH_KEY_PATH is updated for the app. Writing the key must
# never stop the API or worker from starting: without it, pushes are skipped and
# logged, while device registration keeps working.
if [ -n "${APNS_AUTH_KEY_B64:-}" ] && [ -n "${APNS_AUTH_KEY_PATH:-}" ]; then
  secrets_dir="${APP_SECRETS_DIR:-/app/secrets}"
  target="$APNS_AUTH_KEY_PATH"
  target_dir="$(dirname "$target")"

  if ! mkdir -p "$target_dir" 2>/dev/null || [ ! -w "$target_dir" ]; then
    target="$secrets_dir/$(basename "$APNS_AUTH_KEY_PATH")"
    echo "entrypoint: $target_dir is not writable; writing the APNs key to $target instead" >&2
    mkdir -p "$secrets_dir" 2>/dev/null || true
  fi

  old_umask="$(umask)"
  umask 077
  if printf '%s' "$APNS_AUTH_KEY_B64" | base64 -d > "$target" 2>/dev/null; then
    export APNS_AUTH_KEY_PATH="$target"
  else
    echo "entrypoint: could not write the APNs key to $target; push delivery is disabled" >&2
  fi
  umask "$old_umask"
fi

exec "$@"
