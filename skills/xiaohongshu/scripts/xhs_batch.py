#!/usr/bin/env python3
"""小红书批量分析中的确定性流水线；不调用大模型。"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse


REQUIRED_ANALYSIS_FIELDS = {
    "index",
    "comment_focus",
    "cover_ocr",
    "cover_strategy",
    "content_type",
    "commercial_judgment",
    "brand_product",
    "placement",
    "high_read_method",
    "evidence_gap",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_count(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    match = re.fullmatch(r"([0-9.]+)\s*万", text)
    if match:
        return int(float(match.group(1)) * 10000)
    try:
        return int(float(text))
    except ValueError:
        return None


def flatten_comments(value):
    rows = []
    for item in (value or {}).get("list", []):
        rows.append({"content": item.get("content", ""), "likes": parse_count(item.get("likeCount")) or 0})
        for child in item.get("subComments") or []:
            rows.append({"content": child.get("content", ""), "likes": parse_count(child.get("likeCount")) or 0})
    return sorted(rows, key=lambda row: row["likes"], reverse=True)


def unwrap_mcp_payload(payload):
    if "data" in payload:
        return payload
    try:
        text = payload["result"]["content"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("无法解析MCP返回结果") from exc


def find_official_subtitle(value):
    keys = {"subtitle", "subtitles", "caption", "captions", "transcript", "transcripts"}
    found = []

    def visit(node, parent_key=""):
        if isinstance(node, dict):
            for key, child in node.items():
                lower = str(key).lower()
                if lower in keys and child:
                    if isinstance(child, str):
                        found.append(child.strip())
                    elif isinstance(child, list):
                        parts = []
                        for item in child:
                            if isinstance(item, str):
                                parts.append(item)
                            elif isinstance(item, dict):
                                parts.append(str(item.get("text") or item.get("content") or ""))
                        if any(parts):
                            found.append("\n".join(x for x in parts if x))
                visit(child, lower)
        elif isinstance(node, list):
            for child in node:
                visit(child, parent_key)

    visit(value)
    return "\n".join(x for x in found if x).strip()


def pick_video_url(video):
    candidates = []
    stream = ((video or {}).get("media") or {}).get("stream") or {}
    for variants in stream.values():
        for item in variants or []:
            url = item.get("masterUrl") or next(iter(item.get("backupUrls") or []), "")
            if url:
                candidates.append((int(item.get("size") or 0), url))
    if not candidates:
        return ""
    positive = [item for item in candidates if item[0] > 0]
    return min(positive or candidates, key=lambda item: item[0])[1].replace("http://", "https://", 1)


def normalize_payload(source, payload):
    data = unwrap_mcp_payload(payload).get("data") or {}
    note = data.get("note") or {}
    if not note:
        return {
            "source": source,
            "status": "采集失败",
            "note": None,
            "comments": [],
            "images": [],
            "official_subtitle": "",
            "transcription_status": "未采集到视频信息",
        }
    interact = note.get("interactInfo") or {}
    note_type = "视频" if note.get("type") == "video" else "图文"
    subtitle = find_official_subtitle(note) if note_type == "视频" else ""
    images = []
    for page, image in enumerate(note.get("imageList") or [], start=1):
        url = image.get("urlDefault") or image.get("urlPre") or ""
        if url:
            images.append({"page": page, "url": url.replace("http://", "https://", 1)})
    if note_type == "图文":
        transcription_status = "不适用（图文）"
    elif subtitle:
        transcription_status = "已提取官方字幕"
    else:
        transcription_status = "无官方字幕，未转录"
    return {
        "source": source,
        "status": "采集成功",
        "note": {
            "note_id": note.get("noteId", ""),
            "title": note.get("title", ""),
            "body": note.get("desc", ""),
            "format": note_type,
            "published_at": note.get("time"),
            "author": (note.get("user") or {}).get("nickname", ""),
            "likes": parse_count(interact.get("likedCount")),
            "saves": parse_count(interact.get("collectedCount")),
            "comment_count": parse_count(interact.get("commentCount")),
            "duration": (((note.get("video") or {}).get("capa") or {}).get("duration")),
            "video_url": pick_video_url(note.get("video") or {}),
        },
        "comments": flatten_comments(data.get("comments")),
        "images": images,
        "official_subtitle": subtitle,
        "transcription_status": transcription_status,
    }


def parse_feed_args(source):
    url = str(source.get("笔记链接") or source.get("link") or "")
    parsed = urlparse(url)
    match = re.search(r"/(?:discovery/item|explore)/([^/?]+)", parsed.path)
    token = parse_qs(parsed.query).get("xsec_token", [""])[0]
    if not match or not token:
        raise ValueError("链接缺少feed_id或xsec_token")
    return match.group(1), token


def collect_one(source, raw_dir, mcp_call, mcp_url, timeout):
    index = int(source.get("序号") or source.get("index"))
    target = Path(raw_dir) / f"note_{index:03d}.json"
    try:
        feed_id, token = parse_feed_args(source)
        args = json.dumps({
            "feed_id": feed_id,
            "xsec_token": token,
            "load_all_comments": False,
            "limit": 10,
            "click_more_replies": False,
        }, ensure_ascii=False)
        env = os.environ.copy()
        env["MCP_URL"] = mcp_url
        env["MCP_CALL_TIMEOUT"] = str(timeout)
        completed = subprocess.run(
            [str(mcp_call), "get_feed_detail", args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout + 5,
            check=False,
        )
        if completed.returncode == 28:
            return {"index": index, "status": f"采集超时（{timeout}秒跳过）", "error": "timeout"}
        if completed.returncode != 0 or not completed.stdout.strip():
            error = completed.stderr.strip() or completed.stdout.strip() or "空结果"
            return {"index": index, "status": "采集失败", "error": error}
        payload = json.loads(completed.stdout)
        write_json(target, payload)
        return {"index": index, "status": "采集成功", "file": str(target)}
    except subprocess.TimeoutExpired:
        return {"index": index, "status": f"采集超时（{timeout}秒跳过）", "error": "timeout"}
    except Exception as exc:
        return {"index": index, "status": "采集失败", "error": str(exc)}


def collect_batch(sources, raw_dir, mcp_call, mcp_urls, workers=4, timeout=60):
    Path(raw_dir).mkdir(parents=True, exist_ok=True)
    urls = list(mcp_urls) or ["http://localhost:18060/mcp"]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for position, source in enumerate(sources):
            futures.append(pool.submit(
                collect_one,
                source,
                raw_dir,
                mcp_call,
                urls[position % len(urls)],
                timeout,
            ))
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item["index"])


def normalize_batch(sources, raw_dir):
    rows = []
    for source in sources:
        index = int(source.get("序号") or source.get("index"))
        path = Path(raw_dir) / f"note_{index:03d}.json"
        if not path.exists() or path.stat().st_size == 0:
            rows.append({
                "source": source,
                "status": "采集超时或失败（未重试）",
                "note": None,
                "comments": [],
                "images": [],
                "official_subtitle": "",
                "transcription_status": "无法判断",
            })
            continue
        try:
            rows.append(normalize_payload(source, read_json(path)))
        except Exception as exc:
            rows.append({
                "source": source,
                "status": "采集结果解析失败",
                "note": None,
                "comments": [],
                "images": [],
                "official_subtitle": "",
                "transcription_status": "无法判断",
                "error": str(exc),
            })
    return rows


def download_one(item):
    target = Path(item["local_path"])
    if target.exists() and target.stat().st_size > 0:
        return {**item, "download": "ok", "bytes": target.stat().st_size}
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        item["url"].replace("http://", "https://", 1),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            target.write_bytes(response.read())
        return {**item, "download": "ok", "bytes": target.stat().st_size}
    except Exception as exc:
        return {**item, "download": f"failed:{type(exc).__name__}", "bytes": 0}


def download_images(rows, media_dir, workers=4):
    jobs = []
    for row in rows:
        index = int(row["source"].get("序号") or row["source"].get("index"))
        for image in row.get("images") or []:
            jobs.append({
                "index": index,
                "page": image["page"],
                "url": image["url"],
                "local_path": str(Path(media_dir) / f"note_{index:03d}" / f"page_{int(image['page']):02d}.webp"),
            })
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(download_one, jobs))
    by_key = {(item["index"], item["page"]): item for item in results}
    for row in rows:
        index = int(row["source"].get("序号") or row["source"].get("index"))
        row["images"] = [by_key[(index, image["page"])] for image in row.get("images") or []]
    return results


def attach_ocr(rows, ocr_rows):
    mapped = {}
    for item in ocr_rows:
        match = re.search(r"note_(\d+)/page_(\d+)\.[^/]+$", str(item.get("path", "")))
        if match:
            mapped[(int(match.group(1)), int(match.group(2)))] = item.get("text", "")
    for row in rows:
        index = int(row["source"].get("序号") or row["source"].get("index"))
        for image in row.get("images") or []:
            image["ocr"] = mapped.get((index, int(image.get("page") or 0)), "")
    return rows


def run_ocr(rows, output, workers=4):
    swift_source = Path(__file__).with_name("vision_ocr.swift")
    cache_dir = Path(output).resolve().parent / ".xhs-tools"
    binary = cache_dir / "vision_ocr"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if not binary.exists() or swift_source.stat().st_mtime > binary.stat().st_mtime:
        completed = subprocess.run(["swiftc", str(swift_source), "-o", str(binary)], capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "OCR编译失败")
    paths = [
        image["local_path"]
        for row in rows
        for image in row.get("images") or []
        if image.get("download") == "ok" and image.get("local_path")
    ]
    chunks = [paths[offset::workers] for offset in range(workers) if paths[offset::workers]]

    def run_chunk(chunk):
        completed = subprocess.run([str(binary), *chunk], capture_output=True, text=True, check=False)
        parsed = []
        for line in completed.stdout.splitlines():
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return parsed

    ocr_rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(run_chunk, chunks):
            ocr_rows.extend(result)
    write_json(output, ocr_rows)
    return attach_ocr(rows, ocr_rows), ocr_rows


def make_model_batches(rows, batch_size=12, max_comments=10):
    compact = []
    for row in rows:
        source = row.get("source") or {}
        note = row.get("note") or {}
        compact.append({
            "index": int(source.get("序号") or source.get("index")),
            "source": {
                "trend": source.get("趋势词", ""),
                "source_title": source.get("笔记标题", ""),
                "source_format": source.get("笔记类型", ""),
                "source_views": source.get("阅读量"),
                "source_engagement": source.get("互动量"),
                "link": source.get("笔记链接") or source.get("link") or "",
            },
            "collection_status": row.get("status", ""),
            "title": note.get("title", ""),
            "body": note.get("body", ""),
            "format": note.get("format", ""),
            "author": note.get("author", ""),
            "likes": note.get("likes"),
            "saves": note.get("saves"),
            "comment_count": note.get("comment_count"),
            "duration": note.get("duration"),
            "official_subtitle": row.get("official_subtitle", ""),
            "transcription_status": row.get("transcription_status", ""),
            "comments": (row.get("comments") or [])[:max_comments],
            "images": [
                {"page": image.get("page"), "ocr": image.get("ocr", ""), "local_path": image.get("local_path", "")}
                for image in row.get("images") or []
            ],
        })
    return [compact[start:start + batch_size] for start in range(0, len(compact), batch_size)]


def validate_analysis(context, analysis):
    expected = [int(row["source"].get("序号") or row["source"].get("index")) for row in context]
    actual = [int(row.get("index")) for row in analysis]
    duplicates = sorted({index for index in actual if actual.count(index) > 1})
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if duplicates:
        raise ValueError(f"分析行重复: {duplicates}")
    if missing:
        raise ValueError(f"缺少分析行: {missing}")
    if extra:
        raise ValueError(f"存在多余分析行: {extra}")
    for row in analysis:
        absent = REQUIRED_ANALYSIS_FIELDS - set(row)
        if absent:
            raise ValueError(f"第{row.get('index')}行缺少字段: {sorted(absent)}")
    return sorted(analysis, key=lambda row: int(row["index"]))


def cleanup_media(media_dir, report_verified, execute=False):
    path = Path(media_dir).resolve()
    result = {"media_dir": str(path), "would_delete_files": 0, "deleted_files": 0, "bytes": 0}
    if path.name not in {"media", "xhs_media", "xhs-media"}:
        raise ValueError(f"拒绝清理非媒体目录: {path}")
    if not report_verified or not path.exists() or not path.is_dir():
        return result
    files = [item for item in path.rglob("*") if item.is_file()]
    result["would_delete_files"] = len(files)
    result["bytes"] = sum(item.stat().st_size for item in files)
    if execute:
        for item in files:
            item.unlink()
        for directory in sorted((item for item in path.rglob("*") if item.is_dir()), reverse=True):
            directory.rmdir()
        path.rmdir()
        result["deleted_files"] = len(files)
    return result


def command_collect(args):
    sources = read_json(args.source)
    results = collect_batch(sources, args.raw_dir, args.mcp_call, args.mcp_url, args.workers, args.timeout)
    write_json(args.status, results)
    print(json.dumps({
        "total": len(results),
        "success": sum(item["status"] == "采集成功" for item in results),
        "failed": sum(item["status"] != "采集成功" for item in results),
        "workers": args.workers,
        "timeout": args.timeout,
    }, ensure_ascii=False))


def command_normalize(args):
    rows = normalize_batch(read_json(args.source), args.raw_dir)
    write_json(args.output, rows)
    print(json.dumps({"rows": len(rows), "success": sum(row["status"] == "采集成功" for row in rows)}, ensure_ascii=False))


def command_download_images(args):
    rows = read_json(args.context)
    results = download_images(rows, args.media_dir, args.workers)
    write_json(args.output, rows)
    print(json.dumps({
        "images": len(results),
        "downloaded": sum(item["download"] == "ok" for item in results),
        "failed": sum(item["download"] != "ok" for item in results),
        "bytes": sum(item["bytes"] for item in results),
    }, ensure_ascii=False))


def command_model_batches(args):
    batches = make_model_batches(read_json(args.context), args.batch_size, args.max_comments)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, batch in enumerate(batches, start=1):
        write_json(output_dir / f"batch_{index:02d}.json", batch)
    print(json.dumps({"batches": len(batches), "rows": sum(map(len, batches))}, ensure_ascii=False))


def command_ocr(args):
    rows = read_json(args.context)
    rows, ocr_rows = run_ocr(rows, args.ocr_output, args.workers)
    write_json(args.output, rows)
    print(json.dumps({
        "images": len(ocr_rows),
        "recognized": sum(bool(item.get("text")) for item in ocr_rows),
        "errors": sum(bool(item.get("error")) for item in ocr_rows),
    }, ensure_ascii=False))


def command_attach_ocr(args):
    rows = read_json(args.context)
    text = Path(args.ocr_input).read_text(encoding="utf-8").strip()
    if not text:
        ocr_rows = []
    elif text.startswith("["):
        ocr_rows = json.loads(text)
    else:
        ocr_rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    write_json(args.output, attach_ocr(rows, ocr_rows))
    print(json.dumps({"rows": len(rows), "ocr_records": len(ocr_rows)}, ensure_ascii=False))


def command_validate_analysis(args):
    context = read_json(args.context)
    analysis = []
    for path in sorted(Path(args.analysis_dir).glob("*.json")):
        value = read_json(path)
        analysis.extend(value if isinstance(value, list) else [value])
    validated = validate_analysis(context, analysis)
    write_json(args.output, validated)
    print(json.dumps({"rows": len(validated), "status": "ok"}, ensure_ascii=False))


def command_transcription_report(args):
    rows = read_json(args.context)
    pending = []
    for row in rows:
        note = row.get("note") or {}
        if note.get("format") == "视频" and row.get("transcription_status") == "无官方字幕，未转录":
            pending.append({
                "index": int(row["source"].get("序号") or row["source"].get("index")),
                "title": note.get("title") or row["source"].get("笔记标题", ""),
                "duration_seconds": note.get("duration"),
                "link": row["source"].get("笔记链接") or row["source"].get("link") or "",
            })
    write_json(args.output, {"count": len(pending), "items": pending})
    print(json.dumps({"pending_transcription": len(pending)}, ensure_ascii=False))


def command_cleanup(args):
    verification = read_json(args.verification)
    verified = verification.get("failed", 1) == 0 or verification.get("verified") is True
    result = cleanup_media(args.media_dir, verified, args.execute)
    print(json.dumps(result, ensure_ascii=False))


def build_parser():
    parser = argparse.ArgumentParser(description="小红书批量分析确定性流水线（不调用大模型）")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="4路并发采集；每篇60秒；不重试")
    collect.add_argument("--source", required=True)
    collect.add_argument("--raw-dir", required=True)
    collect.add_argument("--status", required=True)
    collect.add_argument("--mcp-call", default=str(Path(__file__).with_name("mcp-call.sh")))
    collect.add_argument("--mcp-url", action="append", default=[])
    collect.add_argument("--workers", type=int, default=4)
    collect.add_argument("--timeout", type=int, default=60)
    collect.set_defaults(func=command_collect)

    normalize = sub.add_parser("normalize")
    normalize.add_argument("--source", required=True)
    normalize.add_argument("--raw-dir", required=True)
    normalize.add_argument("--output", required=True)
    normalize.set_defaults(func=command_normalize)

    download = sub.add_parser("download-images")
    download.add_argument("--context", required=True)
    download.add_argument("--media-dir", required=True)
    download.add_argument("--output", required=True)
    download.add_argument("--workers", type=int, default=4)
    download.set_defaults(func=command_download_images)

    batches = sub.add_parser("model-batches")
    batches.add_argument("--context", required=True)
    batches.add_argument("--output-dir", required=True)
    batches.add_argument("--batch-size", type=int, default=12)
    batches.add_argument("--max-comments", type=int, default=10)
    batches.set_defaults(func=command_model_batches)

    ocr = sub.add_parser("ocr-images")
    ocr.add_argument("--context", required=True)
    ocr.add_argument("--ocr-output", required=True)
    ocr.add_argument("--output", required=True)
    ocr.add_argument("--workers", type=int, default=4)
    ocr.set_defaults(func=command_ocr)

    attach = sub.add_parser("attach-ocr")
    attach.add_argument("--context", required=True)
    attach.add_argument("--ocr-input", required=True)
    attach.add_argument("--output", required=True)
    attach.set_defaults(func=command_attach_ocr)

    validate = sub.add_parser("validate-analysis")
    validate.add_argument("--context", required=True)
    validate.add_argument("--analysis-dir", required=True)
    validate.add_argument("--output", required=True)
    validate.set_defaults(func=command_validate_analysis)

    report = sub.add_parser("transcription-report")
    report.add_argument("--context", required=True)
    report.add_argument("--output", required=True)
    report.set_defaults(func=command_transcription_report)

    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("--media-dir", required=True)
    cleanup.add_argument("--verification", required=True)
    cleanup.add_argument("--execute", action="store_true")
    cleanup.set_defaults(func=command_cleanup)
    return parser


def main():
    args = build_parser().parse_args()
    if hasattr(args, "workers") and not 1 <= args.workers <= 4:
        raise SystemExit("workers必须在1到4之间")
    if hasattr(args, "timeout") and args.timeout != 60:
        raise SystemExit("采集超时固定为60秒")
    args.func(args)


if __name__ == "__main__":
    main()
