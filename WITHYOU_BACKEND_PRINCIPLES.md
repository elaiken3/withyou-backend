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


## Notifications

Backend systems may schedule notifications, but must not:

- escalate frequency automatically
- repeat indefinitely without user input
- introduce urgency language
- create “missed count” or “failure” state

Forgiveness logic:
- a reminder may ask once if it is still relevant
- after that, it must stop unless explicitly rescheduled


## Retries & Background Jobs

Retries are allowed only for:
- delivery reliability
- data consistency

Retries must not:
- surface to the user as repeated nudges
- be used to “ensure compliance”

If a notification fails, it may retry silently.
It must not compensate by sending more.


## Scheduling Philosophy

Time-based logic must remain lightweight.

The backend should not:
- infer user productivity
- generate pressure-based timing
- auto-reschedule tasks without consent
- create backlog or debt states

The frontend owns meaning.
The backend owns delivery.


## Logging & Analytics

Allowed:
- error logging
- system health metrics
- coarse-grained usage counts for stability

Forbidden:
- productivity scoring
- task completion rates per user
- behavioral profiling
- insights framed around efficiency or output

If data could later be used to shame a user,
it should not be collected.


## Data Retention

Prefer:
- minimal storage
- user-controlled deletion
- short-lived derived data

Avoid:
- long-term behavioral histories
- inferred motivation or engagement labels


## AI / Automation Boundaries

Automation may assist with:
- parsing
- routing
- delivery

Automation must not:
- decide what a user “should” do
- optimize for speed over safety
- introduce hidden nudges


## Guidance for AI Assistants (Codex)

When working in this repo:

- Read this file before making changes
- Choose the least invasive solution
- Prefer explicit user intent over inference
- If unsure, stop rather than escalate

The backend should feel invisible.
