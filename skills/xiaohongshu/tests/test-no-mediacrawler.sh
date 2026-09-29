#!/bin/bash

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if grep -qi "MediaCrawler" "$SKILL_DIR/SKILL.md"; then
    echo "FAIL: SKILL.md 仍包含 MediaCrawler"
    exit 1
fi

if [ -e "$SKILL_DIR/scripts/media-crawler.sh" ]; then
    echo "FAIL: MediaCrawler 调用脚本仍存在"
    exit 1
fi

echo "PASS: xiaohongshu skill 不再调用 MediaCrawler"
