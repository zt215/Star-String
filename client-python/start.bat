@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv
    echo 请先在 client-python 目录执行: python -m venv .venv ^&^& .venv\Scripts\pip install -e .
    pause
    exit /b 1
)

".venv\Scripts\python.exe" start.py
if errorlevel 1 (
    echo.
    echo [错误] 客户端启动失败
    pause
)
