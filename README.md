# ReClip · 傻瓜式视频 / 音频下载器

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

一个自托管的免费视频 / 音频下载器：粘贴链接 → 选清晰度 → 下载为 **MP4** 或 **MP3**。
基于强大的 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 引擎，支持 YouTube、TikTok、Instagram、B 站、Twitter/X、Reddit 等 **1000+ 网站**。

> 本仓库是基于 [averygan/reclip](https://github.com/averygan/reclip) 的**复刻优化版**，重点做了三件事：
> 1. **一键启动** —— 提供 Windows 双击即用脚本，自动装好所有依赖（Python / ffmpeg / yt-dlp）并自动打开浏览器。
> 2. **真实进度条** —— 下载时显示实时百分比、速度与剩余时间（原版只有「Downloading...」）。
> 3. **中文界面** —— 支持中文 / 英文一键切换（默认跟随系统语言）。

---

## 🚀 一分钟上手（三选一）

### 方式 A：Windows 双击即用（最推荐，零门槛）

1. 下载本仓库（绿色 `Code` → `Download ZIP`，解压）。
2. **双击 `reclip.bat`**。
3. 脚本会自动安装依赖、打开浏览器，看到界面即可粘贴链接。

> 首次运行会联网安装 Python 依赖与 ffmpeg，请保持网络畅通，耐心等待一两分钟。
> 之后每次双击都是秒开。

### 方式 B：macOS / Linux 一行命令

```bash
git clone https://github.com/gaoren7716-lab/reclip.git
cd reclip
./reclip.sh
```

脚本会自动装好依赖、打开浏览器。

### 方式 C：Docker（服务器 / 高级用户）

```bash
docker compose up -d --build
# 打开 http://localhost:8899
```

---

## 📖 使用步骤

1. 在输入框粘贴**一个或多个**视频链接（每行一个，或用空格、逗号分隔）。
2. 选择 **MP4**（视频）或 **MP3**（音频）。
3. 点击 **获取信息**，稍候会显示封面、标题与可选清晰度。
4. 点单条 **下载**，或点 **一键全部下载**。
5. 下载完成后浏览器会自动保存文件；进度条实时显示百分比 / 速度 / 剩余时间。

---

## ✨ 功能特性

- 支持 **1000+ 网站**（yt-dlp 全量支持）。
- **MP4 视频** 或 **MP3 音频** 提取。
- **清晰度选择**：自动列出每个分辨率的最佳格式。
- **批量下载**：一次粘贴多个链接，自动去重。
- **真实进度条**：实时百分比 + 速度 + 预估剩余时间（SSE 推送）。
- **中 / 英界面**：右上角一键切换，默认跟随浏览器语言。
- **自动更新 yt-dlp**：各平台提取器经常失效，启动时自动更新（可关闭）。
- **零构建前端**：纯 HTML/CSS/JS，没有打包步骤。
- **跨平台一键启动**：Windows 双击、macOS/Linux 脚本、Docker 三选一。

---

## ⚙️ 进阶设置（环境变量）

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `PORT` | 服务端口 | `8899` |
| `HOST` | 监听地址（`0.0.0.0` 可局域网访问） | `127.0.0.1` |
| `RECLIP_TIMEOUT` | 单任务下载超时（秒） | `1800` |
| `RECLIP_NO_UPDATE` | 设为 `1` 跳过 yt-dlp 启动更新 | 未设置（即更新） |

示例（Windows PowerShell）：
```powershell
$env:PORT = 9000
.\reclip.bat
```

---

## 🔧 故障排查

| 现象 | 解决办法 |
| --- | --- |
| 双击 `reclip.bat` 闪退 | 以管理员身份运行一次；确保已联网。看黑框里的红色提示。 |
| 提示「未检测到 Python」 | 脚本会尝试 winget 安装；失败时手动装 [Python](https://www.python.org/downloads/)，**务必勾选 Add to PATH**。 |
| 提示缺少 ffmpeg | Windows 会自动 winget 安装；失败则手动下载 [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) 并加入 PATH。仅影响 MP4 合成 / MP3 提取。 |
| 「该链接暂不支持 / 视频不可用」 | 平台限制或需登录；换源或确认链接有效。 |
| 下载很慢 / 卡住 | 大文件请调大 `RECLIP_TIMEOUT`；检查网络。 |
| yt-dlp 报错「Sign in to confirm」 | YouTube 风控，等待 yt-dlp 更新或换链接；可设 `RECLIP_NO_UPDATE=1` 后用 `pip install -U yt-dlp` 手动升级。 |

---

## 🧱 技术栈

- **后端**：Python + Flask（约 200 行，改用 yt-dlp Python API + SSE 进度）。
- **前端**：原生 HTML/CSS/JS（单文件，无构建）。
- **下载引擎**：[yt-dlp](https://github.com/yt-dlp/yt-dlp) + [ffmpeg](https://ffmpeg.org/)。
- **依赖**：仅 2 个（Flask、yt-dlp）。

---

## 🙏 致谢与许可

- 复刻自 [averygan/reclip](https://github.com/averygan/reclip)（MIT），感谢原作者。
- 本优化版同样以 **MIT 协议** 发布，详见 [LICENSE](LICENSE)。

> ⚠️ **免责声明**：本工具仅供个人学习与技术研究使用。请遵守相关平台的用户协议与当地版权法律，勿用于任何侵权或违规用途。开发者不对任何滥用行为负责。

---

### English (short)

A self-hosted video/audio downloader (MP4/MP3) for 1000+ sites via yt-dlp. This is a fork-and-upgrade of [averygan/reclip](https://github.com/averygan/reclip) with: one-click Windows launcher (`reclip.bat`), real progress bars (SSE), and a Chinese/English UI toggle.

- **Windows**: double-click `reclip.bat`.
- **macOS/Linux**: `./reclip.sh`.
- **Docker**: `docker compose up -d --build`.

Open <http://localhost:8899>. MIT licensed.
