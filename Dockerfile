# Dockerfile for PHINS Web Portal
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# System dependencies:
#   curl              - lightweight health checks
#   tesseract-ocr     - OCR engine for scanned ID cards / photographed receipts
#   tesseract-ocr-eng - English language pack
#   tesseract-ocr-heb - Hebrew language pack (Israeli IDs, medical reports)
#   tesseract-ocr-ara - Arabic language pack
#   poppler-utils     - PDF rasterisation backing pdf2image (scanned PDF OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-heb \
        tesseract-ocr-ara \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create /data directory for Railway persistent volume mount.
# When a Railway volume is attached at /data, ledger data survives restarts.
# Without a volume, this dir still exists so the app uses /data/ (in container
# layer) rather than /tmp, preventing accidental ephemeral-path warnings during
# short-lived deploys.  Real persistence requires a Railway volume at /data.
RUN mkdir -p /data && chmod 777 /data

# Railway uses dynamic PORT - don't hardcode
# EXPOSE is informational only, actual port comes from $PORT env var

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Stale-PID prevention: ensure clean signal delivery to python process
STOPSIGNAL SIGTERM

# Health check - uses curl for lower memory overhead than python interpreter spawn
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Run the server (reads PORT from environment)
CMD ["python3", "web_portal/server.py"]
