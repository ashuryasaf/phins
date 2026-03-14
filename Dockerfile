# Dockerfile for PHINS Web Portal
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Railway uses dynamic PORT - don't hardcode
# EXPOSE is informational only, actual port comes from $PORT env var

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Health check - Railway will use /api/health
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT', '8000') + '/api/health')" || exit 1

# Run the server (reads PORT from environment)
CMD ["python3", "web_portal/server.py"]
