FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CHROMA_PATH=/app/data/chroma \
    COLLECTION_NAME=lutz_author \
    PORT=8080

WORKDIR /app

# System deps for chromadb (sqlite, build tooling)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libsqlite3-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY server.py .
COPY data/ ./data/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
  CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["python", "server.py"]
