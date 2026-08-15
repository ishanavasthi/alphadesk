# AlphaDesk backend — Hugging Face Spaces (Docker SDK).
# HF routes traffic to port 7860. Container runs the FastAPI app from backend/.
FROM python:3.11-slim

# HF runs the container as a non-root user (uid 1000). Give it a home/writable app dir.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    HF_HOME=/app/.cache

WORKDIR /app

# System deps for chromadb / onnxruntime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code + RAG corpus (data/nse_docs -> data/chroma_db at project root).
COPY backend/ ./backend/
COPY data/ ./data/

# Bake the ChromaDB index into the image (downloads the ONNX embed model once,
# at build time). Harmless no-op if data/nse_docs is empty.
RUN cd backend && python -m rag.ingest || true

# Writable dirs for the non-root HF user (token cache + chroma + model cache).
RUN mkdir -p /app/.cache && chmod -R 777 /app

EXPOSE 7860

# --app-dir backend so `api.main:app`, `graph.*`, `tools.*` import as in dev.
CMD ["sh", "-c", "uvicorn api.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-7860}"]
