# WithYou Backend

Backend services for **With You**, a local-first support app designed to help ADHD brains get started, stay focused, and refocus without pressure or shame.

This service powers:
- Push notifications (APNs)
- User-scheduled reminders (a daily check-in at a time the user picks)
- Gentle, opt-in nudges
- Privacy-respecting event counts

The backend is intentionally lightweight, readable, and explainable — optimized for human-paced interactions rather than growth hacking. See [WITHYOU_BACKEND_PRINCIPLES.md](WITHYOU_BACKEND_PRINCIPLES.md) (the rules) and [ARCHITECTURE.md](ARCHITECTURE.md) (how it fits together).

---

## Core Principles

- **Local-first**: The app works fully offline. The backend enhances reliability and support, not control.
- **No accounts (v1)**: Identity is a generated install ID plus a per-install secret. No logins.
- **Privacy-respecting**: No task text, no content ingestion — only small counts and timestamps, kept for 35 days.
- **Gentle by design**: Quiet hours, a daily cap, one push per tick, and dedupe so nothing repeats.
- **Explainable nudges**: Every notification can be traced to a clear, user-understandable reason.
- **User-controlled deletion**: `DELETE /v1/installs/{install_id}` removes everything stored for an install.

---

## What This Backend Does

### Push notifications
- Token-based APNs integration (.p8), HTTP/2
- Per-device `apns_environment` (`sandbox` for Xcode builds, `production` for TestFlight / App Store)
- Deep links into the app
- Invalid tokens (`BadDeviceToken`, `Unregistered`, `DeviceTokenNotForTopic`) are deleted automatically

### Notifications the worker can send

Nothing is sent until the app has saved prefs with `PUT /v1/prefs/{install_id}`. Every send respects quiet hours and the daily cap.

| Type | When | Default |
| --- | --- | --- |
| `daily_checkin` — "Want to do a gentle check-in?" | Once per local day, at or after the chosen local time, within a 2 hour grace window | off |
| `capture_sort` — "Want a 60-second sort?" | Once per local day, after 8+ captures that day | on |
| `focus_first_step` — "Want help choosing a first step?" | Once per local day, 7–10 min into a focus session with no first step | **off (opt-in)** |

**Why focus nudges are opt-in:** the focus first-step nudge arrives *during* a focus session. That interrupts the session it is meant to support ("During a Focus Session: nothing else matters"), so it is only sent if the user turns it on.

**Grace window:** the check-in does not have to land in the exact minute. If a tick is late (deploy, restart, quiet hours ending), it still goes out within 2 hours of the chosen time. After that the day is skipped — no catch-up sends.

### Guardrails
- Quiet hours in the install's local time (default 22:00–08:00, may wrap midnight)
- `max_push_per_day` (default 2, max 5; 0 turns pushes off) counted per **local** day
- At most one push per install per tick
- Claim-first dedupe: a `push_log` record is inserted (unique per install + local day + type) *before* sending, so two workers can never both send the same notification. If APNs rejects the send, the record is removed and a later tick may retry silently. If the outcome is unknown (timeout after the request went out), it is not retried — a missed nudge is better than a duplicate.

---

## Tech Stack

- **Language**: Python 3.12
- **API**: FastAPI
- **Database**: MongoDB Atlas (via Motor — see follow-ups)
- **Scheduler**: APScheduler (separate worker process)
- **Push**: Apple Push Notification Service (APNs)
- **Containerization**: Docker, deployed on Fly.io

---

## Repository Structure

```text
withyou-backend/
├─ backend/
│  └─ app/
│     ├─ main.py              # FastAPI app: lifespan, API key check, /health, /ready
│     ├─ config.py            # Environment-driven settings
│     ├─ db.py                # Mongo client, collections, indexes (incl. TTL)
│     ├─ auth.py              # API key + per-install secret checks
│     ├─ models.py            # Pydantic request models and validation
│     ├─ worker.py            # Scheduler process
│     ├─ routes/
│     │  ├─ devices.py        # POST /v1/devices/register
│     │  ├─ prefs.py          # PUT /v1/prefs/{install_id}
│     │  ├─ events.py         # POST /v1/events
│     │  └─ installs.py       # DELETE /v1/installs/{install_id}
│     └─ services/
│        ├─ apns.py           # APNs HTTP/2 client + JWT auth
│        ├─ scheduler.py      # The worker tick: who gets which push now
│        ├─ rules.py          # Pure "is it due?" rules
│        ├─ dedupe.py         # Claim-first dedupe + daily cap counts
│        ├─ events.py         # Daily event rollup updates
│        ├─ notifications.py  # Notification copy + dedupe keys
│        ├─ defaults.py       # Default prefs and limits
│        └─ timeutils.py      # Quiet hours, local days, timezone fallback
├─ tests/                     # pytest suite (mongomock-motor, no real Mongo needed)
├─ secrets/                   # Mounted at runtime (NOT committed)
├─ docker-compose.yml
├─ Dockerfile
├─ fly.toml
├─ pyproject.toml             # ruff + pytest config
├─ requirements.txt           # pinned runtime deps
└─ requirements-dev.txt       # + pytest, pytest-asyncio, mongomock-motor, ruff
```

