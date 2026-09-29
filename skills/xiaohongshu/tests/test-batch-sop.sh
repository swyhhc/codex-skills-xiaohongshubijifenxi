#!/bin/bash
set -euo pipefail

SKILL_FILE="$(cd "$(dirname "$0")/.." && pwd)/SKILL.md"

grep -q "最多4路并发" "$SKILL_FILE"
grep -q "60秒" "$SKILL_FILE"
grep -q "不重试" "$SKILL_FILE"
grep -q "Excel.*完成.*再询问" "$SKILL_FILE"
grep -q "机械步骤.*不调用.*模型" "$SKILL_FILE"
echo "PASS: 批量SOP已固定"
