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
                                    (no LLM call; returns top passages so
                                    the caller's model can compose)

Run:
  pip install -r requirements.txt
  python server.py
  # MCP at http://localhost:8080/mcp

The included `data/chroma/` directory must hold the same Chroma collection
(`lutz_author`) used locally. Use `scripts/export-rag.sh` to copy from
~/Lutz_Media/rag-index/chroma into ./data/chroma.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection
from mcp.server import Server
from mcp.server.streamable_http import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
import starlette.applications
import starlette.routing
import uvicorn

CHROMA_PATH = os.environ.get("CHROMA_PATH", "./data/chroma")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "lutz_author")
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
MAX_K = 12


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


def _hits_from_query(col: Collection, query: str, k: int, source_filter: list[str] | None = None) -> list[Hit]:
    k = max(1, min(MAX_K, k))
    where = None
    if source_filter:
        where = {"source": {"$in": source_filter}} if len(source_filter) > 1 else {"source": source_filter[0]}
    res = col.query(query_texts=[query], n_results=k, where=where)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    out: list[Hit] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        out.append(Hit(
            text=doc or "",
            title=meta.get("title") or "Untitled",
            url=meta.get("url") or "",
            date=meta.get("date") or "",
            source=meta.get("source") or "",
            score=1.0 - float(dist) if dist is not None else 0.0,
        ))
    return out


def _format_hits(hits: list[Hit]) -> str:
    """Plain-text representation that LLM clients render readably."""
    lines = []
    for i, h in enumerate(hits, 1):
        lines.append(f"### {i}. {h.title}")
        if h.url:
            lines.append(f"Source: {h.source or 'unknown'} — {h.url}")
        if h.date:
            lines.append(f"Date: {h.date}")
        lines.append("")
        lines.append(h.text[:800])
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip()


# ── MCP server setup ────────────────────────────────────────────────────────

app = Server("lutz-finger-rag")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_writing",
            description=(
                "Search Lutz Finger's writing (Forbes column + LinkedIn articles + LinkedIn posts). "
                "Returns top passages with title, source URL, date, and excerpt. "
                "Use this to find what Lutz has written about a topic."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for, in natural language."},
                    "k": {"type": "integer", "description": f"How many results (1-{MAX_K}). Default 5.", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_speaking",
            description=(
                "Search Lutz Finger's keynote and lecture content (transcripts, slides). "
                "Use this for what he has said on stage rather than written."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_all",
            description=(
                "Search across everything Lutz Finger has authored — writing, speaking, "
                "book excerpts, course material."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="answer",
            description=(
                "Retrieve the most relevant passages for a question. Returns structured "
                "JSON with the top passages and sources — designed for the caller's LLM "
                "to compose a final answer. Does NOT itself call an LLM."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "max_passages": {"type": "integer", "default": 4},
                },
                "required": ["question"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    col = _collection()
    if name == "search_writing":
        hits = _hits_from_query(col, arguments["query"], arguments.get("k", 5),
                                source_filter=["Forbes", "LinkedIn"])
        return [TextContent(type="text", text=_format_hits(hits))]
    if name == "search_speaking":
        hits = _hits_from_query(col, arguments["query"], arguments.get("k", 5),
                                source_filter=["Keynote", "Course", "course"])
        if not hits:
            hits = _hits_from_query(col, arguments["query"], arguments.get("k", 5))
        return [TextContent(type="text", text=_format_hits(hits))]
    if name == "search_all":
        hits = _hits_from_query(col, arguments["query"], arguments.get("k", 5))
        return [TextContent(type="text", text=_format_hits(hits))]
    if name == "answer":
        hits = _hits_from_query(col, arguments["question"], arguments.get("max_passages", 4))
        payload = {
            "question": arguments["question"],
            "passages": [h.to_dict() for h in hits],
            "note": (
                "These are the most relevant passages from Lutz Finger's authored "
                "content. Compose your answer grounded in these sources and cite each."
            ),
        }
        import json
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]
    raise ValueError(f"Unknown tool: {name}")


# ── Resource: lazy-loaded ChromaDB collection ───────────────────────────────

_client: PersistentClient | None = None
_collection_cache: Collection | None = None


def _collection() -> Collection:
    global _client, _collection_cache
    if _collection_cache is None:
        _client = PersistentClient(path=CHROMA_PATH)
        _collection_cache = _client.get_collection(COLLECTION_NAME)
    return _collection_cache


# ── HTTP transport with health probe ────────────────────────────────────────

session_manager = StreamableHTTPSessionManager(app=app, stateless=True)


@asynccontextmanager
async def lifespan(app: starlette.applications.Starlette) -> AsyncIterator[None]:
    async with session_manager.run():
        yield


async def health(request):
    from starlette.responses import JSONResponse
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


async def handle_mcp(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)


starlette_app = starlette.applications.Starlette(
    debug=False,
    routes=[
        starlette.routing.Route("/", health),
        starlette.routing.Route("/health", health),
        starlette.routing.Mount("/mcp", app=handle_mcp),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(starlette_app, host=HOST, port=PORT)
