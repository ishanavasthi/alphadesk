"""RAG retriever — semantic search over the ``nse_filings`` ChromaDB collection.

Consumed by the Analyst agent. Degrades gracefully: if ChromaDB is unavailable or
the collection has not been ingested yet (see rag/ingest.py), the functions return
an empty list so the Analyst keeps working without RAG context.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

# Mirror ingest.py settings so the retriever reads the same store/model.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_DIR = _PROJECT_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "nse_filings"

_collection = None  # cached ChromaDB collection handle
_init_failed = False


def _get_collection():
    """Lazily open the persistent collection; cache it, tolerate any failure."""
    global _collection, _init_failed
    if _collection is not None:
        return _collection
    if _init_failed:
        return None
    try:
        import chromadb
        from chromadb.utils import embedding_functions

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        ef = embedding_functions.ONNXMiniLM_L6_V2()  # chromadb default, no torch
        _collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
        return _collection
    except Exception:  # noqa: BLE001 - not installed / not ingested yet
        _init_failed = True
        return None


def get_relevant_context(symbol: str, query: str, k: int = 3) -> List[str]:
    """Return the top ``k`` filing chunks relevant to ``symbol`` + ``query``.

    Args:
        symbol: NSE ticker the research concerns (biases the semantic query).
        query: Research question / summary text.
        k: Number of chunks to return (default 3).

    Returns:
        A list of chunk strings (empty if no store/results).
    """
    collection = _get_collection()
    if collection is None:
        return []
    text = f"{symbol} {query}".strip()
    try:
        result = collection.query(query_texts=[text], n_results=k)
    except Exception:  # noqa: BLE001 - empty collection / query failure
        return []
    documents = result.get("documents") or [[]]
    return documents[0] if documents else []


def retrieve(query: str, k: int = 4) -> List[str]:
    """Backward-compatible symbol-less retrieval; delegates to get_relevant_context."""
    return get_relevant_context("", query, k=k)
