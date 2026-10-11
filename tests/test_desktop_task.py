import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/desktop-task.py'

FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(args) + '\n')
if os.environ.get('HANG'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])
    Path(os.environ['CHILD_PID']).write_text(str(child.pid))
    time.sleep(90)
if '--write-thumbnail' in args:
    if os.environ.get('FAIL_COVER'): print('ERROR: thumbnail HTTP Error 502'); sys.exit(1)
    Path(args[args.index('-o') + 1].replace('%(ext)s', 'jpg')).write_bytes(b'jpeg')
elif '--write-info-json' in args:
    base = Path(args[args.index('-o') + 1]).parent / 'abc'
    base.with_suffix('.info.json').write_text(json.dumps({'id':'abc','title':'中文课程','duration':5,'webpage_url':'https://example.invalid/v?token=secret'}))
    if not os.environ.get('NO_SUBS'):
        base.with_suffix('.zh.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n第一段课程内容。\n\n00:00:03.000 --> 00:00:05.000\n第二段内容。\n', encoding='utf-8')
else:
    target = Path(os.environ['MEDIA']).with_suffix('.mp3' if '-x' in args else '.mp4')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'media')
    Path(args[args.index('--print-to-file') + 2]).write_text(str(target)+'\n')
    print('VD_TITLE:中文课程')
    print('VD_PROGRESS: 45.5%|1.2MiB/s|剩余 00:02')
'''

class DesktopTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / 'output'
        self.calls = self.root / 'calls'
        engine = self.root / 'yt-dlp'
        engine.write_text(FAKE)
        engine.chmod(0o755)
        probe = self.root / 'ffprobe'
        probe.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps({"streams":[{"codec_type":"audio" if sys.argv[-1].endswith("mp3") else "video", "height":720}]}))\n')
        probe.chmod(0o755)
        ffmpeg = self.root / 'ffmpeg'
        ffmpeg.write_text('#!/bin/sh\nexit 0\n')
        ffmpeg.chmod(0o755)
        self.env = dict(os.environ, VIDEO_DOWNLOADER_YTDLP=str(engine),
                        VIDEO_DOWNLOADER_FFMPEG=str(ffmpeg), VIDEO_DOWNLOADER_FFPROBE=str(probe),
                        CALLS=str(self.calls), MEDIA=str(self.output / '中文课程.mp4'), CHILD_PID=str(self.root / 'pid'))

    def tearDown(self): self.tmp.cleanup()

    def command(self, mode, *args):
        return [sys.executable, str(SCRIPT), '--mode', mode, '--output-dir', str(self.output),
                '--transcript-dir', str(self.output / 'transcripts'), '--no-system-proxy', *args, 'https://example.invalid/watch']

    def run_task(self, mode, *args):
        result = subprocess.run(self.command(mode, *args), capture_output=True, text=True, env=self.env, timeout=15)
        self.assertFalse(result.stderr, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        return result, events

    def test_audio_selects_audio_stream_and_emits_progress(self):
        result, events = self.run_task('audio', '--audio-quality', '128K')
        self.assertEqual(result.returncode, 0)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index('-f')+1], 'bestaudio/best')
        self.assertIn('128K', calls[0])
        self.assertNotIn('--write-thumbnail', calls[0])
        self.assertTrue(any(e.get('percent') == 45.5 for e in events))
        self.assertEqual(events[-1]['status'], 'complete')
        self.assertTrue(Path(next(e['paths'][0] for e in events if e['event']=='result')).exists())

    def test_video_cover_failure_keeps_playable_media(self):
        self.env['FAIL_COVER'] = '1'
        result, events = self.run_task('video', '--cover', '--quality', '720')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(events[-1]['status'], 'partial')
        results = [e for e in events if e['event']=='result']
        self.assertEqual([(e['kind'],e['status']) for e in results], [('视频','complete'),('封面','failed')])
        self.assertTrue(Path(results[0]['paths'][0]).exists())

    def test_transcript_has_no_media_and_optional_timestamps(self):
        for timestamps in [False, True]:
            with self.subTest(timestamps=timestamps):
                result, events = self.run_task('text', *(['--timestamps'] if timestamps else []))
                self.assertEqual(result.returncode, 0)
                paths = next(e['paths'] for e in events if e['event']=='result')
                self.assertEqual(len(paths), 2)
                for path in paths:
                    self.assertIn('待确认受访者', Path(path).parts)
                    text = Path(path).read_text()
                    self.assertIn('第一段课程内容', text)
                    self.assertEqual('[00:00:00]' in text, timestamps)
                    self.assertNotIn('token=secret', text)
                calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
                self.assertTrue(all('--skip-download' in call for call in calls))

    def test_missing_subtitles_is_failure_not_empty_success(self):
        self.env['NO_SUBS'] = '1'
        result, events = self.run_task('text')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(events[-1]['status'], 'failed')
        self.assertIn('尚不支持语音转写', next(e['message'] for e in events if e['event']=='result'))
        self.assertFalse(list(self.output.rglob('*.md')))

    def test_explicit_guest_groups_episode_and_source_files(self):
        result, events = self.run_task('text', '--guest', '测试受访者')
        self.assertEqual(result.returncode, 0)
        md = Path(next(e['paths'][0] for e in events if e['event']=='result'))
        self.assertEqual(md.parent.parent, (self.output / '测试受访者').resolve())
        self.assertTrue(list((md.parent / 'source').glob('*.vtt')))

    def test_all_optional_products(self):
        result, events = self.run_task('video', '--cover', '--transcript', '--subtitles')
        self.assertEqual(result.returncode, 0)
        results = [e for e in events if e['event']=='result']
        self.assertEqual([e['kind'] for e in results], ['视频','封面','文字稿','字幕'])
        self.assertTrue(all(Path(p).exists() for e in results for p in e['paths']))

    def test_stop_reaps_descendants_and_reports_cancelled(self):
        self.env['HANG'] = '1'
        proc = subprocess.Popen(self.command('audio'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        try:
            pid_path = self.root / 'pid'
            deadline = time.monotonic() + 5
            while not pid_path.exists() and time.monotonic() < deadline: time.sleep(.05)
            self.assertTrue(pid_path.exists())
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=6)
            self.assertEqual(proc.returncode, 130, stderr)
            self.assertEqual(json.loads(stdout.splitlines()[-1])['status'], 'cancelled')
            child_pid = int(pid_path.read_text())
            time.sleep(.1)
            with self.assertRaises(ProcessLookupError): os.kill(child_pid, 0)
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()

    def test_invalid_url_never_launches_engine(self):
        command = self.command('video')
        command[-1] = 'file:///tmp/private'
        result = subprocess.run(command, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.calls.exists())

if __name__ == '__main__': unittest.main()
