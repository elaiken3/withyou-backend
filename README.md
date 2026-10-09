# WithYou Backend

Backend for **With You**, a local-first support app that helps ADHD brains get started, stay focused, and refocus without pressure or shame.

The app works fully without this backend. Reminders and the daily check-in are local notifications on the phone, and AI features run on the device (Apple Intelligence) or fall back to simple rules. This backend does one optional thing: **cloud AI** for people who turn it on in Settings, through one Supabase Edge Function, `ai`, that calls Claude.

See [WITHYOU_BACKEND_PRINCIPLES.md](WITHYOU_BACKEND_PRINCIPLES.md) (the rules), [ARCHITECTURE.md](ARCHITECTURE.md) (how it fits together) and [docs/CUTOVER.md](docs/CUTOVER.md) (setting up the Supabase project and retiring the old Fly.io + MongoDB backend).

---

## Core principles

- **Off by default.** Cloud AI only runs after the person turns it on, with a plain explanation of what is sent.
- **Nothing stored with your words.** The server never stores the text of a request or the model's reply, and never logs them. It keeps only per-day request counts, deleted after 35 days.
- **No accounts.** Each install signs in anonymously (a random id, no email, no password).
- **Suggestions, not actions.** The AI suggests; the app shows it and the person decides.
- **Gentle limits.** Daily per-person and global limits keep costs predictable. Reaching one is never framed as a failure, and the app falls back to on-device AI or rules.
- **User-controlled deletion.** The `delete_me` task removes everything WithYou stores for that person (their usage counts and anonymous account). Supabase's short-lived platform request logs expire on their own.

---

## What is sent and stored

| Where | What | Kept |
| --- | --- | --- |
| Request to the `ai` function | The text of that one request (for example the words to sort, or a task title), plus the person's anonymous access token | Not stored |
| Request to Anthropic (Claude) | The same text, wrapped in a fixed prompt | Not stored by WithYou. Anthropic processes it under its API terms |
| `public.ai_usage` | anonymous user id, UTC day, request count | 35 days (deleted daily by `pg_cron`), or until `delete_me` |
| `public.ai_usage_global` | UTC day, total request count | 35 days |
| `auth.users` | the anonymous user Supabase Auth creates on sign-in | until `delete_me` |
| Function logs | task name, HTTP status, latency, error class | Supabase log retention. Never request text, model output, tokens or user ids |
| Supabase platform logs (API gateway, Auth, Edge Functions) | IP address, user agent, time and request path; Auth logs also hold the anonymous user id. Never request text | Supabase's log retention (1 day on Free, 7 days on Pro). Not removed by `delete_me` |

---

## API

`POST https://<project-ref>.supabase.co/functions/v1/ai`

Headers:

| Header | Value |
| --- | --- |
| `apikey` | the project's publishable (or legacy anon) key |
| `Authorization` | `Bearer <access token from Supabase anonymous sign-in>` |
| `Content-Type` | `application/json` |

Body (at most 16 KB; unknown fields are ignored):

```json
{"task": "<task>", "input": { ... }}
```

Success: HTTP 200 `{"ok": true, "task": "<task>", "result": { ... }}`

Error: `{"ok": false, "error": "<code>", "message": "<short human text>"}`

| Status | `error` | When |
| --- | --- | --- |
| 400 | `invalid_input` | the body isn't JSON, the task is unknown, or `input` breaks the rules below |
| 401 | `unauthorized` | no `Authorization: Bearer` token, or Supabase Auth doesn't accept it |
| 405 | `method_not_allowed` | anything but `POST` (also sends `Allow: POST`) |
| 413 | `too_large` | body over 16 KB |
| 429 | `quota_exceeded` | a daily limit is reached; `Retry-After` is the seconds until the next UTC midnight |
| 502 | `upstream_error` | Claude declined, timed out, failed, or answered in an unusable shape |
| 503 | `not_configured` | `ANTHROPIC_API_KEY` isn't set (AI tasks only; `delete_me` still works) |
| 500 | `internal` | anything else (for example the database is unreachable) |

All string outputs are plain text (no markdown), trimmed, and capped to the lengths below. Numbers are rounded and clamped into range.

