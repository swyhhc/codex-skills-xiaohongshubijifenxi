#!/bin/bash

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMP_HOME="$(mktemp -d)"
TEST_PORT=$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)

cleanup() {
    if [ -f "$TMP_HOME/.xiaohongshu/mcp.pid" ]; then
        kill "$(cat "$TMP_HOME/.xiaohongshu/mcp.pid")" 2>/dev/null || true
    fi
    rm -rf "$TMP_HOME"
}
trap cleanup EXIT

mkdir -p "$TMP_HOME/.local/bin"
cat > "$TMP_HOME/.local/bin/xiaohongshu-mcp" <<'PY'
#!/usr/bin/env python3
import socket
import sys
import time

address = sys.argv[sys.argv.index("-port") + 1]
host, port = address.rsplit(":", 1)
time.sleep(3)
with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, int(port)))
    server.listen()
    while True:
        connection, _ = server.accept()
        connection.close()
PY
chmod +x "$TMP_HOME/.local/bin/xiaohongshu-mcp"

HOME="$TMP_HOME" XHS_MCP_PORT="$TEST_PORT" "$SKILL_DIR/scripts/start-mcp.sh" >/dev/null

python3 - "$TEST_PORT" <<'PY'
import socket
import sys

with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1):
    pass
PY

echo "PASS: start-mcp waits for listening port"
