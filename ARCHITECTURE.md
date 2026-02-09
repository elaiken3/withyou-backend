# WithYou Backend — Architecture Overview

This backend supports the WithYou frontend with minimal pressure
and minimal inference.

Primary responsibilities:
- persistence
- notification delivery
- background processing

It does not:
- decide priorities
- infer motivation
- optimize productivity


## Components (example)

- API layer (FastAPI)
- Background workers (Celery or equivalent)
- Message broker / queue
- Notification delivery service
- Data store(s)


## Architectural Rules

- Prefer simple, explicit flows
- Avoid hidden automation
- No autonomous escalation logic
- All timing decisions must be user-initiated or explicitly configured
