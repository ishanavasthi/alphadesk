# AlphaDesk backend — Hugging Face Spaces (Docker SDK).
# HF routes traffic to port 7860. Container runs the FastAPI app from backend/.
FROM python:3.11-slim

# HF runs the container as a non-root user (uid 1000). Give it a home/writable app dir.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    HF_HOME=/app/.cache

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code only. RAG is unplugged in v2, so the image carries no corpus and no
# vector store: chromadb is not installed and rag/retriever.py returns an empty
# context. To re-enable RAG: put chromadb/pypdf/langchain-text-splitters back in
# requirements.txt, restore `COPY data/ ./data/` and a
# `RUN cd backend && python -m rag.ingest || true` step here, and add PDFs to
# data/nse_docs. (Re-adds build-essential + the onnxruntime download.)
#
# `.dockerignore` keeps backend/.env and the IND Money token cache out of the
# build context — without it a local build would bake TOKEN_ENCRYPTION_KEY and
# GROQ_API_KEY into a layer.
COPY backend/ ./backend/

# Build-time gate (F1). graph/portfolio_config.py suppresses LangSmith tracing
# for the portfolio graph by leaning on a langchain-core internal, and
# langchain-core arrives here transitively — so prove the kill switch against
# the versions THIS image resolved. A bad resolution fails the build instead of
# shipping a portfolio graph that quietly traces someone's holdings.
RUN cd backend \
 && LANGCHAIN_TRACING_V2=true LANGCHAIN_API_KEY=dummy \
    python -m tests.check_tracing_in_image

# Writable dirs for the non-root HF user (token cache + model cache).
RUN mkdir -p /app/.cache && chmod -R 777 /app

EXPOSE 7860

# --app-dir backend so `api.main:app`, `graph.*`, `tools.*` import as in dev.
CMD ["sh", "-c", "uvicorn api.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-7860}"]
