#!/bin/bash
# ReClip 一键启动器（macOS / Linux）
# 用法：  ./reclip.sh
# 自动检查并安装依赖（Python / ffmpeg / yt-dlp），启动后自动打开浏览器。
# 环境变量：RECLIP_NO_UPDATE=1 跳过 yt-dlp 更新；PORT 修改端口。

set -e
cd "$(dirname "$0")"

say()   { echo -e "\033[36m[ReClip]\033[0m $1"; }
ok()    { echo -e "  \033[32m✓\033[0m $1"; }
warn()  { echo -e "  \033[33m!\033[0m $1"; }

PORT="${PORT:-8899}"

# --------------------------------------------------------------------------- #
# 1. Python
# --------------------------------------------------------------------------- #
say "检查 Python..."
if ! command -v python3 &> /dev/null; then
  warn "未检测到 python3。请先安装： https://www.python.org/downloads/  (macOS: brew install python)"
  exit 1
fi
ok "$(python3 --version 2>&1)"

# --------------------------------------------------------------------------- #
# 2. 虚拟环境 + 依赖
# --------------------------------------------------------------------------- #
say "准备运行环境（虚拟环境 + 依赖）..."
if [ ! -d "venv" ]; then
  echo "  创建虚拟环境..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q --upgrade pip
pip install -q flask
if [ -n "$RECLIP_NO_UPDATE" ]; then
  pip install -q yt-dlp
else
  echo "  更新 yt-dlp（各平台提取器经常变动）..."
  pip install -q -U yt-dlp || warn "yt-dlp 更新失败，将使用已安装版本"
fi
ok "依赖安装完成"

# --------------------------------------------------------------------------- #
# 3. ffmpeg（合成 MP4 / 提取 MP3 必需）
# --------------------------------------------------------------------------- #
say "检查 ffmpeg..."
if ! command -v ffmpeg &> /dev/null; then
  warn "未检测到 ffmpeg，尝试安装..."
  if command -v brew &> /dev/null; then
    brew install ffmpeg
  elif command -v apt-get &> /dev/null; then
    sudo apt-get update && sudo apt-get install -y ffmpeg
  else
    warn "无法自动安装 ffmpeg。请手动安装（仅影响 MP4 合成 / MP3 提取）。"
  fi
else
  ok "ffmpeg 已就绪"
fi

# --------------------------------------------------------------------------- #
# 4. 启动 + 自动打开浏览器
# --------------------------------------------------------------------------- #
say "启动 ReClip 服务..."
export PORT
export RECLIP_OPEN_BROWSER=0
# 2 秒后打开浏览器
( sleep 2; (command -v xdg-open >/dev/null && xdg-open "http://localhost:$PORT") || (command -v open >/dev/null && open "http://localhost:$PORT") ) >/dev/null 2>&1 &
python3 app.py
