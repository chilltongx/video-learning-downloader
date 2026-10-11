#!/usr/bin/env python3
"""Desktop task runner. stdout is JSON Lines; optional products fail independently."""
from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


engine = load_module("download_engine", "download-for-editing.py")
transcripts = load_module("transcript_engine", "extract-podcast-transcript.py")


def emit(event, **values):
    print(json.dumps(dict(event=event, **values), ensure_ascii=False), flush=True)


class Cancelled(Exception):
    pass


def cancel(signum, frame):
    raise Cancelled()


def run_command(command, stage):
    """Drain output and reap the whole subprocess group even on cancellation."""
    emit("stage", text=stage)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", start_new_session=True)
    lines = []
    try:
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            lines.append(line)
            if len(lines) > 200:
                lines.pop(0)
            if line.startswith("VD_PROGRESS:"):
                parts = line.split(":", 1)[1].split("|", 2)
                try:
                    percent = float(parts[0].strip().rstrip("%"))
                    emit("progress", percent=max(0, min(100, percent)),
                         text=" · ".join(part.strip().replace("Unknown B/s", "速度计算中").replace("剩余 Unknown", "剩余时间估算中").replace("剩余 NA", "传输结束") for part in parts))
                except ValueError:
                    pass
            elif line.startswith("VD_TITLE:"):
                emit("title", text=line.split(":", 1)[1])
            elif line.startswith(("[ExtractAudio]", "[Merger]", "[VideoRemuxer]")):
                emit("stage", text="正在转换音频…" if "ExtractAudio" in line else "正在合并视频与音频…")
            else:
                emit("log", text=line)
        return process.wait(), lines
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        process.stdout.close()


def error_text(lines):
    error = next((line for line in reversed(lines) if "ERROR:" in line), "未生成文件，请展开详细日志查看原因。")
    if any(term in error.lower() for term in ("sign in", "login", "logged in", "cookies", "premium")):
        return "平台要求登录或相应账号权限，当前未使用浏览器登录态。"
    return error[:240]


