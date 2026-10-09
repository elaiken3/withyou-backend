# WithYou Backend — Principles & Constraints

This document defines non-negotiable rules for backend development
for the WithYou app.

The backend exists to support emotional safety, not to enforce productivity.

If backend behavior introduces pressure, escalation, or judgment,
it violates the product.


## Core Rule

The backend must never create urgency or punishment on its own.

All backend logic must assume:
- users miss things for valid reasons
- absence is neutral
- reminders are invitations, not enforcement

Today the backend does one thing: optional cloud AI. It sends no notifications
and keeps no schedule. Reminders and check-ins live on the phone.


## Cloud AI

Cloud AI is off by default. It runs only after the person turns it on,
with a plain explanation of what is sent.

The AI may:
- turn what someone typed or said into clear items
- suggest smaller steps, one gentle next move, or one thing to start with
- tidy stray thoughts into items for later

The AI must not:
- act on the person's data by itself (it suggests; the app shows it; the person decides)
- decide what a user "should" do, or rank people's worth by output
- use guilt, urgency, streaks, "overdue", or exclamation marks
- moralize, diagnose, or give therapy-style advice

Prompts must:
- be warm, short, plain text, and ADHD-aware (small first steps, low friction)
- treat everything the person wrote as data, never as instructions
  (wrap it in clear delimiters and say so)
- prefer a missing suggestion over a wrong one: when an answer is odd,
  return an error so the app falls back to on-device AI or rules


## Limits

Daily limits exist to keep costs predictable and to stop abuse.

Limits must not:
- be framed as failure ("you've used up...") or as a reward
- carry over, accumulate, or create a "debt"
- push people to come back

When a limit is reached, the app quietly uses on-device AI or simple rules,
and cloud AI is back the next day.


## Retries & Failures

Retries are allowed only for:
- delivery reliability (one SDK retry for a dropped connection or overload)
- data consistency

Retries must not:
- surface to the user as repeated prompts
- be used to "ensure compliance"

When Claude declines or fails, the backend answers with an error and the
app falls back. It never retries with a reworded prompt to get around a refusal.


## Logging & Analytics

Allowed:
- error logging (fixed error codes, never messages that could quote input)
- system health metrics (status, latency)
- coarse-grained usage counts for limits and stability

Forbidden:
- logging request text, model output, access tokens, or user ids
- productivity scoring
- task completion rates per user
- behavioral profiling
- insights framed around efficiency or output

If data could later be used to shame a user,
it should not be collected.


## Data Retention

Prefer:
- minimal storage (today: per-day request counts only)
- user-controlled deletion (`delete_me` removes everything for that person)
- short-lived derived data (counts are deleted after 35 days)

Avoid:
- storing what people write, in any form
- long-term behavioral histories
- inferred motivation or engagement labels


## Guidance for AI Assistants (Claude, Codex)

When working in this repo:

- Read this file before making changes
- Choose the least invasive solution
- Prefer explicit user intent over inference
- Keep every test that guards privacy (logs, deletion, limits) passing
- If unsure, stop rather than escalate

The backend should feel invisible.
