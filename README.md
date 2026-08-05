# Video Learning Downloader

Local-first GUI and CLI wrapper around [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
for saving authorized videos for editing and study. Supports YouTube, TikTok, and
other sites supported by `yt-dlp`.

## Features

- Native macOS UI plus a Python/Tkinter fallback.
- Single-video and batch downloads with configurable quality.
- Automatic HTTP, HTTPS, and SOCKS proxy discovery on macOS.
- Machine-readable output for editing workflows.
- Redacted run manifests, SHA-256 hashes, and `ffprobe` validation.
- Playlists disabled by default.

## Requirements

- Python 3.9 or newer.
- `yt-dlp`.
- `ffmpeg` and `ffprobe`.
- Node.js is recommended for YouTube JavaScript extraction.

On macOS with Homebrew:

```bash
brew install yt-dlp ffmpeg node
```

## Use

Run the cross-platform Python GUI:

```bash
python3 app.py
```

Download one video:

```bash
./scripts/download-one.sh "https://www.youtube.com/watch?v=VIDEO_ID"
```

Use the verified machine-readable entry point:

```bash
python3 ./scripts/download-for-editing.py "VIDEO_URL" \
  --output-dir "$HOME/Movies/video-learning" \
  --quality 1080p
```

It prints `DOWNLOADED_FILE=...` and `RESULT_JSON=...`, writes a redacted run
manifest, hashes downloaded files, and verifies media with `ffprobe`.

Download at 720p to a custom folder:

```bash
OUTPUT_DIR="$HOME/Movies/video-learning" \
QUALITY=720 \
./scripts/download-one.sh "VIDEO_URL"
```

Batch download URLs from a text file:

```bash
cp urls.example.txt urls.txt
./scripts/download-batch.sh urls.txt
```

Compile and run the native macOS UI directly from source:

```bash
swiftc -parse-as-library macos/VideoDownloader.swift \
  -framework AppKit \
  -framework CFNetwork \
  -o VideoDownloader
./VideoDownloader
```

## Configuration

The CLI detects tools on `PATH`. These environment variables can override them:

- `VIDEO_DOWNLOADER_YTDLP`
- `VIDEO_DOWNLOADER_FFMPEG`
- `VIDEO_DOWNLOADER_FFPROBE`
- `VIDEO_DOWNLOADER_NODE`

`download-one.sh` also accepts `OUTPUT_DIR`, `QUALITY`, and
`COOKIES_FROM_BROWSER`.

## Test

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/*.sh scripts/*.command
```

## Responsible use

Use only videos you own, videos with explicit permission, or videos you are
otherwise legally allowed to download and study. Do not bypass DRM, paywalls,
account restrictions, or platform rules.
