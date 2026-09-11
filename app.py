#!/usr/bin/env python3
"""ReClip — 傻瓜式视频/音频下载器（后端）。

基于 averygan/reclip 复刻并升级：
  * 改用 yt-dlp Python API（原生进度钩子）
  * 新增 /api/progress 实时进度（Server-Sent Events）
  * 可配置超时、自动打开浏览器开关
  * 跨平台一键启动器（Windows / macOS / Linux）

依赖：Flask + yt-dlp（+ 系统 ffmpeg 用于合成 MP4 / 提取 MP3）
"""
import os
import uuid
import glob
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import (
    Flask, request, jsonify, send_file, render_template, Response,
    stream_with_context,
)

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except Exception:  # pragma: no cover - 依赖由启动脚本保证安装
    yt_dlp = None
    DownloadError = Exception

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}
_executor = ThreadPoolExecutor(max_workers=8)

# 单任务下载超时（秒），可用环境变量 RECLIP_TIMEOUT 覆盖
DEFAULT_TIMEOUT = int(os.environ.get("RECLIP_TIMEOUT", "1800"))


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def run_with_timeout(fn, timeout, default=None):
    """在线程池里跑 fn，超时返回 default。"""
    fut = _executor.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except Exception:
        return default


def make_progress_hook(job_id):
    """yt-dlp 进度钩子，把进度写进 jobs[job_id]。"""

    def hook(d):
        job = jobs.get(job_id)
        if not job:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                try:
                    job["progress"] = round(downloaded / total * 100, 1)
                except Exception:
                    pass
            job["speed"] = d.get("speed")
            job["eta"] = d.get("eta")
        elif status == "finished":
            job["progress"] = 100

    return hook


def build_formats(info):
    """提取每个分辨率的最佳格式，用于前端清晰度选择器。"""
    best = {}
    for f in info.get("formats", []):
        h = f.get("height")
        if not h:
            continue
        if f.get("vcodec", "none") == "none":
            continue
        is_combined = f.get("acodec", "none") != "none"
        f["_combined"] = is_combined
        tbr = f.get("tbr") or 0
        cur = best.get(h)
        if cur is None:
            best[h] = f
        else:
            cur_combined = cur.get("_combined")
            # 优先选纯视频流（下载时再合并最佳音轨），同档位取更高码率
            if (not is_combined) and cur_combined:
                best[h] = f
            elif is_combined == cur_combined and tbr > (cur.get("tbr") or 0):
                best[h] = f

    formats = []
    for h, f in best.items():
        formats.append({
            "id": f["format_id"],
            "label": f"{h}p",
            "height": h,
        })
    formats.sort(key=lambda x: x["height"], reverse=True)
    return formats


# --------------------------------------------------------------------------- #
# 下载任务
# --------------------------------------------------------------------------- #
def run_download(job_id, url, format_choice, format_id):
    job = jobs[job_id]
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": out_template,
        "noplaylist": True,
        "progress_hooks": [make_progress_hook(job_id)],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    if format_choice == "audio":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            }],
        })
    elif format_id:
        ydl_opts["format"] = f"{format_id}+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"
    else:
        ydl_opts["format"] = "bestvideo+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
        if not files:
            job["status"] = "error"
            job["error"] = "下载完成但未找到文件"
            return

        target_ext = ".mp3" if format_choice == "audio" else ".mp4"
        target = [f for f in files if f.lower().endswith(target_ext)]
        chosen = target[0] if target else files[0]

        for f in files:
            if f != chosen:
                try:
                    os.remove(f)
                except OSError:
                    pass

        job["status"] = "done"
        job["file"] = chosen
        ext = os.path.splitext(chosen)[1]
        title = job.get("title", "").strip()
        if title:
            safe = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:100].strip()
            job["filename"] = f"{safe}{ext}" if safe else os.path.basename(chosen)
        else:
            job["filename"] = os.path.basename(chosen)
    except DownloadError as e:
        job["status"] = "error"
        job["error"] = str(e)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "请提供视频链接"}), 400
    if yt_dlp is None:
        return jsonify({"error": "yt-dlp 未安装，请先运行启动脚本（reclip.sh / reclip.bat）"}), 500

    def _extract():
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = run_with_timeout(_extract, 60)
        if info is None:
            return jsonify({"error": "获取视频信息超时，请稍后重试"}), 400

        formats = build_formats(info)
        return jsonify({
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "uploader": info.get("uploader", ""),
            "formats": formats,
        })
    except DownloadError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/playlist", methods=["POST"])
def get_playlist_info():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "请提供播放列表链接"}), 400
    if yt_dlp is None:
        return jsonify({"error": "yt-dlp 未安装"}), 500

    def _extract():
        with yt_dlp.YoutubeDL({
            "quiet": True, "no_warnings": True,
            "extract_flat": True, "skip_download": True,
        }) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = run_with_timeout(_extract, 60)
        entries = (info or {}).get("entries", [])
        urls = [e.get("url") for e in entries if e.get("url")]
        return jsonify({"urls": urls})
    except DownloadError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    title = data.get("title", "")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {
        "status": "downloading",
        "progress": 0,
        "url": url,
        "title": title,
        "format": format_choice,
    }
    threading.Thread(
        target=run_download,
        args=(job_id, url, format_choice, format_id),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def progress(job_id):
    """Server-Sent Events：实时推送下载进度。"""

    def gen():
        while True:
            job = jobs.get(job_id)
            if not job:
                yield "data: " + json.dumps({"status": "error", "error": "任务不存在"}) + "\n\n"
                break
            payload = {
                "status": job.get("status"),
                "progress": job.get("progress", 0),
                "speed": job.get("speed"),
                "eta": job.get("eta"),
                "filename": job.get("filename"),
                "error": job.get("error"),
            }
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            if job.get("status") in ("done", "error"):
                break
            time.sleep(0.6)

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/status/<job_id>")
def check_status(job_id):
    """兼容旧版轮询接口。"""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job.get("status"),
        "error": job.get("error"),
        "filename": job.get("filename"),
        "progress": job.get("progress", 0),
    })


@app.route("/api/file/<job_id>")
def download_file(job_id):
    job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(
        job["file"],
        as_attachment=True,
        download_name=job.get("filename", os.path.basename(job["file"])),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    if os.environ.get("RECLIP_OPEN_BROWSER") == "1":
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    # threaded=True 保证进度 SSE 与下载任务互不阻塞
    app.run(host=host, port=port, threaded=True)