---

## Environment Variables

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `MONGO_URI` | yes | — | MongoDB connection string |
| `MONGO_DB` | no | `withyou` | Database name |
| `APNS_TEAM_ID` | for pushes | — | Apple team ID |
| `APNS_KEY_ID` | for pushes | — | ID of the .p8 key |
| `APNS_AUTH_KEY_PATH` | for pushes | — | Path to the .p8 key, e.g. `/app/secrets/AuthKey_XXXX.p8` |
| `APNS_AUTH_KEY_B64` | no | — | If set, `entrypoint.sh` decodes it into `APNS_AUTH_KEY_PATH` at start (used on Fly). The container runs as a non-root user that can only write under `/app`; if the path's folder isn't writable, the key is written to `/app/secrets/` instead (same file name) and the app is pointed there. A failed write never stops startup; pushes are skipped and logged. |
| `APNS_TOPIC` | for pushes | — | Bundle ID, e.g. `com.commongenelabs.WithYou` |
| `APNS_USE_SANDBOX` | no | `true` | Fallback host when a device has no `apns_environment` |
| `SCHEDULER_INTERVAL_SECONDS` | no | `60` | Worker tick interval; `/ready` fails if the last tick is older than 3× this |
| `API_KEY` | no | — | If set, every `/v1/*` request must send a matching `X-API-Key` |

If the APNs variables are missing, the worker logs what it *would* have sent instead of sending.

---

## API

### Authentication

| Header | Where | Behaviour |
| --- | --- | --- |
| `X-API-Key` | all `/v1/*` | Required only when `API_KEY` is set. Wrong or missing → `401`. Compared in constant time. |
| `X-Install-Secret` | `PUT /v1/prefs/{id}`, `POST /v1/events`, `DELETE /v1/installs/{id}` | Required. Missing → `401`, unknown install → `404`, wrong secret or install has no secret yet → `403`. |
| `X-Install-Secret` | `POST /v1/devices/register` | Optional. Wrong → `403`. Missing is accepted (older app builds) and logged. |

The install secret is a random URL-safe token returned **once**, by the first registration of an install. Only its SHA-256 hash is stored. The app must keep it (e.g. in the Keychain) and send it on later calls.

Invalid input is rejected with `422` (see each endpoint for the rules).

### `GET /health`
Liveness: `{"ok": true}` if the process is up. Does not touch Mongo. Used by Fly and docker-compose health checks.

### `GET /ready`
Readiness: `200 {"ok": true}` when Mongo answers a ping **and** the worker heartbeat (`worker_heartbeat.last_tick_at`) is at most 3 × `SCHEDULER_INTERVAL_SECONDS` old; otherwise `503 {"ok": false, "reason": "..."}`. Use it for external monitoring.

### `POST /v1/devices/register`

```json
{
  "install_id": "E621E1F8-C36C-495A-93FC-0C247A3E6E5F",
  "device_token": "<64-200 hex chars>",
  "timezone": "America/New_York",
  "push_enabled": true,
  "apns_environment": "production"
}
```

- `install_id`: 8–64 chars, `[A-Za-z0-9-]`
- `device_token`: hex, 64–200 chars
- `timezone`: a valid IANA zone name (default `America/New_York`)
- `apns_environment`: `"sandbox"`, `"production"` or omitted

Response: `{"ok": true, "install_has_secret": true}`, plus `"install_secret": "<token>"` only when a new secret was issued (the install had none). If an app holds no secret and gets none back while `install_has_secret` is true, the secret went to an earlier build that discarded it; the app starts over with a fresh `install_id` (the server never re-issues a secret).

### `PUT /v1/prefs/{install_id}` (needs `X-Install-Secret`)

```json
{
  "quiet_hours": {"start": "22:00", "end": "08:00"},
  "max_push_per_day": 2,
  "daily_checkin": {"enabled": true, "time": "09:00"},
  "focus_nudges": {"enabled": false},
  "capture_nudges": {"enabled": true},
  "refocus_nudges": {"enabled": false}
}
```

