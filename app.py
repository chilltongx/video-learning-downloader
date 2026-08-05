#!/usr/bin/env python3
import json
import os
import queue
import shutil
import subprocess
import threading
import traceback
from pathlib import Path
from tkinter import END, StringVar, Text, Tk, filedialog, messagebox
import tkinter as tk


APP_NAME = "Video Learning Downloader"
DEFAULT_OUTPUT_DIR = str(Path.home() / "Movies")
CONFIG_PATH = Path.home() / ".config" / "video-learning-downloader" / "settings.json"
LOG_PATH = Path.home() / "Library" / "Logs" / "video-learning-downloader.log"
LOCAL_BIN = Path.home() / ".local" / "bin"
YTDLP = shutil.which("yt-dlp") or str(LOCAL_BIN / "yt-dlp")
FFMPEG_DIR = str(LOCAL_BIN)

BG = "#f3f5f7"
PANEL = "#ffffff"
TEXT = "#111827"
MUTED = "#6b7280"
BORDER = "#c9d1d9"
PRIMARY = "#2563eb"
DANGER = "#b42318"
LOG_BG = "#111827"
LOG_FG = "#e5e7eb"


class DownloadApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("780x560")
        self.root.minsize(680, 480)
        self.root.configure(bg=BG)

        self.log_queue = queue.Queue()
        self.process = None
        self.worker = None
        self.cancel_requested = False

        settings = self.load_settings()
        self.output_dir = StringVar(value=settings.get("output_dir", DEFAULT_OUTPUT_DIR))
        self.quality = StringVar(value=settings.get("quality", "1080"))
        self.status = StringVar(value="准备就绪")

        self.build_ui()
        self.write_log("准备就绪。粘贴链接，选择保存文件夹，然后点击下载。\n")
        self.root.after(100, self.drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        padding = {"padx": 18, "pady": 8}

        header = tk.Frame(self.root, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
        header.columnconfigure(0, weight=1)

        title = tk.Label(header, text="视频下载", font=("", 22, "bold"), bg=BG, fg=TEXT)
        title.grid(row=0, column=0, sticky="w")

        quality_box = tk.Frame(header, bg=BG)
        quality_box.grid(row=0, column=1, sticky="e")
        tk.Label(quality_box, text="清晰度", bg=BG, fg=MUTED).grid(row=0, column=0, padx=(0, 8))
        quality_menu = tk.OptionMenu(quality_box, self.quality, "1080", "720", "480", "best")
        quality_menu.configure(bg=PANEL, fg=TEXT, activebackground="#e8eefc", relief="solid", bd=1, width=7)
        quality_menu.grid(row=0, column=1)

        link_frame = tk.Frame(self.root, bg=BG)
        link_frame.grid(row=1, column=0, sticky="nsew", **padding)
        link_frame.columnconfigure(0, weight=1)
        tk.Label(link_frame, text="视频链接", bg=BG, fg=MUTED).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.url_text = Text(
            link_frame,
            height=5,
            wrap="word",
            undo=True,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            padx=10,
            pady=8,
        )
        self.url_text.grid(row=1, column=0, sticky="nsew")
        self.url_text.focus_set()

        path_frame = tk.Frame(self.root, bg=BG)
        path_frame.grid(row=2, column=0, sticky="ew", **padding)
        path_frame.columnconfigure(1, weight=1)
        tk.Label(path_frame, text="保存到", bg=BG, fg=MUTED).grid(row=0, column=0, sticky="w", padx=(0, 10))
        tk.Entry(
            path_frame,
            textvariable=self.output_dir,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
        ).grid(row=0, column=1, sticky="ew", ipady=5)
        tk.Button(
            path_frame,
            text="选择",
            command=self.choose_output_dir,
            bg=PANEL,
            fg=TEXT,
            activebackground="#e8eefc",
            relief="solid",
            bd=1,
            padx=14,
            pady=4,
        ).grid(row=0, column=2, padx=(10, 0))

        log_frame = tk.Frame(self.root, bg=BG)
        log_frame.grid(row=3, column=0, sticky="nsew", **padding)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = Text(
            log_frame,
            height=12,
            wrap="word",
            state="disabled",
            bg=LOG_BG,
            fg=LOG_FG,
            insertbackground=LOG_FG,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=10,
            pady=8,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = tk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        footer = tk.Frame(self.root, bg=BG)
        footer.grid(row=4, column=0, sticky="ew", padx=18, pady=(6, 18))
        footer.columnconfigure(0, weight=1)
        tk.Label(footer, textvariable=self.status, bg=BG, fg=MUTED).grid(row=0, column=0, sticky="w")
        self.download_button = tk.Button(
            footer,
            text="下载",
            command=self.start_download,
            bg=PRIMARY,
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief="flat",
            padx=20,
            pady=7,
        )
        self.download_button.grid(row=0, column=2, padx=(0, 8))
        self.cancel_button = tk.Button(
            footer,
            text="停止",
            command=self.cancel_download,
            bg=PANEL,
            fg=DANGER,
            activebackground="#fee4e2",
            relief="solid",
            bd=1,
            padx=20,
            pady=6,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=3)

    def choose_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self.output_dir.get() or DEFAULT_OUTPUT_DIR)
        if selected:
            self.output_dir.set(selected)
            self.save_settings()

    def start_download(self):
        if self.worker and self.worker.is_alive():
            return

        urls = [line.strip() for line in self.url_text.get("1.0", END).splitlines() if line.strip()]
        if not urls:
            messagebox.showinfo(APP_NAME, "先粘贴视频链接。")
            return

        output_dir = self.output_dir.get().strip()
        if not output_dir:
            messagebox.showinfo(APP_NAME, "先选择保存文件夹。")
            return
        output_dir = str(Path(output_dir).expanduser())
        self.output_dir.set(output_dir)

        if not Path(YTDLP).exists() and shutil.which("yt-dlp") is None:
            messagebox.showerror(APP_NAME, "找不到 yt-dlp。")
            return

        Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        self.save_settings()
        self.cancel_requested = False
        self.set_running(True)
        self.clear_log()
        self.write_log(f"保存到: {output_dir}\n")

        self.worker = threading.Thread(target=self.download_urls, args=(urls, output_dir), daemon=True)
        self.worker.start()

    def download_urls(self, urls, output_dir):
        failed = 0
        for index, url in enumerate(urls, start=1):
            if self.cancel_requested:
                break

            self.log_queue.put(("status", f"下载中 {index}/{len(urls)}"))
            self.log_queue.put(("log", f"\n[{index}/{len(urls)}] {url}\n"))
            cmd = self.build_command(url, output_dir)

            process = None
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                self.process = process

                assert process.stdout is not None
                for line in process.stdout:
                    self.log_queue.put(("log", line))

                return_code = process.wait()
                if return_code != 0 and not self.cancel_requested:
                    failed += 1
                    self.log_queue.put(("log", f"下载失败，退出码: {return_code}\n"))
            except Exception as exc:
                if not self.cancel_requested:
                    failed += 1
                    self.log_queue.put(("log", f"下载失败: {exc}\n"))
            finally:
                if process is not None and self.process is process:
                    self.process = None

        if self.cancel_requested:
            self.log_queue.put(("status", "已停止"))
        elif failed:
            self.log_queue.put(("status", f"完成，失败 {failed} 个"))
        else:
            self.log_queue.put(("status", "下载完成"))
        self.log_queue.put(("done", None))

    def build_command(self, url, output_dir):
        quality = self.quality.get()
        if quality == "best":
            fmt = "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/best"
        else:
            fmt = f"bv*[height<={quality}][ext=mp4]+ba[ext=m4a]/bv*[height<={quality}]+ba/b[height<={quality}]/best"

        return [
            YTDLP,
            "--newline",
            "--no-playlist",
            "--restrict-filenames",
            "--trim-filenames",
            "160",
            "--merge-output-format",
            "mp4",
            "--embed-metadata",
            "--write-thumbnail",
            "--convert-thumbnails",
            "jpg",
            "--ffmpeg-location",
            FFMPEG_DIR,
            "-f",
            fmt,
            "-o",
            f"{output_dir}/%(extractor)s/%(uploader|unknown)s/%(upload_date>%Y-%m-%d|unknown)s_%(title).120B_%(id)s.%(ext)s",
            url,
        ]

    def cancel_download(self):
        if self.process:
            self.process.terminate()
            self.write_log("\n已请求停止。\n")
        self.cancel_requested = True
        self.set_running(False)
        self.status.set("已停止")

    def set_running(self, running):
        if running:
            self.download_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
        else:
            self.download_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")

    def drain_log_queue(self):
        try:
            while True:
                kind, value = self.log_queue.get_nowait()
                if kind == "log":
                    self.write_log(value)
                elif kind == "status":
                    self.status.set(value)
                elif kind == "done":
                    self.set_running(False)
        except queue.Empty:
            pass
        self.root.after(100, self.drain_log_queue)

    def write_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert(END, text)
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")

    def load_settings(self):
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_settings(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(
                {"output_dir": self.output_dir.get(), "quality": self.quality.get()},
                indent=2,
            ),
            encoding="utf-8",
        )

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "下载仍在进行，确定退出？"):
                return
            self.cancel_download()
        self.root.destroy()


def main():
    root = Tk()
    DownloadApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(traceback.format_exc())
            log_file.write("\n")
        raise