Order of checks: method, size, access token, JSON and task, input. Only a request that passes all of them counts toward the daily limit, and it counts before Claude is called (so a 502 still counts).

### `capture`: turn typed or spoken text into one or more items

```json
{"text": "string, 1-4000 characters",
 "now": "2026-10-09T14:05:00-04:00",
 "timezone": "America/New_York",
 "morning_hour": 9, "evening_hour": 19}
```

`now` is the device's local time with its UTC offset (required). `timezone` is an IANA name (required). `morning_hour` and `evening_hour` are optional (defaults 9 and 19).

```json
{"items": [
  {"title": "1-80, verb first when natural",
   "first_step": "1-100, a tiny concrete action under 2 minutes",
   "estimate_minutes": 1,
   "when": null}
]}
```

1 to 12 items. `when` is `null` unless the text names a day or time, then `{"day_offset": 0-30, "hour": 0-23, "minute": 0-59}`, with `day_offset` counted from `now`'s local date ("tomorrow" is 1, "tonight" is 0 at `evening_hour`, "this weekend" is the coming Saturday at `morning_hour`). A model answer more than 30 days out becomes `null` (Inbox) rather than a wrong date.

### `break_down`: split a task into tiny steps

Input `{"title": "1-200", "current_step": "0-200, optional"}`. Result `{"steps": ["2 to 5 steps, each 1-100 characters, verb first"]}`.

### `stuck_help`: one gentle next move when stuck

Input `{"title": "1-200", "blocker": "dont_know_where_to_start" | "too_big" | "boring" | "worried" | "low_energy" | "distracted", "energy": "low" | "okay" | "good" | null}`. Result `{"message": "1-160", "step": "1-100", "minutes": 1-10}`.

### `suggest_next`: pick one thing to do now

Input `{"energy": "low" | "okay" | "good" | null, "minutes_available": null | 5-240, "candidates": [{"id": "1-128 characters, unique", "title": "1-200", "estimate_minutes": null | 1-240, "scheduled_in_minutes": null | -1440-10080}]}` with 1 to 30 candidates. Result `{"id": "<one of the candidate ids>", "reason": "1-120", "first_step": "1-100"}`. The app's ids are never sent to Claude; it sees short keys that the function maps back.

### `tidy`: tidy up thoughts jotted down during a focus session

Input `{"thoughts": ["1 to 30 strings, 1-500 characters each"]}`. Result `{"items": [{"title": "1-80", "first_step": "1-100"}]}`, same count and order as the input.

### `delete_me`: delete everything the server holds for this person

Input `{}`. Result `{"deleted": true}`. Deletes the person's usage rows and their anonymous auth user. Doesn't count toward the limits and works even when cloud AI isn't configured.

---

## Limits

| Setting | Default | Meaning |
| --- | --- | --- |
| `AI_DAILY_LIMIT_PER_USER` | 60 | requests per anonymous user per UTC day |
| `AI_DAILY_LIMIT_GLOBAL` | 3000 | requests from everyone together per UTC day |

The counting is one atomic database call (`public.ai_consume_quota`). Setting either limit to `0` turns cloud AI off (every AI request gets 429, and the app quietly uses on-device AI or rules).

---

## Configuration

Edge Function secrets (`supabase secrets set NAME=value`):

| Name | Required | Default | Notes |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | yes | none | Without it, AI tasks return 503 `not_configured` |
| `CLAUDE_MODEL` | no | `claude-opus-5-5` | `claude-haiku-5-5` is a much cheaper option (see cost below) |
| `AI_DAILY_LIMIT_PER_USER` | no | `60` | whole number, `0` turns cloud AI off |
| `AI_DAILY_LIMIT_GLOBAL` | no | `3000` | whole number, `0` turns cloud AI off |
| `ANTHROPIC_BASE_URL` | no | Anthropic's API | only for tests (CI points it at an unreachable address) |

Set by Supabase for every function (nothing to do): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. If the service role key is ever absent, the function uses `SUPABASE_SECRET_KEY`, then the `default` entry of `SUPABASE_SECRET_KEYS`.

