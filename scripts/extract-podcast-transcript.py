#!/usr/bin/env python3
"""Fetch platform subtitles with yt-dlp and organize them into readable transcripts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_OUTPUT_DIR = Path("/Volumes/xssd/Movies/文字稿/待确认受访者")
SENSITIVE_QUERY_PARTS = (
    "token",
    "signature",
    "credential",
    "policy",
    "authorization",
    "auth",
    "secret",
    "key",
    "x-amz-",
    "x-goog-",
)
LANGUAGE_SELECTORS = {
    "zh": "zh-Hans,zh-Hant,zh-CN,zh-TW,zh,en",
    "en": "en,en-US,en-GB,zh-Hans,zh",
    "auto": "zh-Hans,zh-Hant,zh,en,en-US,en-GB",
}
LANGUAGE_RANKS = {
    "zh": ("zh-hans", "zh-cn", "zh", "zh-hant", "zh-tw", "en"),
    "en": ("en", "en-us", "en-gb", "zh-hans", "zh"),
    "auto": ("zh-hans", "zh-cn", "zh", "en", "en-us", "en-gb"),
}


@dataclass
class CaptionCue:
    start: float
    end: float
    text: str


@dataclass
class EpisodeRecord:
    id: str
    title: str
    source_url: str
    uploader: str
    upload_date: str
    duration: float
    language: str
    cue_count: int
    transcript_file: str
    text_file: str
    captions_file: str
    subtitle_file: str


def executable(env_name: str, name: str, preferred: Optional[Path] = None) -> str:
    configured = os.environ.get(env_name)
    candidates = [configured, str(preferred) if preferred else None, shutil.which(name)]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) or candidate
        path = Path(resolved).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    raise RuntimeError("找不到 %s；请先安装，或设置 %s" % (name, env_name))


def node_path() -> Optional[str]:
    configured = os.environ.get("VIDEO_DOWNLOADER_NODE")
    home = Path.home()
    candidates = [
        configured,
        shutil.which("node"),
        str(home / ".local" / "bin" / "node"),
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
    ]
    pi_node_root = home / ".local" / "share" / "pi-node"
    if pi_node_root.is_dir():
        candidates[1:1] = [
            str(item / "bin" / "node")
            for item in sorted(pi_node_root.glob("node-*"), reverse=True)
        ]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) or candidate
        path = Path(resolved).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


def _proxy_from_scutil() -> Optional[str]:
    if platform.system() != "Darwin" or not shutil.which("scutil"):
        return None
    result = subprocess.run(
        ["scutil", "--proxy"], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"\s*([A-Za-z]+)\s*:\s*(.*?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2)
    for prefix, scheme in (("HTTPS", "http"), ("HTTP", "http"), ("SOCKS", "socks5h")):
        if values.get("%sEnable" % prefix) != "1":
            continue
        host = values.get("%sProxy" % prefix)
        port = values.get("%sPort" % prefix)
        if host and port:
            return "%s://%s:%s" % (scheme, host, port)
    return None


def proxy_settings(explicit: Optional[str], disabled: bool) -> tuple[Optional[str], str]:
    if explicit:
        return explicit, "explicit"
    if disabled:
        return None, "disabled"
    for key in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        if os.environ.get(key):
            return os.environ[key], "environment:%s" % key
    system_proxy = _proxy_from_scutil()
    if system_proxy:
        return system_proxy, "macOS-system"
    return None, "none"


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = "%s:%d" % (host, parts.port)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            lowered = key.lower()
            query.append(
                (key, "REDACTED" if any(part in lowered for part in SENSITIVE_QUERY_PARTS) else value)
            )
        return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ""))
    except (TypeError, ValueError):
        return url.split("?", 1)[0].split("#", 1)[0]


def clean_caption_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", value).strip()


def normalize_cues(cues: Iterable[CaptionCue]) -> list[CaptionCue]:
    normalized: list[CaptionCue] = []
    for cue in cues:
        text = clean_caption_text(cue.text)
        if not text:
            continue
        current = CaptionCue(max(cue.start, 0.0), max(cue.end, cue.start), text)
        if not normalized:
            normalized.append(current)
            continue

        previous = normalized[-1]
        close_in_time = current.start <= previous.end + 1.5
        if text == previous.text:
            previous.end = max(previous.end, current.end)
            continue
        if close_in_time and text.startswith(previous.text):
            previous.text = text
            previous.end = max(previous.end, current.end)
            continue
        if close_in_time and previous.text.startswith(text):
            previous.end = max(previous.end, current.end)
            continue

        overlap = 0
        max_overlap = min(len(previous.text), len(text), 80)
        for size in range(max_overlap, 3, -1):
            if previous.text[-size:] == text[:size]:
                overlap = size
                break
        if close_in_time and overlap >= 4:
            previous.text += text[overlap:]
            previous.end = max(previous.end, current.end)
            continue
        normalized.append(current)
    return normalized


def parse_json3(path: Path) -> list[CaptionCue]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cues = []
    for event in payload.get("events", []):
        segments = event.get("segs") or []
        text = "".join(str(segment.get("utf8", "")) for segment in segments)
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        duration = float(event.get("dDurationMs", 0)) / 1000.0
        cues.append(CaptionCue(start=start, end=start + max(duration, 0.0), text=text))
    return normalize_cues(cues)


def _parse_timestamp(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = "0", parts[0], parts[1]
    else:
        raise ValueError("无效字幕时间：%s" % value)
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_timed_text(path: Path) -> list[CaptionCue]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    cues: list[CaptionCue] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        start_raw, end_raw = line.split("-->", 1)
        end_raw = end_raw.strip().split()[0]
        try:
            start = _parse_timestamp(start_raw)
            end = _parse_timestamp(end_raw)
        except ValueError:
            index += 1
            continue
        index += 1
        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        cues.append(CaptionCue(start=start, end=end, text=" ".join(text_lines)))
    return normalize_cues(cues)


def parse_subtitle(path: Path) -> list[CaptionCue]:
    if path.suffix.lower() == ".json3":
        return parse_json3(path)
    if path.suffix.lower() in {".vtt", ".srt"}:
        return parse_timed_text(path)
    raise ValueError("不支持的字幕格式：%s" % path.suffix)


def format_timestamp(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return "%02d:%02d:%02d" % (hours, minutes, secs)


def slugify(value: str, max_length: int = 70) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^\w\u3400-\u9fff]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[-_]{2,}", "-", normalized).strip("-_")
    return normalized[:max_length].rstrip("-_") or "episode"


def _smart_join(parts: list[str]) -> str:
    output = ""
    for part in parts:
        if not output:
            output = part
            continue
        if re.search(r"[\u3400-\u9fff]$", output) and re.match(r"^[\u3400-\u9fff]", part):
            output += part
        else:
            output += " " + part
    return output


def cues_to_paragraphs(cues: list[CaptionCue]) -> list[tuple[float, str]]:
    paragraphs: list[tuple[float, str]] = []
    parts: list[str] = []
    paragraph_start = 0.0
    previous_end: Optional[float] = None

    def flush() -> None:
        nonlocal parts
        if parts:
            paragraphs.append((paragraph_start, _smart_join(parts)))
            parts = []

    for cue in cues:
        current_length = len(_smart_join(parts)) if parts else 0
        gap = cue.start - previous_end if previous_end is not None else 0.0
        should_break = bool(parts) and (
            gap > 3.5
            or current_length >= 360
            or (current_length >= 140 and re.search(r"[。！？!?…][”’\"]?$", parts[-1]))
        )
        if should_break:
            flush()
        if not parts:
            paragraph_start = cue.start
        parts.append(cue.text)
        previous_end = cue.end
    flush()
    return paragraphs


def normalized_chapters(info: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    raw_chapters = info.get("chapters") or []
    chapters = []
    for item in raw_chapters:
        start = float(item.get("start_time") or 0)
        title = clean_caption_text(str(item.get("title") or ""))
        if not title or title.startswith("<Untitled Chapter"):
            title = "开场" if start < 1 else "第 %d 部分" % (len(chapters) + 1)
        chapters.append({"start": start, "title": title})
    if chapters:
        if chapters[0]["start"] > 1:
            chapters.insert(0, {"start": 0.0, "title": "开场"})
        return chapters

    length = max(duration, 1.0)
    count = max(int((length + 299) // 300), 1)
    return [
        {"start": float(index * 300), "title": "第 %d 部分" % (index + 1)}
        for index in range(count)
    ]


def _language_from_filename(video_id: str, path: Path) -> str:
    prefix = video_id + "."
    name = path.name
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name.rsplit(".", 1)[0]


def select_subtitle(raw_dir: Path, video_id: str, language: str) -> Optional[Path]:
    candidates = []
    for extension in ("json3", "vtt", "srt"):
        candidates.extend(raw_dir.glob("%s.*.%s" % (video_id, extension)))
    if not candidates:
        return None
    ranks = LANGUAGE_RANKS[language]

    def rank(path: Path) -> tuple[int, int, str]:
        code = _language_from_filename(video_id, path).lower()
        exact = ranks.index(code) if code in ranks else len(ranks)
        extension_rank = {".json3": 0, ".vtt": 1, ".srt": 2}.get(path.suffix.lower(), 3)
        return exact, extension_rank, path.name

    return sorted(candidates, key=rank)[0]


def render_episode(
    info: dict[str, Any], cues: list[CaptionCue], subtitle_path: Path
) -> tuple[str, str]:
    title = clean_caption_text(str(info.get("title") or info.get("id") or "未命名节目"))
    source_url = str(info.get("webpage_url") or info.get("original_url") or "")
    uploader = clean_caption_text(str(info.get("uploader") or info.get("channel") or ""))
    upload_date = str(info.get("upload_date") or "")
    duration = float(info.get("duration") or (cues[-1].end if cues else 0))
    language = _language_from_filename(str(info.get("id") or ""), subtitle_path)
    chapters = normalized_chapters(info, duration)

    markdown = ["# " + title, ""]
    if source_url:
        markdown.append("- 来源：[%s](%s)" % (source_url, source_url))
    if uploader:
        markdown.append("- 节目：" + uploader)
    if upload_date and len(upload_date) == 8:
        markdown.append("- 发布：%s-%s-%s" % (upload_date[:4], upload_date[4:6], upload_date[6:]))
    if duration:
        markdown.append("- 时长：" + format_timestamp(duration))
    markdown.extend(
        [
            "- 字幕语言：" + language,
            "",
            "> 字幕来自平台官方或自动字幕，已经去除滚动重复并按章节、停顿整理；专有名词仍可能存在识别误差。",
            "",
        ]
    )
    plain = [title, ""]

    for chapter_index, chapter in enumerate(chapters):
        start = float(chapter["start"])
        end = (
            float(chapters[chapter_index + 1]["start"])
            if chapter_index + 1 < len(chapters)
            else duration + 1
        )
        chapter_cues = [cue for cue in cues if start <= cue.start < end]
        if not chapter_cues:
            continue
        heading = "[%s] %s" % (format_timestamp(start), chapter["title"])
        markdown.extend(["## " + heading, ""])
        plain.extend([str(chapter["title"]), ""])
        for paragraph_start, paragraph in cues_to_paragraphs(chapter_cues):
            markdown.extend(["**[%s]** %s" % (format_timestamp(paragraph_start), paragraph), ""])
            plain.extend([paragraph, ""])
    return "\n".join(markdown).strip() + "\n", "\n".join(plain).strip() + "\n"


def organize_downloaded_subtitles(
    raw_dirs: list[Path], output_dir: Path, language: str
) -> tuple[list[EpisodeRecord], list[str]]:
    episodes_dir = output_dir / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    records: list[EpisodeRecord] = []
    errors: list[str] = []

    info_paths = []
    for raw_dir in raw_dirs:
        info_paths.extend(raw_dir.glob("*.info.json"))
    info_paths.sort()

    for info_path in info_paths:
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append("无法读取元数据 %s：%s" % (info_path.name, exc))
            continue
        video_id = str(info.get("id") or "").strip()
        if not video_id:
            continue
        subtitle_path = select_subtitle(info_path.parent, video_id, language)
        if subtitle_path is None:
            errors.append("%s：没有找到可用字幕" % (info.get("title") or video_id))
            continue
        try:
            cues = parse_subtitle(subtitle_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append("%s：字幕解析失败：%s" % (info.get("title") or video_id, exc))
            continue
        if not cues:
            errors.append("%s：字幕为空" % (info.get("title") or video_id))
            continue

        title = clean_caption_text(str(info.get("title") or video_id))
        folder = episodes_dir / ("%03d-%s-%s" % (len(records) + 1, slugify(title), video_id))
        folder.mkdir(parents=True, exist_ok=True)
        markdown, plain = render_episode(info, cues, subtitle_path)
        transcript_path = folder / "transcript.md"
        text_path = folder / "transcript.txt"
        captions_path = folder / "captions.jsonl"
        transcript_path.write_text(markdown, encoding="utf-8")
        text_path.write_text(plain, encoding="utf-8")
        with captions_path.open("w", encoding="utf-8") as handle:
            for cue in cues:
                handle.write(json.dumps(asdict(cue), ensure_ascii=False) + "\n")

        record = EpisodeRecord(
            id=video_id,
            title=title,
            source_url=redact_url(str(info.get("webpage_url") or info.get("original_url") or "")),
            uploader=clean_caption_text(str(info.get("uploader") or info.get("channel") or "")),
            upload_date=str(info.get("upload_date") or ""),
            duration=float(info.get("duration") or cues[-1].end),
            language=_language_from_filename(video_id, subtitle_path),
            cue_count=len(cues),
            transcript_file=str(transcript_path.relative_to(output_dir)),
            text_file=str(text_path.relative_to(output_dir)),
            captions_file=str(captions_path.relative_to(output_dir)),
            subtitle_file=str(subtitle_path.relative_to(output_dir)),
        )
        records.append(record)
        print("EPISODE_DONE=%s|%s" % (video_id, title), flush=True)

    combined_md = ["# 播客字幕合集", "", "> 共整理 %d 期节目。" % len(records), ""]
    combined_txt = []
    for record in records:
        transcript = (output_dir / record.transcript_file).read_text(encoding="utf-8").strip()
        plain = (output_dir / record.text_file).read_text(encoding="utf-8").strip()
        combined_md.extend(["---", "", transcript, ""])
        combined_txt.extend([plain, "\n" + ("=" * 72) + "\n"])
    (output_dir / "transcript.md").write_text("\n".join(combined_md).strip() + "\n", encoding="utf-8")
    (output_dir / "transcript.txt").write_text("\n".join(combined_txt).strip() + "\n", encoding="utf-8")
    return records, errors


def run_yt_dlp(
    yt_dlp: str,
    node: Optional[str],
    proxy: Optional[str],
    url: str,
    raw_dir: Path,
    args: argparse.Namespace,
) -> int:
    raw_dir.mkdir(parents=True, exist_ok=True)
    command = [
        yt_dlp,
        "--newline",
        "--yes-playlist" if args.playlist else "--no-playlist",
        "--skip-download",
        "--write-info-json",
        "--no-write-playlist-metafiles",
        "--write-subs",
        "--write-auto-subs",
        "--sub-format",
        "json3/vtt/srt/best",
        "--sub-langs",
        LANGUAGE_SELECTORS[args.language],
        "--socket-timeout",
        "20",
    ]
    if args.playlist:
        command.extend(["--playlist-end", str(args.max_items)])
    if proxy:
        command.extend(["--proxy", proxy])
    if node:
        command.extend(["--js-runtimes", "node:%s" % node])
    if args.cookies_from_browser:
        command.extend(["--cookies-from-browser", args.cookies_from_browser])
    command.extend(["-o", str(raw_dir / "%(id)s.%(ext)s"), url])

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return process.wait()


def write_manifest(
    output_dir: Path,
    args: argparse.Namespace,
    records: list[EpisodeRecord],
    errors: list[str],
    proxy_source: str,
) -> Path:
    payload = {
        "schema_version": "video-learning-downloader/podcast-transcript-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if records else "failed",
        "source_urls": [redact_url(url) for url in args.urls],
        "options": {
            "language": args.language,
            "playlist": args.playlist,
            "max_items": args.max_items,
            "cookies_from_browser": bool(args.cookies_from_browser),
            "proxy_source": proxy_source,
        },
        "stats": {
            "episodes": len(records),
            "failed": len(errors),
            "caption_cues": sum(record.cue_count for record in records),
        },
        "episodes": [asdict(record) for record in records],
        "errors": errors,
        "files": {
            "transcript": "transcript.md",
            "plain_text": "transcript.txt",
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="获取播客或长视频的官方/自动字幕，并整理为按章节分段的文字稿。"
    )
    parser.add_argument("urls", nargs="+", help="一个或多个播客/视频页面 URL")
    parser.add_argument("--output-dir", "-o", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--language", choices=("zh", "en", "auto"), default="zh")
    parser.add_argument("--playlist", action="store_true", help="显式处理整个播放列表")
    parser.add_argument("--max-items", type=int, default=100, help="播放列表最大集数（默认 100）")
    parser.add_argument(
        "--cookies-from-browser",
        choices=("chrome", "chromium", "edge", "firefox", "safari"),
        help="显式使用用户自己的浏览器登录态",
    )
    parser.add_argument("--proxy", help="显式代理 URL；不会写入 manifest")
    parser.add_argument("--no-system-proxy", action="store_true", help="不读取环境或 macOS 系统代理")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_items < 1:
        parser.error("--max-items 必须大于 0")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    yt_dlp = executable(
        "VIDEO_DOWNLOADER_YTDLP",
        "yt-dlp",
        Path.home() / ".local" / "bin" / "yt-dlp",
    )
    node = node_path()
    proxy, proxy_source = proxy_settings(args.proxy, args.no_system_proxy)
    print("ENGINE=%s" % yt_dlp, flush=True)
    print("PROXY_SOURCE=%s" % proxy_source, flush=True)
    print("字幕获取不会下载视频或音频。", flush=True)

    raw_dirs = []
    download_errors = []
    for index, url in enumerate(args.urls, start=1):
        raw_dir = output_dir / "raw" / ("source-%03d" % index)
        raw_dirs.append(raw_dir)
        print("\n[%d/%d] 正在获取字幕：%s" % (index, len(args.urls), redact_url(url)), flush=True)
        return_code = run_yt_dlp(yt_dlp, node, proxy, url, raw_dir, args)
        if return_code != 0:
            download_errors.append("%s：yt-dlp 退出码 %d" % (redact_url(url), return_code))

    records, organize_errors = organize_downloaded_subtitles(raw_dirs, output_dir, args.language)
    errors = download_errors + organize_errors
    manifest_path = write_manifest(output_dir, args, records, errors, proxy_source)
    print("\n完成：整理 %d 期，失败 %d 期。" % (len(records), len(errors)), flush=True)
    print("TRANSCRIPT_FILE=%s" % (output_dir / "transcript.md"), flush=True)
    print("RESULT_JSON=%s" % manifest_path, flush=True)
    for error in errors:
        print("WARNING=%s" % error, file=sys.stderr, flush=True)
    return 0 if records else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print("ERROR=%s" % exc, file=sys.stderr)
        raise SystemExit(2)
