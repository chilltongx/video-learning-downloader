import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "extract-podcast-transcript.py"
SPEC = importlib.util.spec_from_file_location("podcast_transcript", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PodcastTranscriptTests(unittest.TestCase):
    def test_json3_deduplicates_rolling_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "captions.json3"
            path.write_text(
                json.dumps(
                    {
                        "events": [
                            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "你好"}]},
                            {"tStartMs": 900, "dDurationMs": 1000, "segs": [{"utf8": "你好世界"}]},
                            {"tStartMs": 2200, "dDurationMs": 1000, "segs": [{"utf8": "下一句。"}]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            cues = MODULE.parse_json3(path)
        self.assertEqual([cue.text for cue in cues], ["你好世界", "下一句。"])

    def test_organize_writes_chaptered_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw" / "source-001"
            raw.mkdir(parents=True)
            info = {
                "id": "abc123",
                "title": "测试播客",
                "webpage_url": "https://example.com/watch?v=abc123",
                "uploader": "示例节目",
                "upload_date": "20260801",
                "duration": 620,
                "chapters": [
                    {"start_time": 0, "title": "开场"},
                    {"start_time": 300, "title": "核心讨论"},
                ],
            }
            (raw / "abc123.info.json").write_text(
                json.dumps(info, ensure_ascii=False), encoding="utf-8"
            )
            (raw / "abc123.zh-Hans.json3").write_text(
                json.dumps(
                    {
                        "events": [
                            {"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "欢迎收听。"}]},
                            {"tStartMs": 301000, "dDurationMs": 1000, "segs": [{"utf8": "进入核心讨论。"}]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            records, errors = MODULE.organize_downloaded_subtitles([raw], root, "zh")

            transcript = (root / "transcript.md").read_text(encoding="utf-8")
            captions = root / records[0].captions_file

        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        self.assertIn("## [00:00:00] 开场", transcript)
        self.assertIn("## [00:05:00] 核心讨论", transcript)
        self.assertTrue(captions.name == "captions.jsonl")


if __name__ == "__main__":
    unittest.main()
