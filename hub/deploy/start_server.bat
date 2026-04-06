@echo off
REM ===================================================
REM Hub 服务端启动脚本
REM ===================================================

echo.
echo ========================================
echo    Agent Universal Hub - 服务端启动
echo ========================================
echo.

REM 设置环境变量
set GLM_API_KEY=e6edc7b93f2d4b1e8280b73d37228e40.pOs5JhSDSFOxqcfG
set EMBEDDING_PROVIDER=glm

echo [配置] Embedding Provider: GLM
echo [配置] 服务端口: 8000
echo.

REM 检查端口占用
echo [检查] 检查端口占用...
netstat -ano | findstr :8000 >nul
if %errorlevel% == 0 (
    echo [警告] 端口 8000 已被占用，正在停止...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
        taskkill /F /PID %%a 2>nul
    )
    timeout /t 2 /nobreak >nul
)

echo [启动] 正在启动服务端...
cd /d C:\agent-hub\package
C:\Python311\python.exe -m hub_server.main

pause
