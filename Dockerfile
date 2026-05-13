# PHINS Web Portal — multi-stage Docker build
# -----------------------------------------------------------------------------
# Stage 1 (builder): build wheels from requirements.txt with pip in a throwaway
#                    image. This keeps the pip cache and any transient build
#                    tooling out of the final image.
# Stage 2 (runtime): minimal python:3.12-slim with only the OCR/PDF system
#                    libraries and the pre-built wheels installed.
#
# All entry points (serve / cron / db-init) are dispatched through
# scripts/entrypoint.sh so the start command lives in ONE place.
# -----------------------------------------------------------------------------

# =====================
# Stage 1 — wheel builder
# =====================
FROM python:3.12-slim AS builder

WORKDIR /build

# We compile a few sdists (psycopg2-binary, cryptography, Pillow, etc.). Most
# arrive as manylinux wheels, but having gcc available avoids slow surprises.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Resolve runtime deps into wheels in /wheels. Using --wheel-dir keeps the
# final image free of pip's HTTP cache and the build-essential toolchain.
RUN pip wheel \
        --no-cache-dir \
        --wheel-dir=/wheels \
        -r requirements.txt


# =====================
# Stage 2 — runtime
# =====================
FROM python:3.12-slim AS runtime

# System dependencies (kept identical to legacy single-stage Dockerfile):
#   curl              - healthcheck
#   tesseract-ocr     - OCR engine (Assessment Center)
#   tesseract-ocr-eng - English language pack
#   tesseract-ocr-heb - Hebrew language pack
#   tesseract-ocr-ara - Arabic language pack
#   poppler-utils     - PDF rasterisation backing pdf2image
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-heb \
        tesseract-ocr-ara \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install runtime deps from the pre-built wheels only (no network, no pip
# cache, no compiler in the final layer).
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install \
        --no-cache-dir \
        --no-index \
        --find-links=/wheels \
        -r requirements.txt \
    && rm -rf /wheels

# Copy the application source.
# .dockerignore aggressively excludes tests, docs, demos, backups, *.pdf,
# .venv, .env, etc. so this COPY ships only what runs in production.
COPY . .

# Ensure the entrypoint dispatcher is executable even if the host bit was lost.
RUN chmod +x scripts/entrypoint.sh

# Persistent-volume mount point used by Railway for the ledger. Without a
# volume the directory still exists so the app does not fall back to /tmp.
RUN mkdir -p /data && chmod 777 /data

# Railway / Render inject PORT at runtime. EXPOSE is informational only.
ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PYTHONDONTWRITEBYTECODE=1

STOPSIGNAL SIGTERM

# Curl-based healthcheck (cheaper than spawning a python interpreter).
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/api/health" || exit 1

ENTRYPOINT ["./scripts/entrypoint.sh"]
CMD ["serve"]