GitHub Actions secrets for deploys: `SUPABASE_ACCESS_TOKEN`, `SUPABASE_PROJECT_REF`, `SUPABASE_DB_PASSWORD`. Without them the deploy workflow skips with a notice.

### Model and cost

Requests use Claude Opus 5.5 by default: one message with a JSON schema for the answer, low effort, and Anthropic's server-side fallback model if Claude declines (`fallbacks: "default"`; not available on Haiku). A typical request is about 1,000 input tokens and a few hundred output tokens (including low-effort thinking).

| Model | Price per million tokens (input / output) | Typical cost per request |
| --- | --- | --- |
| `claude-opus-5-5` (default) | $4 / $20 | about 1 to 3 US cents |
| `claude-haiku-5-5` | $0.10 / $0.50 | well under a tenth of a cent |

The global limit caps the worst case: at 3,000 requests a day on Opus 5.5 that is roughly $30 to $90 a day. Set `AI_DAILY_LIMIT_GLOBAL` to what you're comfortable spending and add a spend limit in the Anthropic Console. Switching models is one command (`supabase secrets set CLAUDE_MODEL=claude-haiku-5-5`); no redeploy is needed. Prices are Anthropic's list prices as of October 2026.

---

## Repository structure

```text
withyou-backend/
├─ supabase/
│  ├─ config.toml                       # Supabase CLI project (anonymous sign-ins on, ai: verify_jwt = false)
│  ├─ migrations/
│  │  └─ 20261009120000_ai_usage.sql    # usage tables, ai_consume_quota, retention job
│  ├─ tests/database/
│  │  └─ ai_usage.test.sql              # pgTAP tests (supabase test db)
│  └─ functions/
│     ├─ .env.example                   # local secrets template
│     └─ ai/
│        ├─ index.ts                    # Deno.serve entry point (wiring only)
│        ├─ handler.ts                  # request handling, status codes, limits, logging
│        ├─ tasks.ts                    # per-task validation, prompts, JSON schemas, output clamping
│        ├─ claude.ts                   # Anthropic SDK call
│        ├─ supabase.ts                 # token check, quota, deletion (service-role client)
│        ├─ deno.json                   # pinned npm imports used when bundling
│        └─ *_test.ts                   # deno test, with fakes (no network)
├─ scripts/smoke_test.sh                # end-to-end check against a local Supabase stack
├─ deno.json                            # same pins, plus fmt/lint settings, for running Deno from the repo root
├─ docs/CUTOVER.md                      # project setup and Fly.io/MongoDB retirement
└─ .github/workflows/                   # ci.yml (tests), deploy.yml (migrations + function)
```

---

## Running locally

You need the [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started), Docker, and [Deno 2](https://docs.deno.com/runtime/getting_started/installation/).

```bash
supabase start                                   # Postgres, Auth, REST, gateway; applies migrations
cp supabase/functions/.env.example supabase/functions/.env
# put a real ANTHROPIC_API_KEY in supabase/functions/.env (it is gitignored)
supabase functions serve                         # serves http://127.0.0.1:54321/functions/v1/ai
```

Try it (`supabase status` prints the publishable key):

```bash
API=http://127.0.0.1:54321
KEY=<publishable key from supabase status>
TOKEN=$(curl -sS -X POST "$API/auth/v1/signup" -H "apikey: $KEY" -H "Content-Type: application/json" -d '{}' | jq -r .access_token)

curl -sS -X POST "$API/functions/v1/ai" \
  -H "apikey: $KEY" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task": "break_down", "input": {"title": "Clean the kitchen"}}'
# -> {"ok":true,"task":"break_down","result":{"steps":["...","..."]}}
```

## Tests

```bash
deno fmt --check
deno lint
deno check supabase/functions/ai/index.ts
deno test -A supabase/functions/ai     # handler, tasks, Claude and Supabase calls, all with fakes
supabase test db                       # pgTAP: tables, privileges, quota, retention, deletion
bash scripts/smoke_test.sh             # needs `supabase start`; never calls Anthropic
```

CI (`.github/workflows/ci.yml`) runs all of these on every pull request. A push to `main` runs the same CI and then `deploy.yml`, which applies migrations and deploys the function when the deploy secrets are set.
