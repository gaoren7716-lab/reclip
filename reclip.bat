@echo off
rem ReClip 一键启动器（Windows）
rem 直接双击本文件即可：自动安装依赖、打开浏览器、启动服务。
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0reclip.ps1"
pause
