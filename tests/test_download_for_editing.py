import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download-for-editing.py"


class DownloadForEditingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.fake_video = self.output / "youtube" / "tester" / "2026-01-01_demo_abc.mp4"

        self.ytdlp = self.root / "yt-dlp"
        self.ytdlp.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                if "--dump-single-json" in args:
                    print('{"id":"abc","title":"demo","duration":3}')
                    raise SystemExit(0)
                marker = Path(args[args.index("--print-to-file") + 2])
                video = Path(os.environ["FAKE_VIDEO"])
                video.parent.mkdir(parents=True, exist_ok=True)
                video.write_bytes(b"fake-video")
                video.with_suffix(".jpg").write_bytes(b"fake-cover")
                marker.write_text(str(video) + "\\n", encoding="utf-8")
                print("fake download complete")
                """
            ),
            encoding="utf-8",
        )
        self.ytdlp.chmod(0o755)

        self.ffprobe = self.root / "ffprobe"
        self.ffprobe.write_text(
            "#!/usr/bin/env python3\n"
            "print('{\"format\":{\"duration\":\"3.0\",\"size\":\"10\"},"
            "\"streams\":[{\"codec_type\":\"video\",\"codec_name\":\"h264\","
            "\"width\":1920,\"height\":1080},{\"codec_type\":\"audio\","
            "\"codec_name\":\"aac\"}]}')\n",
            encoding="utf-8",
        )
        self.ffprobe.chmod(0o755)

        self.ffmpeg = self.root / "ffmpeg"
        self.ffmpeg.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.ffmpeg.chmod(0o755)

        self.env = os.environ.copy()
        self.env.update(
            {
                "VIDEO_DOWNLOADER_YTDLP": str(self.ytdlp),
                "VIDEO_DOWNLOADER_FFPROBE": str(self.ffprobe),
                "VIDEO_DOWNLOADER_FFMPEG": str(self.ffmpeg),
                "FAKE_VIDEO": str(self.fake_video),
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *extra):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "https://example.invalid/watch?v=abc&token=do-not-store",
                "--output-dir",
                str(self.output),
                "--no-system-proxy",
                *extra,
            ],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def test_download_emits_verified_paths_and_manifest(self):
        result = self.run_cli("--quality", "720p")
        self.assertEqual(result.returncode, 0, result.stderr)
        resolved_video = self.fake_video.resolve()
        self.assertIn(f"DOWNLOADED_FILE={resolved_video}", result.stdout)
        self.assertIn(f"THUMBNAIL_FILE={resolved_video.with_suffix('.jpg')}", result.stdout)
        result_line = next(line for line in result.stdout.splitlines() if line.startswith("RESULT_JSON="))
        manifest = json.loads(Path(result_line.split("=", 1)[1]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["options"]["quality"], "720")
        self.assertEqual(manifest["files"][0]["path"], str(resolved_video))
        self.assertEqual(manifest["source_url"], "https://example.invalid/watch?v=abc&token=REDACTED")
        self.assertNotIn("do-not-store", json.dumps(manifest))
        self.assertEqual(len(manifest["files"][0]["sha256"]), 64)

    def test_dry_run_does_not_create_video(self):
        result = self.run_cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY_RUN=1", result.stdout)
        self.assertFalse(self.fake_video.exists())


if __name__ == "__main__":
    unittest.main()
