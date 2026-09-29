#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE_BIN="${CODEX_NODE_BIN:?请先设置 CODEX_NODE_BIN}"
NODE_MODULES="${CODEX_NODE_MODULES:?请先设置 CODEX_NODE_MODULES}"

if [ ! -x "$NODE_BIN" ] || [ ! -d "$NODE_MODULES/@oai/artifact-tool" ]; then
    echo "错误: Codex表格运行时不可用" >&2
    exit 1
fi

RUNTIME_DIR="$(mktemp -d)"
trap 'find "$RUNTIME_DIR" -depth -delete' EXIT
cp "$SCRIPT_DIR/xlsx_pipeline.mjs" "$RUNTIME_DIR/xlsx_pipeline.mjs"
ln -s "$NODE_MODULES" "$RUNTIME_DIR/node_modules"
"$NODE_BIN" "$RUNTIME_DIR/xlsx_pipeline.mjs" "$@"
