# WithYou Backend — Architecture Overview

This backend supports the WithYou app with minimal pressure
and minimal inference.

Primary responsibility:
- answer optional cloud AI requests, within daily limits

It does not:
- store what people write
- send notifications (reminders and check-ins are local to the phone)
- decide priorities, infer motivation, or optimize productivity


## Components

```text
 iOS app ──(1) anonymous sign-in──▶ Supabase Auth
    │
    └──(2) POST /functions/v1/ai ──▶ Edge Function `ai` (Deno)
                                       ├─(3) check token ──▶ Supabase Auth (auth.getUser)
                                       ├─(4) count quota ──▶ Postgres: public.ai_consume_quota()
                                       └─(5) one message ──▶ Anthropic API (Claude)
```

- **Supabase Auth** gives each install an anonymous user (no email, no password). The app keeps
  the session in the Keychain and refreshes it.
- **Edge Function `ai`** (`supabase/functions/ai/`) is stateless. The gateway's JWT check is off
  (`verify_jwt = false`) because the function checks the token itself with a service-role client,
  which works with both legacy JWT keys and the new publishable/secret keys.
- **Postgres** holds two counter tables and two functions. Nothing else.
- **Anthropic** runs Claude. The function uses the official TypeScript SDK.
- **pg_cron** deletes counters older than 35 days, every day at 03:17 UTC.

There is no queue, worker, or push service. The old Fly.io API and worker, MongoDB, and APNs
integration are retired (see [docs/CUTOVER.md](docs/CUTOVER.md)).


## Code layout

| File | Role |
| --- | --- |
| `index.ts` | `Deno.serve` entry point. Wires real dependencies into the handler. |
| `handler.ts` | Pure request handling. Every outside dependency is injected: `verifyUser`, `consumeQuota`, `deleteUserData`, `callClaude`, `now`, `env`, `log`. |
| `tasks.ts` | Per task: input validation, system prompt, JSON schema, output validation and clamping. No I/O. |
| `claude.ts` | The Anthropic SDK call and the mapping of SDK errors and stop reasons to `UpstreamError`. |
| `supabase.ts` | Token check, quota call and deletion through `@supabase/supabase-js`. |

Tests (`*_test.ts`) run the handler with fakes, and run the real SDK clients against a fake
`fetch`, so nothing leaves the machine.


## Request flow

1. Anything but `POST` → 405. A body over 16 KB (declared or streamed) → 413.
2. `Authorization: Bearer <token>` is required. `auth.getUser(token)` must return a user;
   a 4xx from Auth → 401. Auth being unreachable → 500 (not 401, so the app doesn't sign in again
   for nothing).
3. The body must be a JSON object with a known `task`. `delete_me` is handled here (step 8).
4. `tasks.ts` validates `input` → 400 with a message that names the field but never echoes it.
5. No `ANTHROPIC_API_KEY` → 503.
6. `ai_consume_quota(user, per-user limit, global limit)` → `false` → 429 with `Retry-After`
   set to the seconds until the next UTC midnight.
7. Claude is called once (see below). Refusal, `max_tokens`, timeouts, API errors, or JSON that
   doesn't fit → 502. Otherwise the answer is cleaned and clamped, then returned with 200.
8. `delete_me`: delete the person's `ai_usage` rows, then their auth user (`auth.admin.deleteUser`).
   Doesn't touch quota and works without an Anthropic key.

Any unexpected exception → 500.


## Calling Claude

- Model: `CLAUDE_MODEL`, default `claude-opus-5-5`.
- One request per call: a stable system prompt per task, one user message, `max_tokens` 16000,
  `output_config: { effort: "low", format: { type: "json_schema", schema } }`. No `thinking`
  setting (Opus 5.5 always thinks adaptively; low effort keeps it short), no sampling parameters,
  no prefill.
- On Opus 5.x, Fable 5.x and Sonnet 5.5 the request uses the beta endpoint with
  `betas: ["server-side-fallback-2026-07-01"]` and `fallbacks: "default"`: if Claude declines,
  Anthropic re-runs it on its recommended fallback model in the same call. Haiku 5.5 has no
  server-side fallback, so it uses the plain endpoint.
