FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definitions first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (owned by root, read-only for the app user)
COPY backend ./backend

COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# Run as an unprivileged user. entrypoint.sh may write the APNs key from
# APNS_AUTH_KEY_B64 to APNS_AUTH_KEY_PATH, so /app and /app/secrets are
# writable by this user (keep APNS_AUTH_KEY_PATH under /app/secrets).
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/secrets \
    && chown appuser:appuser /app /app/secrets
USER appuser

ENTRYPOINT ["/entrypoint.sh"]

# Default process is the API. Fly's [processes] and docker-compose's worker
# service override this with their own commands.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
