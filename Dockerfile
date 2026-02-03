FROM python:3.12-slim

WORKDIR /app

# Install system deps if needed
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definitions first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend ./backend

# ---- ENTRYPOINT SETUP (THIS IS THE PART YOU ADD) ----
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
# ----------------------------------------------------

# Optional: default CMD (Fly overrides this with process commands)
CMD ["python", "-m", "backend.app.main"]

