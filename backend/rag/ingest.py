"""RAG ingestion — load NSE PDFs into ChromaDB.

Reads every PDF under ``data/nse_docs/``, splits the text with
``RecursiveCharacterTextSplitter`` (chunk_size=1000, overlap=100), embeds the
chunks with ChromaDB's default ONNX MiniLM model (all-MiniLM-L6-v2, no torch),
and upserts them into a persistent ChromaDB collection named ``nse_filings``.

Run as a script::

    cd backend && python -m rag.ingest

The first run downloads the small ONNX embedding model and persists vectors under
``data/chroma_db/``. Re-running is idempotent (deterministic chunk ids upsert).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, List, Tuple

import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

# Project layout: this file is backend/rag/ingest.py -> project root is parents[2].
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
NSE_DOCS_DIR = _PROJECT_ROOT / "data" / "nse_docs"
CHROMA_DIR = _PROJECT_ROOT / "data" / "chroma_db"

COLLECTION_NAME = "nse_filings"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100


def _symbol_from_filename(name: str) -> str:
    """Best-effort NSE symbol from a filename, e.g. 'RELIANCE_2024.pdf' -> 'RELIANCE'."""
    stem = Path(name).stem
    return stem.split("_")[0].split("-")[0].upper()


def _iter_pdf_pages(docs_dir: Path) -> Iterator[Tuple[str, int, str]]:
    """Yield (filename, page_number, text) for every readable PDF page."""
    for pdf_path in sorted(docs_dir.glob("*.pdf")):
        try:
            reader = PdfReader(str(pdf_path))
        except Exception as exc:  # noqa: BLE001 - skip unreadable files, keep going
            print(f"  ! skipping {pdf_path.name}: {exc}")
            continue
        for page_num, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                yield pdf_path.name, page_num, text


def _get_collection(persist_dir: Path):
    client = chromadb.PersistentClient(path=str(persist_dir))
    ef = embedding_functions.ONNXMiniLM_L6_V2()  # chromadb default, no torch
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def ingest(docs_dir: Path = NSE_DOCS_DIR, persist_dir: Path = CHROMA_DIR) -> int:
    """Ingest all PDFs in ``docs_dir`` into the ``nse_filings`` collection.

    Returns the number of chunks upserted.
    """
    if not docs_dir.exists():
        print(f"No docs directory at {docs_dir}; nothing to ingest.")
        return 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    collection = _get_collection(persist_dir)

    ids: List[str] = []
    documents: List[str] = []
    metadatas: List[dict] = []

    for filename, page_num, text in _iter_pdf_pages(docs_dir):
        symbol = _symbol_from_filename(filename)
        for chunk_idx, chunk in enumerate(splitter.split_text(text)):
            ids.append(f"{symbol}:{filename}:p{page_num}:c{chunk_idx}")
            documents.append(chunk)
            metadatas.append({"source": filename, "symbol": symbol, "page": page_num})

    if not documents:
        print(f"No extractable text found in PDFs under {docs_dir}.")
        return 0

    # Upsert in batches to keep memory bounded on large filing sets.
    batch = 256
    for start in range(0, len(documents), batch):
        end = start + batch
        collection.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )

    print(f"Ingested {len(documents)} chunks into '{COLLECTION_NAME}' at {persist_dir}.")
    return len(documents)


def main() -> None:
    ingest()


if __name__ == "__main__":
    main()