- SDK client: 25 s timeout, 1 retry. `ANTHROPIC_BASE_URL` is honored (CI points it at an
  unreachable address).
- The answer is the first `text` block (thinking and fallback blocks are skipped), parsed with
  `JSON.parse`, then validated and clamped in `tasks.ts`.
- The person's data goes into the user message as JSON inside `<request_data>` tags, with every
  `<` written as the JSON escape `\u003c`, so it can't close the tag. The system prompt says that everything inside
  is material to work with, never instructions.
- `suggest_next` sends candidate keys (`c1`, `c2`, ...) instead of the app's ids and maps the
  answer back. `tidy` labels thoughts `t1`, `t2`, ... and reorders the answer by label.
- Schemas use only `type`, `properties`, `required`, `items`, `enum`, `additionalProperties` and
  `description`; every object has `additionalProperties: false` and requires every property.
  Lengths and ranges are enforced after parsing. `capture`'s `when` is an object with a
  `scheduled` flag rather than a nullable object.


## Data model (Postgres)

| Table | Key | Columns |
| --- | --- | --- |
| `public.ai_usage` | `(user_id, day)` | `user_id uuid` → `auth.users(id) on delete cascade`, `day date` (UTC), `count int` |
| `public.ai_usage_global` | `day` | `day date` (UTC), `count int` |

Both tables have RLS on with no policies, and all privileges revoked from `anon` and
`authenticated`. Only `service_role` (the function) can read or write them.

`public.ai_consume_quota(p_user uuid, p_user_limit int, p_global_limit int) returns boolean`
is `security definer` with `search_path = ''`, executable only by `service_role`. It:

1. creates today's global row if needed (`insert ... on conflict do nothing`),
2. locks today's global row, then the person's row (`select ... for update`), always in that
   order, so concurrent calls queue instead of racing past a limit and can't deadlock,
3. returns `false` without changing anything if either count is already at its limit,
4. otherwise adds one to both and returns `true`.

A limit below 1 always returns `false`, which makes `0` a simple off switch.

`public.ai_usage_purge(p_keep_days int default 35)` deletes older rows from both tables. The
migration schedules it with pg_cron when pg_cron is available, and skips scheduling (with a notice)
on a Postgres without it.


## Logging

One line per request: `{"fn":"ai","task":...,"status":...,"latency_ms":...,"error":...}`.
`task` is a known task name or `unknown` (an unknown task string from a client is never logged).
`error` is a fixed code such as `quota_exceeded`, `upstream_refusal` or `internal_quota_Error`:
never an exception message, request text, model output, token or user id. A test feeds a marker
through every path and checks that it never reaches the logger.


## Operations

- **Deploys:** `deploy.yml` runs CI, then `supabase db push` and `supabase functions deploy ai`.
- **Turning cloud AI off quickly:** `supabase secrets set AI_DAILY_LIMIT_GLOBAL=0` (every AI request
  gets 429) or `supabase secrets unset ANTHROPIC_API_KEY` (503). The app falls back to on-device AI
  or rules either way.
- **Retention check:** `select jobname, schedule, command from cron.job;` shows
  `withyou-ai-usage-retention`.
- **Abuse:** the per-user limit only limits one anonymous account, and anyone can create more.
  Supabase Auth rate limits anonymous sign-ins per IP (30 per hour by default), so a single IP
  could still use up the whole global limit in a couple of hours, and cloud AI would then pause
  for everyone until UTC midnight (the app falls back to on-device AI or rules). Lower the
  anonymous sign-in limit to about 5 per hour per IP: each install signs in once and then only
  refreshes its token. The global limit bounds the cost either way. CAPTCHA or App Attest on
  sign-in is the follow-up that closes the gap.


## Architectural Rules

- Prefer simple, explicit flows
- Avoid hidden automation: the AI suggests, the app and the person decide
- No storage of request content, ever
- When unsure (refusal, odd answer, outage), fail quietly so the app falls back to on-device AI
  or rules
- Every limit is a cost guard, never a nudge
