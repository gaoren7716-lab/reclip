FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RECLIP_NO_UPDATE=1 \
    HOST=0.0.0.0

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN useradd -m -u 1000 reclip && \
    mkdir -p /app/downloads && \
    chown -R reclip:reclip /app
USER reclip

# 把 reclip 用户的 --user 安装路径放在前面，便于启动时更新 yt-dlp 立即生效
ENV PATH=/home/reclip/.local/bin:$PATH

EXPOSE 8899

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
# --threads 32：每个下载任务占一条 SSE 长连接，4 线程很容易被占满导致界面卡死；
# --timeout 0：SSE 是长连接，默认 600s 会把长下载的进度推送中途掐断。
CMD ["gunicorn", "-b", "0.0.0.0:8899", "-w", "1", "--threads", "32", "--timeout", "0", "--access-logfile", "-", "app:app"]
