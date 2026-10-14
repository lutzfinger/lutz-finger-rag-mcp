#!/usr/bin/env bash
# Snapshot the local Lutz-author Chroma RAG into mcp-server/data/chroma so it
# can be baked into the Docker image at deploy time.
#
# Usage:  ./scripts/export-rag.sh [source]
#         default source: ~/Lutz_Media/rag-index/chroma
set -euo pipefail

SRC="${1:-$HOME/Lutz_Media/rag-index/chroma}"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/chroma"

if [[ ! -d "$SRC" ]]; then
  echo "Source not found: $SRC" >&2
  exit 1
fi

mkdir -p "$DEST"
rm -rf "$DEST"/*
echo "Copying $SRC → $DEST ..."
cp -R "$SRC"/* "$DEST/"
du -sh "$DEST"
echo "Done. Commit with: git add data/chroma && git commit -m 'Update RAG snapshot'"
