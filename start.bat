@echo off
chcp 65001 >nul
title Web RAG System - 一键启动
setlocal enabledelayedexpansion

echo ========================================
echo   AI 知识库问答系统 - 一键启动
echo   Web RAG System
echo ========================================
echo.

REM 自动以管理员权限运行（PowerShell 执行策略需要）
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 提示: 以管理员身份运行可避免 PowerShell 执行策略问题
    echo.
)

REM 检查 PowerShell 版本
powershell -Command "exit 0" 2>nul
if %errorlevel% neq 0 (
    echo 错误: 需要 PowerShell 5.1 或更高版本
    pause
    exit /b 1
)

REM 执行主启动脚本
echo 正在启动所有服务，请稍候...
echo.
echo 提示: 如果这是首次运行，安装依赖可能需要 3-5 分钟
echo.
echo 服务启动后会自动打开前端页面 ^(http://localhost:3000^)
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1"

REM 如果 PowerShell 执行失败，给用户提示
if %errorlevel% neq 0 (
    echo.
    echo 启动过程中出现错误，请检查上方红色错误信息。
    echo 常见问题:
    echo   1. Docker Desktop 未运行
    echo   2. Python 3.11+ 未安装
    echo   3. 端口 5432/6379/8000/3000 被占用
    echo.
    pause
)