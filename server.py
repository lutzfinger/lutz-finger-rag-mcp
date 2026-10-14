"""
Lutz Finger RAG — public MCP endpoint.

Exposes the Lutz-author RAG (Forbes column + LinkedIn writing + keynote notes,
embedded in ChromaDB) as an MCP server over streamable HTTP. Designed for
hosting on Render / Hugging Face Spaces / Fly free tiers.

Tools:
- search_writing(query, k)        — articles + blog posts only
- search_speaking(query, k)       — keynote/transcript content only
- search_all(query, k)            — everything
- answer(question, max_passages)  — retrieval + structured answer payload

Run:
  pip install -r requirements.txt
  python server.py
  # MCP at http://localhost:8080/mcp
  # Health at http://localhost:8080/health
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
import uvicorn

CHROMA_PATH = os.environ.get("CHROMA_PATH", "./data/chroma")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "lutz_author")
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
MAX_K = 12

mcp = FastMCP("lutz-finger-rag", stateless_http=True)


@dataclass
class Hit:
    text: str
    title: str
    url: str
    date: str
    source: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "date": self.date,
            "source": self.source,
            "score": round(self.score, 3),
            "excerpt": self.text[:800],
        }


_client: PersistentClient | None = None
_collection_cache: Collection | None = None


def _collection() -> Collection:
    global _client, _collection_cache
    if _collection_cache is None:
        _client = PersistentClient(path=CHROMA_PATH)
        _collection_cache = _client.get_collection(COLLECTION_NAME)
    return _collection_cache


def _query(query: str, k: int, source_filter: list[str] | None = None) -> list[Hit]:
    k = max(1, min(MAX_K, k))
    where = None
    if source_filter:
        where = {"source": {"$in": source_filter}} if len(source_filter) > 1 else {"source": source_filter[0]}
    res = _collection().query(query_texts=[query], n_results=k, where=where)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    hits: list[Hit] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        hits.append(Hit(
            text=doc or "",
            title=meta.get("title") or "Untitled",
            url=meta.get("url") or "",
            date=meta.get("date") or "",
            source=meta.get("source") or "",
            score=1.0 - float(dist) if dist is not None else 0.0,
        ))
    return hits


def _format_hits(hits: list[Hit]) -> str:
    if not hits:
        return "_No matching passages found._"
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(f"### {i}. {h.title}")
        if h.url:
            parts.append(f"Source: {h.source or 'unknown'} — {h.url}")
        if h.date:
            parts.append(f"Date: {h.date}")
        parts.append("")
        parts.append(h.text[:800])
        parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts).rstrip()


# ── Tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def search_writing(query: str, k: int = 5) -> str:
    """Search Lutz Finger's writing (Forbes column, LinkedIn articles, LinkedIn posts).
    Returns top passages with title, source URL, date, and excerpt."""
    return _format_hits(_query(query, k, source_filter=["Forbes", "LinkedIn"]))


@mcp.tool()
def search_speaking(query: str, k: int = 5) -> str:
    """Search Lutz Finger's keynote and course content (transcripts, slides)."""
    hits = _query(query, k, source_filter=["Keynote", "Course", "course"])
    if not hits:
        hits = _query(query, k)
    return _format_hits(hits)


@mcp.tool()
def search_all(query: str, k: int = 5) -> str:
    """Search across everything Lutz Finger has authored — writing, speaking,
    book excerpts, course material."""
    return _format_hits(_query(query, k))


@mcp.tool()
def answer(question: str, max_passages: int = 4) -> str:
    """Retrieve the most relevant passages for a question. Returns structured JSON
    with the top passages and sources — designed for the caller's LLM to compose
    a final answer with citations."""
    hits = _query(question, max_passages)
    payload = {
        "question": question,
        "passages": [h.to_dict() for h in hits],
        "note": "Passages from Lutz Finger's authored content. Compose grounded in these and cite each.",
    }
    return json.dumps(payload, indent=2)


# ── HTTP app ────────────────────────────────────────────────────────────────

async def health(request):
    try:
        c = _collection().count()
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)
    return JSONResponse({
        "status": "ok",
        "collection": COLLECTION_NAME,
        "chunks": c,
        "service": "lutz-finger-rag-mcp",
    })


def build_app() -> Starlette:
    # FastMCP's streamable_http_app already mounts /mcp and owns its own
    # lifespan. We extend it with health endpoints rather than wrapping it,
    # so the lifespan context (session manager startup/shutdown) stays intact.
    mcp_app = mcp.streamable_http_app()
    mcp_app.routes.insert(0, Route("/", health))
    mcp_app.routes.insert(1, Route("/health", health))
    return mcp_app


if __name__ == "__main__":
    uvicorn.run(build_app(), host=HOST, port=PORT)
