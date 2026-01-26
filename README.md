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

