#!/usr/bin/env bash
# Smoke test for the `ai` Edge Function on a local Supabase stack.
#
# Run `supabase start` first. This serves the function with a dummy Anthropic key pointed at an
# address nothing listens on, so no request ever reaches Anthropic, and a per-user limit of 1.
# It waits until a valid request from a throwaway user gets 502 (proof that this instance, with
# these settings, is the one answering), then checks auth, quota and deletion end to end:
#   no token -> 401, valid request -> 502 (quota used, upstream unreachable), again -> 429,
#   delete_me -> 200, the deleted user's token -> 401.
#
# Set FUNCTIONS_LOG to keep the function's log somewhere (CI prints it on failure).
set -euo pipefail

work="$(mktemp -d)"
log="${FUNCTIONS_LOG:-$work/functions.log}"
serve_pid=""

finish() {
  local status=$?
  if [ -n "$serve_pid" ]; then kill "$serve_pid" 2>/dev/null || true; fi
  if [ "$status" -ne 0 ]; then
    echo "::group::Function logs"
    cat "$log" 2>/dev/null || true
    echo "::endgroup::"
  fi
  exit "$status"
}
trap finish EXIT

# Keep only KEY=value lines, in case the CLI prints anything else. If that finds no API_URL (a
# CLI that formats its output differently), read the same names from the JSON output instead.
supabase status -o env | grep -E '^[A-Z][A-Z0-9_]*=' >"$work/status.env" || true
if ! grep -q '^API_URL=' "$work/status.env"; then
  supabase status -o json |
    jq -r 'to_entries[] | select(.value | type == "string") | "\(.key)=\"\(.value)\""' |
    grep -E '^[A-Z][A-Z0-9_]*=' >"$work/status.env" || true
fi
set -a
# shellcheck disable=SC1091
. "$work/status.env"
set +a
: "${API_URL:?supabase status did not report API_URL}"
api_key="${PUBLISHABLE_KEY:-${ANON_KEY:-}}"
if [ -z "$api_key" ]; then
  echo "supabase status reported neither PUBLISHABLE_KEY nor ANON_KEY" >&2
  exit 1
fi
fn="$API_URL/functions/v1/ai"

cat >"$work/functions.env" <<'ENV'
ANTHROPIC_API_KEY=dummy
ANTHROPIC_BASE_URL=http://127.0.0.1:9
AI_DAILY_LIMIT_PER_USER=1
ENV

supabase functions serve --env-file "$work/functions.env" >"$log" 2>&1 &
serve_pid=$!

# sign_in: prints an access token for a new anonymous user.
sign_in() {
  local response token
  response="$(curl -sS --max-time 30 -X POST "$API_URL/auth/v1/signup" \
    -H "apikey: $api_key" -H "Content-Type: application/json" -d '{}')"
  token="$(jq -r '.access_token // empty' <<<"$response")"
  if [ -z "$token" ]; then
    echo "anonymous sign-in returned no access token: $response" >&2
    return 1
  fi
  printf '%s' "$token"
}

request='{"task":"break_down","input":{"title":"Water the plants"}}'

# `supabase start` may already serve functions without our env file (it answers 503
# not_configured). Ready means our instance answers: with the dummy key and the unreachable
# Anthropic address, a valid request from a throwaway user gets 502 upstream_error.
echo "Waiting for the function to start with the test settings..."
warmup_token="$(sign_in)"
ready=""
code=""
for _ in $(seq 1 90); do
  code="$(curl -s -o "$work/warmup" -w '%{http_code}' --max-time 60 -X POST "$fn" \
    -H "apikey: $api_key" -H "Authorization: Bearer $warmup_token" \
    -H "Content-Type: application/json" -d "$request" || true)"
  if [ "$code" = "502" ] && grep -q '"error":"upstream_error"' "$work/warmup"; then
    ready="yes"
    break
  fi
  if ! kill -0 "$serve_pid" 2>/dev/null; then
    echo "supabase functions serve exited early" >&2
    exit 1
  fi
  sleep 2
done
if [ -z "$ready" ]; then
  echo "The function did not become ready (last status: ${code:-none})" >&2
  cat "$work/warmup" >&2 2>/dev/null || true
  exit 1
fi
echo "ok - function is up with the test settings"

# expect <description> <status> <curl args...>
expect() {
  local description="$1" want="$2"
  shift 2
  local got
  got="$(curl -sS -o "$work/body" -D "$work/headers" -w '%{http_code}' --max-time 60 "$@")"
  if [ "$got" != "$want" ]; then
    echo "not ok - $description: expected HTTP $want, got $got" >&2
    cat "$work/body" >&2
    echo >&2
    exit 1
  fi
  echo "ok - $description (HTTP $got)"
}

body_has() {
  if ! grep -q "$1" "$work/body"; then
    echo "not ok - response body is missing $1" >&2
    cat "$work/body" >&2
    exit 1
  fi
}

json=(-H "apikey: $api_key" -H "Content-Type: application/json")

expect "GET is not allowed" 405 -X GET "$fn" -H "apikey: $api_key"
expect "no access token" 401 -X POST "$fn" "${json[@]}" -d "$request"
expect "a made-up access token" 401 -X POST "$fn" "${json[@]}" \
  -H "Authorization: Bearer not-a-real-token" -d "$request"

token="$(sign_in)"
echo "ok - anonymous sign-in"
authed=("${json[@]}" -H "Authorization: Bearer $token")

expect "invalid input" 400 -X POST "$fn" "${authed[@]}" -d '{"task":"break_down","input":{"title":""}}'
body_has '"error":"invalid_input"'

head -c 17000 /dev/zero | tr '\0' 'a' >"$work/big.txt"
expect "a body over 16 KB" 413 -X POST "$fn" "${authed[@]}" --data-binary @"$work/big.txt"

expect "valid request: quota counted, Claude unreachable" 502 -X POST "$fn" "${authed[@]}" -d "$request"
body_has '"error":"upstream_error"'

expect "second request over the per-user limit of 1" 429 -X POST "$fn" "${authed[@]}" -d "$request"
body_has '"error":"quota_exceeded"'
if ! grep -qiE '^retry-after: [0-9]+' "$work/headers"; then
  echo "not ok - 429 without a Retry-After header" >&2
  cat "$work/headers" >&2
  exit 1
fi
echo "ok - Retry-After is set"

expect "delete_me" 200 -X POST "$fn" "${authed[@]}" -d '{"task":"delete_me","input":{}}'
body_has '"deleted":true'

expect "the deleted user's token no longer works" 401 -X POST "$fn" "${authed[@]}" -d "$request"

echo "Smoke test passed."