class Task:
    def __init__(self, args):
        self.args = args
        self.output = Path(args.output_dir).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.results = []
        self.ytdlp = engine.executable("VIDEO_DOWNLOADER_YTDLP", "yt-dlp", Path.home() / ".local/bin/yt-dlp")
        self.base = [self.ytdlp, "--ignore-config", "--newline", "--no-playlist", "--no-colors",
                     "--socket-timeout", "20", "--retries", "2"]
        proxy, _ = engine.proxy_settings(None, args.no_system_proxy)
        if proxy:
            self.base += ["--proxy", proxy]
        node = engine.node_path()
        if node:
            self.base += ["--js-runtimes", "node:" + node]
        self.ffmpeg = None
        self.ffprobe = None
        if args.mode != "text" or args.cover:
            self.ffmpeg = engine.executable("VIDEO_DOWNLOADER_FFMPEG", "ffmpeg", Path.home() / ".local/bin/ffmpeg")
            self.base += ["--ffmpeg-location", str(Path(self.ffmpeg).parent)]
        if args.mode != "text":
            self.ffprobe = engine.executable("VIDEO_DOWNLOADER_FFPROBE", "ffprobe", Path.home() / ".local/bin/ffprobe")

    def result(self, kind, status, message, paths=()):
        item = dict(kind=kind, status=status, message=message, paths=[str(path) for path in paths])
        self.results.append(item)
        emit("result", **item)

    def media(self, url, work):
        args = self.args
        marker = work / "media-paths.txt"
        template = self.output / "%(extractor)s/%(uploader|unknown)s/%(upload_date>%Y-%m-%d|unknown)s_%(title).120B_%(id)s.%(ext)s"
        command = self.base + ["--no-overwrites", "--continue", "--trim-filenames", "160", "--embed-metadata",
            "--progress", "--progress-delta", "0.3",
            "--progress-template", "download:VD_PROGRESS:%(progress._percent_str)s|%(progress._speed_str)s|剩余 %(progress._eta_str)s",
            "--print", "before_dl:VD_TITLE:%(title)s", "--no-simulate",
            "--print-to-file", "after_move:%(filepath)s", str(marker), "-o", str(template)]
        kind = "音频" if args.mode == "audio" else "视频"
        if args.mode == "audio":
            command += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", args.audio_quality]
        else:
            height = "" if args.quality == "best" else "[height<=?%s]" % args.quality
            command += ["--merge-output-format", "mp4", "--remux-video", "mp4", "-f",
                        "bv*%s[ext=mp4]+ba[ext=m4a]/bv*%s+ba/b%s" % (height, height, height)]
        code, lines = run_command(command + [url], "正在下载%s…" % kind)
        paths = []
        if marker.exists():
            paths = list(dict.fromkeys(Path(p).resolve() for p in marker.read_text().splitlines() if p))
        valid = []
        for path in paths:
            if not path.is_file() or path.stat().st_size == 0:
                continue
            emit("stage", text="正在校验%s…" % kind)
            probe_code, probe_lines = run_command([self.ffprobe, "-v", "error", "-show_entries",
                "stream=codec_type,width,height:format=duration", "-of", "json", str(path)], "正在校验%s…" % kind)
            try:
                info = json.loads("\n".join(probe_lines))
                expected = "audio" if args.mode == "audio" else "video"
                if probe_code or not any(s.get("codec_type") == expected for s in info.get("streams", [])):
                    raise ValueError("缺少可播放的媒体流")
                valid.append(path)
                size = path.stat().st_size / (1024 * 1024)
                stream = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
                size_label = "%.1f MB" % size if size >= 1 else "%.0f KB" % (size * 1024)
                detail = "%s · %s" % (path.name, size_label)
                if stream.get("height"):
                    detail += " · 实际 %sp" % stream["height"]
                self.result(kind, "complete", detail, [path])
            except (ValueError, KeyError):
                self.result(kind, "failed", "文件校验失败，请重新下载。")
        if not valid and not paths:
            self.result(kind, "failed", error_text(lines))
        elif not valid and not any(r["kind"] == kind and r["status"] == "failed" for r in self.results):
            self.result(kind, "failed", "未找到有效的下载文件。")
        elif code and valid:
            emit("log", text="下载器报告异常，但已校验上述产物可读取。")
        return valid[0] if valid else None

    def cover(self, url, work, media):
        command = self.base + ["--skip-download", "--write-thumbnail", "--convert-thumbnails", "jpg",
                               "-o", str(work / "cover.%(ext)s"), url]
        _, lines = run_command(command, "正在获取封面…")
        covers = sorted(work.glob("cover*.jpg"))
        if not covers or not covers[0].stat().st_size:
            self.result("封面", "failed", "封面获取失败；其他已完成的文件仍然可用。")
            return
        destination = media.with_suffix(".jpg") if media else self.output / ("cover-" + uuid.uuid4().hex[:8] + ".jpg")
        shutil.copy2(covers[0], destination)
        self.result("封面", "complete", destination.name, [destination])

    def text(self, url, work, media):
        # Keep transcript source files with the episode, including failed attempts.
        root = self.output if self.args.mode == "text" else Path(self.args.transcript_dir).expanduser().resolve()
        guest = re.sub(r'[/\\:\x00-\x1f]', "-", self.args.guest).strip(" .")[:80] or "待确认受访者"
        root = root / guest
        episode = root / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
        raw = episode / "source"
        raw.mkdir(parents=True)
        command = self.base + ["--skip-download", "--write-info-json", "--write-subs", "--write-auto-subs",
            "--sub-format", "json3/vtt/srt/best", "--sub-langs", transcripts.LANGUAGE_SELECTORS[self.args.language],
            "-o", str(raw / "%(id)s.%(ext)s"), url]
        code, lines = run_command(command, "正在获取平台字幕…")
        info_files = sorted(raw.glob("*.info.json"))
        kind = "文字稿" if self.args.transcript or self.args.mode == "text" else "字幕"
        def failed(message):
            self.result(kind, "failed", message)
            if kind == "文字稿" and self.args.subtitles:
                self.result("字幕", "failed", message)
        if not info_files:
            failed(error_text(lines))
            return
        info = json.loads(info_files[0].read_text(encoding="utf-8"))
        video_id = str(info.get("id", ""))
        named_episode = root / (transcripts.slugify(str(info.get("title", video_id)), 50) + "-" +
                                transcripts.slugify(video_id, 30) + "-" + episode.name)
        episode.rename(named_episode)
        episode = named_episode
        raw = episode / "source"
        emit("title", text=info.get("title", video_id))
        subtitle = transcripts.select_subtitle(raw, video_id, self.args.language)
        if subtitle is None:
            failed(error_text(lines) if code else
                   "未找到可用的中／英文平台字幕。此版本尚不支持语音转写。")
            return
        cues = transcripts.parse_subtitle(subtitle)
        if not cues:
            failed("平台字幕为空，未生成文字稿。")
            return
        language = transcripts._language_from_filename(video_id, subtitle)
        emit("stage", text="正在整理文字稿…")
        stem = episode / "transcript"
        if self.args.mode == "text" or self.args.transcript:
            for key in ("webpage_url", "original_url"):
                if info.get(key):
                    info[key] = engine.redact_url(info[key])
            markdown, plain = transcripts.render_episode(info, cues, subtitle)
            if not self.args.timestamps:
                markdown = re.sub(r"(?m)^\*\*\[\d{2,}:\d{2}:\d{2}\]\*\* ", "", markdown)
                markdown = re.sub(r"(?m)^(## )\[\d{2,}:\d{2}:\d{2}\] ", r"\1", markdown)
            else:
                plain = str(info.get("title", video_id)) + "\n\n" + "\n\n".join(
                    "[%s] %s" % (transcripts.format_timestamp(start), text)
                    for start, text in transcripts.cues_to_paragraphs(cues)) + "\n"
            md, txt = Path(str(stem) + ".md"), Path(str(stem) + ".txt")
            md.write_text(markdown, encoding="utf-8")
            txt.write_text(plain, encoding="utf-8")
            self.result("文字稿", "complete", "平台字幕 · %s · Markdown + TXT" % language, [md, txt])
        if self.args.subtitles:
            destination = Path(str(stem) + "." + language + subtitle.suffix)
            shutil.copy2(subtitle, destination)
            self.result("字幕", "complete", "平台原始字幕 · " + language, [destination])

    def run(self):
        for index, url in enumerate(self.args.urls, 1):
            emit("item", index=index, total=len(self.args.urls), text=engine.redact_url(url))
            with tempfile.TemporaryDirectory(prefix="video-downloader-") as folder:
                work = Path(folder)
                media = None
                if self.args.mode != "text":
                    try:
                        media = self.media(url, work)
                    except (OSError, RuntimeError, ValueError) as exc:
                        self.result("音频" if self.args.mode == "audio" else "视频", "failed", str(exc))
                if self.args.cover:
                    try:
                        self.cover(url, work, media)
                    except (OSError, RuntimeError, ValueError) as exc:
                        self.result("封面", "failed", str(exc))
                if self.args.mode == "text" or self.args.transcript or self.args.subtitles:
                    try:
                        self.text(url, work, media)
                    except (OSError, RuntimeError, ValueError) as exc:
                        self.result("文字稿" if self.args.mode == "text" or self.args.transcript else "字幕", "failed", str(exc))


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--mode", choices=("audio", "text", "video"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--transcript-dir", default="/Volumes/xssd/Movies/文字稿")
    parser.add_argument("--guest", default="", help="已确认的受访者姓名；未填写时归入待确认受访者")
    parser.add_argument("--quality", choices=("1080", "720", "480", "best"), default="1080")
    parser.add_argument("--audio-quality", choices=("0", "192K", "128K"), default="0")
    parser.add_argument("--language", choices=("auto", "zh", "en"), default="auto")
    parser.add_argument("--cover", action="store_true")
    parser.add_argument("--transcript", action="store_true")
    parser.add_argument("--subtitles", action="store_true")
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--no-system-proxy", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    for url in args.urls:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            emit("done", status="failed", text="请提供有效的 http 或 https 视频链接。")
            return 1
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    task = None
    try:
        task = Task(args)
        task.run()
        successes = sum(r["status"] == "complete" for r in task.results)
        failures = len(task.results) - successes
        status = "partial" if successes and failures else "complete" if successes else "failed"
        emit("done", status=status, text=("已完成 %d 项产物" % successes) + ("，%d 项未完成" % failures if failures else ""))
        return 0 if status in ("complete", "partial") else 1
    except Cancelled:
        emit("done", status="cancelled", text="已停止，已完成的文件已保留。")
        return 130
    except Exception as exc:
        successes = bool(task and any(r["status"] == "complete" for r in task.results))
        emit("done", status="partial" if successes else "failed", text=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
