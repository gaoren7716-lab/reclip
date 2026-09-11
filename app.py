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
import sys
import io
import json
import time
import glob
import uuid
import socket
import threading
import zipfile
import shutil
from concurrent.futures import ThreadPoolExecutor

from flask import (
    Flask, request, jsonify, send_file, render_template, Response,
    stream_with_context,
)


# --------------------------------------------------------------------------- #
# 打包相关（PyInstaller --onefile / .app 支持）
# --------------------------------------------------------------------------- #
def _user_data_dir():
    """返回可写的应用数据目录（exe/.app 模式下用来存日志与最新 yt-dlp）。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "ReClip")
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/ReClip")
    else:
        path = os.path.expanduser("~/.reclip")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _safe_log(msg):
    try:
        with open(os.path.join(_user_data_dir(), "reclip.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def _ensure_ytdlp_fresh():
    """Frozen（exe/.app）模式：把最新 yt-dlp 下到可写目录并插到 sys.path 最前。
    脚本模式直接用 bundled import，跳过本函数。"""
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("RECLIP_NO_UPDATE") == "1":
        return
    try:
        import urllib.request
        ytdlp_dir = os.path.join(_user_data_dir(), "ytdlp")
        ver_file = os.path.join(ytdlp_dir, "version.txt")
        need = True
        try:
            if os.path.exists(ver_file):
                with open(ver_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if time.time() - meta.get("ts", 0) < 7 * 86400:
                    need = False
        except Exception:
            pass
        if need:
            api = json.load(urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=15))
            whl = None
            for u in api["urls"]:
                if u["packagetype"] == "bdist_wheel" and "py3-none-any" in u["filename"]:
                    whl = u["url"]
                    break
            if whl:
                _safe_log("downloading latest yt-dlp")
                data = urllib.request.urlopen(whl, timeout=60).read()
                shutil.rmtree(ytdlp_dir, ignore_errors=True)
                os.makedirs(ytdlp_dir, exist_ok=True)
                zipfile.ZipFile(io.BytesIO(data)).extractall(ytdlp_dir)
                with open(ver_file, "w", encoding="utf-8") as f:
                    json.dump({"ts": time.time()}, f)
        if os.path.isdir(ytdlp_dir) and ytdlp_dir not in sys.path:
            sys.path.insert(0, ytdlp_dir)
    except Exception as e:
        _safe_log("yt-dlp update skipped: %s" % e)


def get_ffmpeg_path():
    """优先用打包内嵌的 ffmpeg，否则回退到系统 PATH 里的 ffmpeg。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        cand = os.path.join(base, "bin", "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if os.path.exists(cand):
            return cand
    return "ffmpeg"


def _find_free_port(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, 0))
        return s.getsockname()[1]
    finally:
        s.close()


_ensure_ytdlp_fresh()

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
        "ffmpeg_location": get_ffmpeg_path(),
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
    # 窗口模式（exe/.app）下 stdout/stderr 为 None，重定向到日志文件避免崩溃
    if getattr(sys, "frozen", False):
        try:
            _log_path = os.path.join(_user_data_dir(), "reclip.log")
            _logf = open(_log_path, "a", encoding="utf-8")
            sys.stdout = _logf
            sys.stderr = _logf
        except Exception:
            pass

    host = os.environ.get("HOST", "127.0.0.1")
    # PORT 未设置或为空时自动选一个空闲端口（exe 双击时用户无感）
    _port_env = os.environ.get("PORT", "")
    try:
        port = int(_port_env) if _port_env else 0
    except ValueError:
        port = 0
    if not port:
        port = _find_free_port(host)
    _safe_log("starting ReClip on %s:%d" % (host, port))

    # 默认自动开浏览器；设 RECLIP_OPEN_BROWSER=0 可关闭
    if os.environ.get("RECLIP_OPEN_BROWSER", "1") != "0":
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    # threaded=True 保证进度 SSE 与下载任务互不阻塞
    app.run(host=host, port=port, threaded=True)
