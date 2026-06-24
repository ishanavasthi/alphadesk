"""RAG retriever — queries the ChromaDB vector store; consumed by the Analyst agent.

STUB: returns an empty list until the ChromaDB ingest pipeline (see rag/ingest.py)
is wired up. The Analyst agent already calls ``retrieve`` so the contract is fixed.
"""

from __future__ import annotations

from typing import List


def retrieve(query: str, k: int = 4) -> List[str]:
    """Return up to ``k`` context passages relevant to ``query``.

    Args:
        query: Natural-language query (typically symbol + research summary).
        k: Maximum number of passages to return.

    Returns:
        A list of context strings. Currently empty (stub) — replace with a real
        ChromaDB similarity search once documents are ingested.
    """
    return []
