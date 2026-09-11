#!/bin/sh
# 容器启动时保持 yt-dlp 为最新——各平台（Instagram、Facebook 等）的提取器
# 经常失效，最常见的修复方式就是更新 yt-dlp。
# 安装到 reclip 用户的 ~/.local（已在 PATH 最前面）。设置 RECLIP_NO_UPDATE=1 可跳过。
if [ -z "$RECLIP_NO_UPDATE" ]; then
    echo "Updating yt-dlp..."
    pip install --user --no-cache-dir -q -U yt-dlp || \
        echo "  (无法更新 yt-dlp —— 继续使用已安装版本)"
fi

exec "$@"
