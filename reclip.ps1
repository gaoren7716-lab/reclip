# ReClip 一键启动器（Windows）
# 双击 reclip.bat 即会调用本脚本。
# 职责：找到/安装 Python -> 创建虚拟环境 -> 安装 flask/yt-dlp ->
#       确保 ffmpeg 可用 -> 自动打开浏览器 -> 启动服务。
# 可用环境变量：RECLIP_NO_UPDATE=1 跳过 yt-dlp 更新；PORT 修改端口。

$ErrorActionPreference = 'Continue'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

function WriteStep($msg) { Write-Host "`n[ReClip] $msg" -ForegroundColor Cyan }
function WriteOk($msg)   { Write-Host "  ✓ $msg" -ForegroundColor Green }
function WriteWarn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function WriteErr($msg)  { Write-Host "  ✗ $msg" -ForegroundColor Red }

$PORT = if ($env:PORT) { $env:PORT } else { "8899" }

# --------------------------------------------------------------------------- #
# 1. 找到 Python
# --------------------------------------------------------------------------- #
WriteStep "检查 Python..."
$PY = $null
foreach ($cand in @('py', 'python', 'python3')) {
    try {
        $v = & $cand -c "import sys; print(sys.version.split()[0])" 2>$null
        if ($v) { $PY = $cand; break }
    } catch { }
}

if (-not $PY) {
    WriteWarn "未检测到 Python，尝试通过 winget 安装..."
    try {
        winget install Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements | Out-Null
        # 刷新 PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $PY = 'py'
    } catch {
        WriteErr "Python 安装失败。请手动安装：https://www.python.org/downloads/  （勾选 'Add to PATH'）"
        exit 1
    }
}
$v = & $PY -c "import sys; print(sys.version.split()[0])" 2>$null
WriteOk "Python $v"

# --------------------------------------------------------------------------- #
# 2. 虚拟环境 + 依赖
# --------------------------------------------------------------------------- #
WriteStep "准备运行环境（虚拟环境 + 依赖）..."
$VenvPy = Join-Path $ScriptDir "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "  创建虚拟环境..."
    & $PY -m venv venv | Out-Null
}
$PY = $VenvPy
WriteOk "虚拟环境就绪"

& $PY -m pip install -q --upgrade pip 2>$null
& $PY -m pip install -q flask 2>$null
if ($env:RECLIP_NO_UPDATE) {
    & $PY -m pip install -q yt-dlp 2>$null
} else {
    Write-Host "  更新 yt-dlp（各平台提取器经常变动）..."
    & $PY -m pip install -q -U yt-dlp 2>$null
    if ($LASTEXITCODE -ne 0) { WriteWarn "yt-dlp 更新失败，将使用已安装版本" }
}
WriteOk "依赖安装完成"

# --------------------------------------------------------------------------- #
# 3. 确保 ffmpeg 可用（合成 MP4 / 提取 MP3 必需）
# --------------------------------------------------------------------------- #
WriteStep "检查 ffmpeg..."
$LocalFfmpeg = Join-Path $ScriptDir ".tools\ffmpeg\bin\ffmpeg.exe"
$ffmpegOk = $false
try { & ffmpeg -version 2>$null | Out-Null; $ffmpegOk = $? } catch { }
if (-not $ffmpegOk -and (Test-Path $LocalFfmpeg)) {
    $env:Path = "$ScriptDir\.tools\ffmpeg\bin;" + $env:Path
    $ffmpegOk = $true
}

if (-not $ffmpegOk) {
    WriteWarn "未检测到 ffmpeg，尝试安装..."
    $installed = $false
    try {
        winget install Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        try { & ffmpeg -version 2>$null | Out-Null; $installed = $? } catch { }
    } catch { }

    if (-not $installed) {
        # 兜底：下载 gyan.dev 的便携版并解压到 .tools
        try {
            $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-7.1-essentials_build.zip"
            $zip = Join-Path $ScriptDir ".tools\ffmpeg.zip"
            New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir ".tools") | Out-Null
            Write-Host "  下载 ffmpeg 便携版..."
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
            Expand-Archive -Path $zip -DestinationPath (Join-Path $ScriptDir ".tools\ffmpeg_extract") -Force
            $inner = Get-ChildItem (Join-Path $ScriptDir ".tools\ffmpeg_extract") -Directory | Select-Object -First 1
            Move-Item -Path (Join-Path $inner.FullName "*") -Destination (Join-Path $ScriptDir ".tools\ffmpeg") -Force
            Remove-Item (Join-Path $ScriptDir ".tools\ffmpeg_extract") -Recurse -Force
            Remove-Item $zip -Force
            $env:Path = "$ScriptDir\.tools\ffmpeg\bin;" + $env:Path
            try { & ffmpeg -version 2>$null | Out-Null; $installed = $? } catch { }
        } catch { }
    }

    if ($installed) { WriteOk "ffmpeg 已就绪" } else { WriteWarn "ffmpeg 安装失败，仅能下载单一格式（MP4 合成/MP3 需要它）" }
} else {
    WriteOk "ffmpeg 已就绪"
}

# --------------------------------------------------------------------------- #
# 4. 启动（自动打开浏览器）
# --------------------------------------------------------------------------- #
WriteStep "启动 ReClip 服务..."
$env:PORT = $PORT
$env:RECLIP_OPEN_BROWSER = "0"   # 浏览器由脚本负责打开，避免重复

# 2 秒后打开浏览器
$job = Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:$using:PORT"
}
try {
    & $PY app.py
} finally {
    Stop-Job $job -ErrorAction SilentlyContinue | Out-Null
    Remove-Job $job -ErrorAction SilentlyContinue | Out-Null
}
