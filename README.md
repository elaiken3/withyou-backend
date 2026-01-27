# withyou-backend

Backend services for **With You**, a local-first support app designed to help ADHD brains get started, stay focused, and refocus without pressure or shame.

This service powers:
- Push notifications (APNs)
- User-scheduled reminders
- Gentle, opt-in behavioral nudges
- Privacy-respecting event aggregation

The backend is intentionally lightweight, readable, and explainable — optimized for human-paced interactions rather than growth hacking.

---

## Core Principles

- **Local-first**: The app works fully offline. The backend enhances reliability and support, not control.
- **No accounts (v1)**: Identity is device-based using a generated install ID. No logins required.
- **Privacy-respecting**: No task text, no content ingestion — only minimal counts and timestamps.
- **Gentle by design**: Built-in caps, quiet hours, and deduplication to avoid notification fatigue.
- **Explainable nudges**: Every notification can be traced to a clear, user-understandable reason.

---

## What This Backend Does

### ✅ Push Notifications
- Token-based APNs integration (.p8)
- TestFlight / production support
- Deep linking into the app

### ✅ Scheduled Reminders
- Daily check-ins (user-defined time)
- Reliable delivery even if the app is closed or the device restarts

### ✅ Behavioral Nudges (Opt-In)
- Focus session follow-ups (e.g., first-step support)
- Capture inbox hygiene prompts
- Refocus support reminders

### ✅ Guardrails
- Quiet hours
- Maximum notifications per day
- Dedupe keys to prevent repeats

---

## Tech Stack

- **Language**: Python 3.12
- **API**: FastAPI
- **Database**: MongoDB Atlas (via Motor)
- **Scheduler**: APScheduler
- **Push**: Apple Push Notification Service (APNs)
- **Containerization**: Docker

---

## Repository Structure

```text
withyou-backend/
├─ backend/
│  └─ app/
│     ├─ main.py              # FastAPI app entrypoint
│     ├─ config.py            # Environment-driven settings
│     ├─ db.py                # Mongo connections / collections
│     ├─ models.py            # Pydantic request models
│     ├─ worker.py            # Scheduler process
│     ├─ routes/
│     │  ├─ devices.py        # Device registration
│     │  ├─ prefs.py          # User preferences
│     │  └─ events.py         # Lightweight event ingestion
│     └─ services/
│        ├─ apns.py           # APNs HTTP/2 client + JWT auth
│        └─ scheduler.py      # Push scheduling logic
├─ secrets/                   # Mounted at runtime (NOT committed)
│  └─ AuthKey_XXXX.p8
├─ docker-compose.yml
├─ Dockerfile
├─ requirements.txt
└─ README.md
```
Environment Variables
---------------------

### MongoDB

-   `MONGO_URI`
-   `MONGO_DB=withyou`

### APNs

-   `APNS_TEAM_ID`
-   `APNS_KEY_ID`
-   `APNS_AUTH_KEY_PATH=/app/secrets/AuthKey_XXXX.p8`
-   `APNS_TOPIC=com.commongenelabs.WithYou`
-   `APNS_USE_SANDBOX=true`

### Scheduler
-   `SCHEDULER_INTERVAL_SECONDS=60`
  
Running Locally
---------------

### 1) Add APNs key

Place your Apple `.p8` key at:

```text
./secrets/AuthKey_XXXX.p8
```

### 2) Start services

```bash
docker compose up --build
```

This starts:

-   API → `http://localhost:8000`
-   Worker → background scheduler for pushes

### 3) Health check

```bash
curl http://localhost:8000/health
```

Register a Device
-----------------

```bash
curl -X POST http://localhost:8000/v1/devices/register\
  -H "Content-Type: application/json"\
  -d '{
    "install_id": "dev-local-1",
    "device_token": "<APNS_TOKEN_FROM_XCODE>",
    "timezone": "America/New_York",
    "push_enabled": true
  }'
```

Verify Mongo
------------

Confirm the following documents exist:

-   `installs` collection contains:
    -   `_id = install_id`
-   `devices` collection contains:
    -   `_id = device_token`
> Note: `device_token` is used as the `_id`, so it should be easy to spot.

Confirm Push Delivery
---------------------

-   Scheduler sends a push notification
-   Notification is received on a physical device (TestFlight build)

Notes / Follow-Ups
------------------

-   Persist `apns_environment` per device (sandbox vs production)
-   Handle `BadDeviceToken` responses and clean up invalid tokens
-   Add push delivery metrics and structured logging
-   Add per-install rate limiting enforcement

Checklist
---------

- [x] Push delivered to real device
- [x] Mongo writes verified
- [x] Secrets excluded from repo
- [x] API + worker dockerized
- [x] Safe defaults when APNs is not configured
