# WithYou Backend — Architecture Overview

This backend supports the WithYou frontend with minimal pressure
and minimal inference.

Primary responsibilities:
- persistence of a few settings and counts
- notification delivery
- one periodic background job

It does not:
- decide priorities
- infer motivation
- optimize productivity


## Components

```text
 iOS app ──HTTPS──▶ API (FastAPI, uvicorn) ──▶ MongoDB Atlas ◀── Worker (APScheduler) ──HTTP/2──▶ APNs ──▶ device
```

- **API process** (`backend/app/main.py`, Fly process `app`): stateless FastAPI app.
  Registers installs/devices, stores prefs, rolls up events, deletes an install on request.
  Exposes `/health` (liveness) and `/ready` (Mongo ping + worker heartbeat freshness).
- **Worker process** (`backend/app/worker.py`, Fly process `worker`): an APScheduler
  `AsyncIOScheduler` that runs `services.scheduler.tick()` every
  `SCHEDULER_INTERVAL_SECONDS` (default 60). It is the only component that sends pushes.
- **MongoDB** (Atlas, via Motor): the only shared state between the two processes.
  There is no message broker or queue.
- **APNs**: token-based (.p8 JWT) HTTP/2 client in `services/apns.py`, one shared
  connection per process, closed on shutdown.


## Data model (MongoDB)

| Collection | `_id` | Purpose |
| --- | --- | --- |
| `installs` | install ID | timezone, `push_enabled`, APNs environment, `secret_hash` |
| `devices` | APNs token | `install_id`, APNs environment, `updated_at` |
| `prefs` | install ID | quiet hours, daily cap, daily check-in, nudge toggles |
| `events_daily` | `install_id\|YYYY-MM-DD` (local day) | small counters/timestamps for that day |
| `push_log` | `install_id\|YYYY-MM-DD\|type` (local day) | dedupe claim + daily cap record |
| `worker_heartbeat` | `"scheduler"` | `last_tick_at` |

Indexes (created at API startup): `installs(push_enabled, _id)`, `devices(install_id)`,
`push_log(install_id, date)`, `events_daily(install_id)`, and TTL indexes
`push_log.sent_at` and `events_daily.updated_at` (35 days).

"Day" always means the install's **local** calendar date, derived from its timezone,
for event rollups, the daily cap and dedupe keys. Quiet hours are local too.


## Request flow (API)

1. Middleware checks `X-API-Key` (constant-time) for `/v1/*` when `API_KEY` is set.
2. Pydantic validates the body/path (IDs, hex tokens, IANA timezones, `HH:MM`, ranges) → `422`.
3. Routes that change or delete an install's data check `X-Install-Secret` against the
   stored SHA-256 hash (`auth.authorize_install`). The first `register` issues the secret.
4. One or two small Mongo writes. No fan-out, no background work.


## Worker tick

Each tick:

1. Write the heartbeat (failure is logged, never fatal).
2. Page through `installs` with `push_enabled: true` (keyset pagination on `_id`, 200 per page).
3. For a page, load prefs with one `$in` query. Skip installs without prefs (nothing opted in)
   and installs inside their quiet hours. A bad stored timezone falls back to UTC (logged once).
4. For the remaining installs, load devices, today's `events_daily` docs and today's
   `push_log` counts with one `$in` query each. The most recently updated device is used.
5. Per install (errors are isolated per install): stop if the daily cap is reached; otherwise
   take the first due notification (daily check-in → focus first step (opt-in) → capture sort).
6. Send through **claim-first dedupe**: insert the `push_log` doc first (the unique `_id` is
   the lock), re-check the cap, then call APNs. On a definite failure the claim is deleted so a
   later tick can retry silently; on an ambiguous timeout it is kept; on an invalid token the
   device is deleted. At most one push per install per tick.

Because the claim is an atomic insert, running more than one worker cannot double-send.
A crash between claim and send loses that notification for the day rather than repeating it.


## Operations

- Fly health checks use `/health`, so a stalled worker does not restart the API.
  Point external monitoring at `/ready`.
- Containers run as a non-root user. CI runs `ruff check` and `pytest` (Python 3.12)
  on pull requests and pushes; deploys to Fly run only after tests pass on `main`.
- Retention is enforced by Mongo TTL indexes; full deletion by `DELETE /v1/installs/{id}`.


## Follow-ups

- **Motor → PyMongo async.** Motor is deprecated; PyMongo's `AsyncMongoClient` is the
  supported replacement. Collections are only accessed through `backend/app/db.py`
  (as `db.<collection>`), so the migration is contained. Intentionally not done yet.


## Architectural Rules

- Prefer simple, explicit flows
- Avoid hidden automation
- No autonomous escalation logic
- All timing decisions must be user-initiated or explicitly configured
- When delivery is uncertain, prefer a missed nudge over a repeated one
