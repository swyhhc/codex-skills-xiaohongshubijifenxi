#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "xhs_batch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("xhs_batch", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BatchPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_normalize_marks_video_without_subtitle_and_keeps_top_comments(self):
        payload = {
            "data": {
                "note": {
                    "noteId": "abc",
                    "title": "测试视频",
                    "desc": "正文",
                    "type": "video",
                    "user": {"nickname": "作者"},
                    "interactInfo": {
                        "likedCount": "1.2万",
                        "collectedCount": "300",
                        "commentCount": "2",
                    },
                    "video": {
                        "capa": {"duration": 61},
                        "media": {"stream": {"H264": [{"masterUrl": "https://example.test/a.mp4", "size": 10}]}},
                    },
                    "imageList": [{"urlDefault": "https://example.test/cover.webp"}],
                },
                "comments": {
                    "list": [
                        {"content": "低赞", "likeCount": "1"},
                        {"content": "高赞", "likeCount": "20"},
                    ]
                },
            }
        }
        row = self.module.normalize_payload({"序号": 1, "笔记链接": "https://example.test"}, payload)
        self.assertEqual(row["note"]["likes"], 12000)
        self.assertEqual(row["comments"][0]["content"], "高赞")
        self.assertEqual(row["transcription_status"], "无官方字幕，未转录")
        self.assertEqual(row["note"]["video_url"], "https://example.test/a.mp4")

    def test_model_batches_preserve_order_and_limit_payload(self):
        rows = [
            {
                "source": {"序号": i, "笔记链接": f"https://x/{i}"},
                "status": "采集成功",
                "note": {"title": f"标题{i}", "body": "正文", "format": "图文"},
                "comments": [{"content": "评论", "likes": 1}],
                "images": [{"page": 1, "ocr": "封面"}],
                "transcription_status": "不适用（图文）",
            }
            for i in range(1, 6)
        ]
        batches = self.module.make_model_batches(rows, batch_size=2, max_comments=1)
        self.assertEqual([[x["index"] for x in batch] for batch in batches], [[1, 2], [3, 4], [5]])
        self.assertNotIn("video_url", json.dumps(batches, ensure_ascii=False))

    def test_validate_analysis_rejects_missing_rows(self):
        context = [{"source": {"序号": 1}}, {"source": {"序号": 2}}]
        analysis = [{"index": 1}]
        with self.assertRaisesRegex(ValueError, "缺少分析行"):
            self.module.validate_analysis(context, analysis)

    def test_attach_ocr_maps_text_by_note_and_page(self):
        rows = [{"source": {"序号": 7}, "images": [{"page": 1}, {"page": 2}]}]
        ocr_rows = [
            {"path": "/tmp/note_007/page_02.webp", "text": "第二页", "error": None},
            {"path": "/tmp/note_007/page_01.webp", "text": "封面", "error": None},
        ]
        mapped = self.module.attach_ocr(rows, ocr_rows)
        self.assertEqual([image["ocr"] for image in mapped[0]["images"]], ["封面", "第二页"])

    def test_cleanup_requires_verified_report_and_execute_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "media"
            media.mkdir()
            target = media / "a.webp"
            target.write_bytes(b"123")
            result = self.module.cleanup_media(media, report_verified=False, execute=True)
            self.assertEqual(result["deleted_files"], 0)
            self.assertTrue(target.exists())
            result = self.module.cleanup_media(media, report_verified=True, execute=False)
            self.assertEqual(result["would_delete_files"], 1)
            self.assertTrue(target.exists())
            result = self.module.cleanup_media(media, report_verified=True, execute=True)
            self.assertEqual(result["deleted_files"], 1)
            self.assertFalse(target.exists())

    def test_cleanup_rejects_non_media_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "reports"
            target.mkdir()
            (target / "final.xlsx").write_bytes(b"123")
            with self.assertRaisesRegex(ValueError, "拒绝清理"):
                self.module.cleanup_media(target, report_verified=True, execute=True)

    def test_collect_one_marks_curl_exit_28_as_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mock = root / "mcp-call.sh"
            mock.write_text("#!/bin/sh\nexit 28\n", encoding="utf-8")
            mock.chmod(0o755)
            source = {
                "序号": 51,
                "笔记链接": "https://www.xiaohongshu.com/explore/abc?xsec_token=token",
            }
            result = self.module.collect_one(source, root / "raw", mock, "http://localhost:1/mcp", 60)
            self.assertEqual(result["status"], "采集超时（60秒跳过）")

    def test_collect_one_rejects_mcp_error_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mock = root / "mcp-call.sh"
            payload = {"result": {"content": [{"type": "text", "text": "工具执行时发生内部错误"}], "isError": True}}
            mock.write_text(
                "#!/bin/sh\nprintf '%s' '" + json.dumps(payload, ensure_ascii=False) + "'\n",
                encoding="utf-8",
            )
            mock.chmod(0o755)
            source = {
                "序号": 55,
                "笔记链接": "https://www.xiaohongshu.com/explore/abc?xsec_token=token",
            }
            result = self.module.collect_one(source, root / "raw", mock, "http://localhost:1/mcp", 60)
            self.assertEqual(result["status"], "采集失败")
            self.assertIn("内部错误", result["error"])


if __name__ == "__main__":
    unittest.main()
