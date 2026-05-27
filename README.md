# lutz-finger-rag-mcp

Public MCP server that exposes Lutz Finger's RAG (Forbes column, LinkedIn
writing, keynote notes) over streamable HTTP.

Endpoints:
- `GET /` and `/health` — health JSON with chunk count.
- `POST /mcp` — MCP streamable HTTP transport.

Tools exposed:
- `search_writing(query, k)`
- `search_speaking(query, k)`
- `search_all(query, k)`
- `answer(question, max_passages)`

## Run locally

```bash
cd mcp-server
pip install -r requirements.txt
./scripts/export-rag.sh        # snapshots ~/Lutz_Media/rag-index/chroma into data/chroma
python server.py
# MCP at http://localhost:8080/mcp
```

## Deploy

The intended host is **Render Free Web Service** (no CC required, sleeps after
~15 min idle, wakes on first request). The repo includes `render.yaml` so the
deploy is fully declarative.

```bash
./scripts/export-rag.sh        # always run before deploy so the latest RAG ships
git add data/chroma && git commit -m "Snapshot RAG: $(date +%Y-%m-%d)"
git push                       # Render auto-deploys via render.yaml
```

After first deploy, point the lutzfinger.com `/qa` chat widget at
`https://<service-name>.onrender.com/mcp`.

### Alternative hosts (if Render fills up)

- **Hugging Face Spaces** (Docker SDK, no CC). See CUTOVER.md.
- **Fly.io** — requires CC on sign-up.
- **Cloudflare Workers** — requires CC for Vectorize.

## Adding the chat widget to lutzfinger.com

1. Set `PUBLIC_MCP_URL` in the Astro repo's GitHub Actions secrets.
2. The `/qa` page already has a script slot ready (`src/pages/qa/index.astro`)
   — extend it to hit the MCP endpoint via fetch+SSE on user input.

The MCP endpoint can also be used by Claude Desktop and other MCP clients
directly; just register the URL.
