#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
    echo "用法:"
    echo "  run-batch.sh prepare --input 来源.xlsx --task-dir 任务目录 [--sheet 工作表] [--start 1] [--limit 50] [--mcp-url URL]"
    echo "  run-batch.sh finalize --task-dir 任务目录 --analysis-dir Codex分析目录 --output 最终.xlsx"
    echo ""
    echo "prepare 只运行采集、下载、OCR和模型批次生成；然后暂停，交给Codex分析。"
    echo "finalize 校验Codex结果、生成并核验Excel、输出无字幕待转录篇数。"
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] || [ -z "${1:-}" ]; then
    usage
    exit 0
fi

COMMAND="$1"
shift
INPUT=""
TASK_DIR=""
SHEET=""
LIMIT="50"
START="1"
ANALYSIS_DIR=""
OUTPUT=""
MCP_URLS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --input) INPUT="${2:?}"; shift 2 ;;
        --task-dir) TASK_DIR="${2:?}"; shift 2 ;;
        --sheet) SHEET="${2:?}"; shift 2 ;;
        --limit) LIMIT="${2:?}"; shift 2 ;;
        --start) START="${2:?}"; shift 2 ;;
        --analysis-dir) ANALYSIS_DIR="${2:?}"; shift 2 ;;
        --output) OUTPUT="${2:?}"; shift 2 ;;
        --mcp-url) MCP_URLS+=("${2:?}"); shift 2 ;;
        *) echo "未知参数: $1" >&2; usage; exit 1 ;;
    esac
done

if [ -z "$TASK_DIR" ]; then
    echo "错误: 必须指定 --task-dir" >&2
    exit 1
fi
TASK_DIR="$(mkdir -p "$TASK_DIR" && cd "$TASK_DIR" && pwd)"

case "$COMMAND" in
    prepare)
        if [ -z "$INPUT" ]; then
            echo "错误: prepare 必须指定 --input" >&2
            exit 1
        fi
        mkdir -p "$TASK_DIR/raw" "$TASK_DIR/media" "$TASK_DIR/model_batches"
        XLSX_ARGS=(export-source --input "$INPUT" --start "$START" --limit "$LIMIT" --output "$TASK_DIR/source.json")
        [ -n "$SHEET" ] && XLSX_ARGS+=(--sheet "$SHEET")
        "$SCRIPT_DIR/run-xlsx.sh" "${XLSX_ARGS[@]}"

        COLLECT_ARGS=(collect --source "$TASK_DIR/source.json" --raw-dir "$TASK_DIR/raw" --status "$TASK_DIR/collection.json" --workers 4 --timeout 60)
        for url in "${MCP_URLS[@]}"; do COLLECT_ARGS+=(--mcp-url "$url"); done
        python3 "$SCRIPT_DIR/xhs_batch.py" "${COLLECT_ARGS[@]}"
        python3 "$SCRIPT_DIR/xhs_batch.py" normalize --source "$TASK_DIR/source.json" --raw-dir "$TASK_DIR/raw" --output "$TASK_DIR/normalized.json"
        python3 "$SCRIPT_DIR/xhs_batch.py" download-images --context "$TASK_DIR/normalized.json" --media-dir "$TASK_DIR/media" --output "$TASK_DIR/downloaded.json" --workers 4
        python3 "$SCRIPT_DIR/xhs_batch.py" ocr-images --context "$TASK_DIR/downloaded.json" --ocr-output "$TASK_DIR/ocr.json" --output "$TASK_DIR/context.json" --workers 4
        python3 "$SCRIPT_DIR/xhs_batch.py" model-batches --context "$TASK_DIR/context.json" --output-dir "$TASK_DIR/model_batches" --batch-size 13 --max-comments 10
        echo "本地准备完成。下一步由Codex读取 $TASK_DIR/model_batches 并输出分析JSON。"
        ;;
    finalize)
        if [ -z "$ANALYSIS_DIR" ] || [ -z "$OUTPUT" ]; then
            echo "错误: finalize 必须指定 --analysis-dir 和 --output" >&2
            exit 1
        fi
        mkdir -p "$TASK_DIR/previews"
        EXPECTED="$(jq 'length' "$TASK_DIR/source.json")"
        python3 "$SCRIPT_DIR/xhs_batch.py" validate-analysis --context "$TASK_DIR/context.json" --analysis-dir "$ANALYSIS_DIR" --output "$TASK_DIR/analysis.json"
        "$SCRIPT_DIR/run-xlsx.sh" build-report --context "$TASK_DIR/context.json" --analysis "$TASK_DIR/analysis.json" --output "$OUTPUT"
        "$SCRIPT_DIR/run-xlsx.sh" verify-report --input "$OUTPUT" --expected "$EXPECTED" --output "$TASK_DIR/verification.json" --preview-dir "$TASK_DIR/previews"
        python3 "$SCRIPT_DIR/xhs_batch.py" transcription-report --context "$TASK_DIR/context.json" --output "$TASK_DIR/transcription.json"
        echo "Excel已完成并核验。读取 $TASK_DIR/transcription.json 后，再询问用户是否转录。"
        ;;
    *)
        echo "未知阶段: $COMMAND" >&2
        usage
        exit 1
        ;;
esac
