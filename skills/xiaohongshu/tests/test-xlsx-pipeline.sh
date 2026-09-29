#!/bin/bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'find "$TMP_DIR" -depth -delete' EXIT

cat > "$TMP_DIR/context.json" <<'JSON'
[
  {
    "source": {"序号": 1, "趋势词": "测试", "笔记标题": "原始标题", "阅读量": 100, "互动量": 20, "笔记链接": "https://www.xiaohongshu.com/explore/test"},
    "status": "采集成功",
    "note": {"title": "测试标题", "author": "作者", "format": "图文", "likes": 10, "saves": 5, "comment_count": 2, "body": "正文"},
    "images": [{"page": 1, "ocr": "封面字"}],
    "transcription_status": "不适用（图文）"
  }
]
JSON

cat > "$TMP_DIR/analysis.json" <<'JSON'
[
  {
    "index": 1,
    "comment_focus": "评论重点",
    "cover_ocr": "封面字",
    "cover_strategy": "策略",
    "content_type": "教程攻略",
    "commercial_judgment": "非商业",
    "brand_product": "",
    "placement": "无商业植入",
    "high_read_method": "方法",
    "evidence_gap": "无"
  }
]
JSON

CODEX_NODE_BIN="${CODEX_NODE_BIN:?}" CODEX_NODE_MODULES="${CODEX_NODE_MODULES:?}" \
  "$SKILL_DIR/scripts/run-xlsx.sh" build-report \
  --context "$TMP_DIR/context.json" --analysis "$TMP_DIR/analysis.json" --output "$TMP_DIR/report.xlsx"

CODEX_NODE_BIN="$CODEX_NODE_BIN" CODEX_NODE_MODULES="$CODEX_NODE_MODULES" \
  "$SKILL_DIR/scripts/run-xlsx.sh" verify-report \
  --input "$TMP_DIR/report.xlsx" --expected 1 --output "$TMP_DIR/verification.json" --preview-dir "$TMP_DIR/previews"

test -s "$TMP_DIR/report.xlsx"
test "$(jq -r '.failed' "$TMP_DIR/verification.json")" = "0"
echo "PASS: XLSX 构建与核验"