All fields are optional and default to the values shown. Times are `HH:MM` (00–23 : 00–59) in the install's local time. `max_push_per_day` is 0–5. Response: `{"ok": true}`.

### `POST /v1/events` (needs `X-Install-Secret`)

```json
{
  "install_id": "E621E1F8-C36C-495A-93FC-0C247A3E6E5F",
  "event_type": "capture_added",
  "ts": "2026-02-10T14:03:00Z",
  "meta": {"count": 1}
}
```

- `event_type`: `capture_added`, `refocus_opened`, `focus_session_started`, `focus_first_step_set`
- `ts`: ISO 8601; without an offset it is treated as UTC
- `meta.count` (capture_added): integer 1–100, default 1. `meta.has_first_step` (focus_session_started): boolean. Other `meta` keys are ignored and never stored.

Events are rolled up per install per **local** day (the install's timezone). Response: `{"ok": true}`.

### `DELETE /v1/installs/{install_id}` (needs `X-Install-Secret`)

Deletes the install and all of its devices, prefs, daily event rollups and push records. `404` if the install is unknown. Response: `{"ok": true}`.

---

## What Is Sent and Stored

Push payloads contain only fixed, gentle copy (title "With You", one of the lines in the table above) and a deep link. No user content is ever sent.

| Collection | Contents | Kept |
| --- | --- | --- |
| `installs` | install ID, timezone, push enabled, APNs environment, created / last seen times, SHA-256 hash of the install secret | until deleted |
| `devices` | APNs token, install ID, platform, APNs environment, created / updated times | until deleted, or until APNs reports the token invalid |
| `prefs` | the prefs above + updated time | until deleted |
| `events_daily` | per install per local day: capture count, refocus-open count, focus start time and whether a first step was set | **35 days** after the last update (TTL index on `updated_at`) |
| `push_log` | per sent notification: install ID, type, local date, sent time (used for dedupe and the daily cap) | **35 days** (TTL index on `sent_at`) |
| `worker_heartbeat` | time of the worker's last tick | single doc |

No task text, no productivity scores, no completion rates. Mongo's TTL monitor removes expired docs within about a minute of expiry.

---

## Running Locally

### 1) Configure

Create `.env` with at least `MONGO_URI` (and the APNs variables if you want real pushes). Place your Apple `.p8` key at:

```text
./secrets/AuthKey_XXXX.p8
```

The container runs as an unprivileged user (uid 10001), so the key file must be world-readable on the host (`chmod 644`).

### 2) Start services

```bash
docker compose up --build
```

This starts:

- API → `http://localhost:8000`
- Worker → background scheduler for pushes

### 3) Health and readiness

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

### 4) Register a device

```bash
curl -X POST http://localhost:8000/v1/devices/register \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "install_id": "dev-local-1",
    "device_token": "<APNS_TOKEN_FROM_XCODE>",
    "timezone": "America/New_York",
    "push_enabled": true,
    "apns_environment": "sandbox"
  }'
# -> {"ok": true, "install_has_secret": true, "install_secret": "..."}   (secret: first time only; keep it)
```

Then save prefs so the worker has something to do:

```bash
curl -X PUT http://localhost:8000/v1/prefs/dev-local-1 \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "X-Install-Secret: <INSTALL_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{"daily_checkin": {"enabled": true, "time": "09:00"}}'
```

---

## Tests and Lint

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests use `mongomock-motor`, so no MongoDB is needed. CI (`.github/workflows/fly-deploy.yml`) runs the same lint + tests on every pull request and push to `main`; a push to `main` deploys to Fly only after the tests pass.

---

## Notes / Follow-Ups

- **Migrate from Motor to PyMongo's async API.** Motor is deprecated in favour of `pymongo.AsyncMongoClient`. The change is mostly contained to `db.py`; not done yet on purpose.
- **Require `X-Install-Secret` on register** once every supported app build sends it. Until then a register call without the header is accepted (and logged).
- **Installs registered by older builds:** the secret was issued to a build that discarded it, and it is never issued again. After updating, such an app cannot authenticate for that install ID and should start over with a fresh install ID (then register). The old install doc is left without devices; consider a periodic cleanup of installs with no devices.
- Add push delivery metrics and structured logging.
- Add per-install rate limiting on the API.
- Done: `apns_environment` is persisted per device; `BadDeviceToken` / `Unregistered` tokens are cleaned up.

Checklist
---------

- [x] Push delivered to real device
- [x] Mongo writes verified
- [x] Secrets excluded from repo
- [x] API + worker dockerized (non-root)
- [x] Safe defaults when APNs is not configured
- [x] Tests + lint run in CI before deploy
- [x] Retention via TTL indexes; user-controlled deletion endpoint
