#!/bin/bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/run-batch.sh"
bash -n "$SCRIPT"
HELP="$("$SCRIPT" --help)"
grep -q "prepare" <<< "$HELP"
grep -q "finalize" <<< "$HELP"
grep -q "Codex" <<< "$HELP"
echo "PASS: 两阶段批量入口"
