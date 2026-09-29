#!/bin/bash

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'find "$TMP_DIR" -depth -delete' EXIT

cat > "$TMP_DIR/curl" <<'EOF'
#!/bin/bash
printf '%s\n' "$@" >> "$MOCK_CURL_LOG"
for arg in "$@"; do
    if [ "$arg" = "-i" ]; then
        printf 'HTTP/1.1 200 OK\r\nMcp-Session-Id: test-session\r\n\r\n{}'
        exit 0
    fi
done
printf '{}'
EOF
chmod +x "$TMP_DIR/curl"

export MOCK_CURL_LOG="$TMP_DIR/curl.log"
PATH="$TMP_DIR:$PATH" MCP_CALL_TIMEOUT=321 "$SKILL_DIR/scripts/mcp-call.sh" check_login_status '{}' >/dev/null

awk 'previous == "--max-time" && $0 == "321" { found=1 } { previous=$0 } END { exit(found ? 0 : 1) }' "$MOCK_CURL_LOG"
echo "PASS: MCP_CALL_TIMEOUT 可配置"
