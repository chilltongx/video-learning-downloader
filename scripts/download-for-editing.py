#!/usr/bin/env python3
"""Headless Video Learning Downloader entry point for editing workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_OUTPUT_DIR = Path.home() / "Movies"
KNOWN_QUALITIES = {"best", "worst", "1080", "720", "480", "360"}
FORMATS = ("mp4", "webm", "mkv")
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
    raise RuntimeError(f"找不到 {name}；请先安装，或设置 {env_name} 指向可执行文件")


def normalize_quality(value: str) -> str:
    quality = value.strip().lower().removesuffix("p")
    if quality not in KNOWN_QUALITIES:
        choices = ", ".join(sorted(KNOWN_QUALITIES))
        raise argparse.ArgumentTypeError(f"不支持的清晰度 {value!r}；可用：{choices}")
    return quality


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            lower = key.lower()
            redacted = any(part in lower for part in SENSITIVE_QUERY_PARTS)
            query.append((key, "REDACTED" if redacted else value))
        return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ""))
    except (TypeError, ValueError):
        return url.split("?", 1)[0].split("#", 1)[0]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_selector(quality: str, container: str) -> str:
    if quality == "worst":
        return "worstvideo+worstaudio/worst"

    height = "" if quality == "best" else f"[height<={quality}]"
    if container == "mp4":
        return (
            f"bv*{height}[ext=mp4]+ba[ext=m4a]/"
            f"bv*{height}+ba/b{height}/best"
        )
    return f"bv*{height}+ba/b{height}/best"


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
        if values.get(f"{prefix}Enable") != "1":
            continue
        host = values.get(f"{prefix}Proxy")
        port = values.get(f"{prefix}Port")
        if host and port:
            return f"{scheme}://{host}:{port}"
    return None


def proxy_settings(explicit: Optional[str], disabled: bool) -> tuple[Optional[str], str]:
    if explicit:
        return explicit, "explicit"
    if disabled:
        return None, "disabled"
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        if os.environ.get(key):
            return os.environ[key], f"environment:{key}"
    system_proxy = _proxy_from_scutil()
    if system_proxy:
        return system_proxy, "macOS-system"
    return None, "none"


def probe_media(path: Path, ffprobe: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 无法读取下载结果 {path}: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe 返回了无效 JSON: {path}") from exc


def write_result(
    run_dir: Path,
    url: str,
    args: argparse.Namespace,
    status: str,
    files: list[dict[str, Any]],
    proxy_source: str,
    error: Optional[str] = None,
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_path = run_dir / f"{stamp}_{os.getpid()}.json"
    payload = {
        "schema_version": "video-learning-downloader/run-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source_url": redact_url(url),
        "output_dir": str(Path(args.output_dir).expanduser().resolve()),
        "options": {
            "quality": args.quality,
            "format": "mp3" if args.audio_only else args.format,
            "audio_only": args.audio_only,
            "playlist": args.playlist,
            "cookies_from_browser": bool(args.cookies_from_browser),
            "proxy_source": proxy_source,
        },
        "files": files,
        "error": error,
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用本地 Video Learning Downloader 下载并输出剪辑流水线可读取的 manifest。"
    )
    parser.add_argument("url", help="用户明确授权下载的视频页面 URL")
    parser.add_argument("--output-dir", "-o", default=str(DEFAULT_OUTPUT_DIR), help="保存根目录")
    parser.add_argument("--quality", "-q", type=normalize_quality, default="1080")
    parser.add_argument("--format", "-f", choices=FORMATS, default="mp4")
    parser.add_argument("--audio-only", "-a", action="store_true", help="只保存 MP3 音频")
    parser.add_argument("--playlist", action="store_true", help="显式允许下载播放列表")
    parser.add_argument(
        "--cookies-from-browser",
        choices=("chrome", "chromium", "edge", "firefox", "safari"),
        help="显式使用用户自己的浏览器登录态",
    )
    parser.add_argument("--proxy", help="显式代理 URL；不会写入结果 manifest")
    parser.add_argument("--no-system-proxy", action="store_true", help="不读取环境或 macOS 系统代理")
    parser.add_argument("--dry-run", action="store_true", help="只读取元数据，不下载")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    yt_dlp = executable("VIDEO_DOWNLOADER_YTDLP", "yt-dlp", Path.home() / ".local" / "bin" / "yt-dlp")
    ffprobe = executable("VIDEO_DOWNLOADER_FFPROBE", "ffprobe", Path.home() / ".local" / "bin" / "ffprobe")
    ffmpeg = executable("VIDEO_DOWNLOADER_FFMPEG", "ffmpeg", Path.home() / ".local" / "bin" / "ffmpeg")
    node = node_path()
    proxy, proxy_source = proxy_settings(args.proxy, args.no_system_proxy)

    cmd = [
        yt_dlp,
        "--newline",
        "--yes-playlist" if args.playlist else "--no-playlist",
        "--restrict-filenames",
        "--trim-filenames",
        "160",
        "--no-overwrites",
        "--continue",
        "--ffmpeg-location",
        str(Path(ffmpeg).parent),
    ]
    if proxy:
        cmd.extend(["--proxy", proxy])
    if node:
        cmd.extend(["--js-runtimes", f"node:{node}"])
    if args.cookies_from_browser:
        cmd.extend(["--cookies-from-browser", args.cookies_from_browser])

    if args.audio_only:
        cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0"])
    else:
        cmd.extend(
            [
                "--merge-output-format",
                args.format,
                "--embed-metadata",
                "--write-thumbnail",
                "--convert-thumbnails",
                "jpg",
                "-f",
                format_selector(args.quality, args.format),
            ]
        )

    cmd.extend(
        [
            "-o",
            str(
                output_dir
                / "%(extractor)s"
                / "%(uploader|unknown)s"
                / "%(upload_date>%Y-%m-%d|unknown)s_%(title).120B_%(id)s.%(ext)s"
            ),
        ]
    )

    print(f"ENGINE={yt_dlp}")
    print(f"OUTPUT_DIR={output_dir}")
    print(f"QUALITY={args.quality}")
    print(f"PROXY_SOURCE={proxy_source}")
    print(f"NODE_RUNTIME={'available' if node else 'missing'}")

    if args.dry_run:
        cmd.extend(["--dump-single-json", "--skip-download", args.url])
        print("DRY_RUN=1")
        return subprocess.run(cmd, check=False).returncode

    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir = output_dir / ".video-learning-downloader"
    run_dir = state_dir / "runs"
    tmp_dir = state_dir / "tmp"
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path_manifest = tmp_dir / f"paths_{os.getpid()}.txt"

    cmd.extend(["--print-to-file", "after_move:%(filepath)s", str(path_manifest), args.url])
    return_code = subprocess.run(cmd, check=False).returncode

    raw_paths = []
    if path_manifest.exists():
        raw_paths = [line.strip() for line in path_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
        path_manifest.unlink(missing_ok=True)

    unique_paths: list[Path] = []
    seen = set()
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser().resolve()
        if str(path) not in seen:
            unique_paths.append(path)
            seen.add(str(path))

    file_records: list[dict[str, Any]] = []
    validation_error: Optional[str] = None
    if return_code == 0:
        try:
            if not unique_paths:
                raise RuntimeError("下载命令成功，但没有捕获到最终文件路径")
            for path in unique_paths:
                if not path.is_file():
                    raise RuntimeError(f"下载结果不存在: {path}")
                file_records.append(
                    {
                        "path": str(path),
                        "size": path.stat().st_size,
                        "sha256": file_sha256(path),
                        "thumbnail": str(path.with_suffix(".jpg")) if path.with_suffix(".jpg").is_file() else None,
                        "ffprobe": probe_media(path, ffprobe),
                    }
                )
        except RuntimeError as exc:
            validation_error = str(exc)
            return_code = 1

    if return_code != 0 and not validation_error:
        validation_error = f"yt-dlp 退出码 {return_code}"

    status = "complete" if return_code == 0 else "failed"
    result_path = write_result(
        run_dir,
        args.url,
        args,
        status,
        file_records,
        proxy_source,
        validation_error,
    )
    print(f"RESULT_JSON={result_path}")
    for record in file_records:
        print(f"DOWNLOADED_FILE={record['path']}")
        if record["thumbnail"]:
            print(f"THUMBNAIL_FILE={record['thumbnail']}")
    if validation_error:
        print(f"ERROR={validation_error}", file=sys.stderr)
    return return_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        raise SystemExit(2)
