@echo off
REM Agent Hub 一键部署脚本 - Windows Server
REM 在腾讯云服务器上运行此脚本

echo =====================================
echo   Agent Universal Hub 一键部署
echo =====================================
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本
    pause
    exit /b 1
)

REM 创建目录
echo [1/8] 创建项目目录...
if not exist C:\agent-hub mkdir C:\agent-hub
if not exist C:\agent-hub\logs mkdir C:\agent-hub\logs
if not exist C:\agent-hub\backups mkdir C:\agent-hub\backups
cd /d C:\agent-hub

REM 检查 Python
echo [2/8] 检查 Python 环境...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo Python 未安装，正在下载安装器...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe' -OutFile 'python_installer.exe'"
    echo 正在安装 Python，请稍候...
    python_installer.exe /quiet InstallAllUsers=1 PrependPath=1
    timeout /t 30 /nobreak >nul
    echo Python 安装完成
) else (
    echo Python 已安装
)

REM 检查项目文件
echo [3/8] 检查项目文件...
if not exist hub_server\main.py (
    echo.
    echo [警告] 项目文件不存在！
    echo 请先上传项目文件到 C:\agent-hub
    echo.
    echo 上传方式：
    echo 1. 通过远程桌面复制本地 e:\hub 文件夹到服务器 C:\agent-hub
    echo 2. 或者在宝塔面板中上传文件
    echo.
    pause
    exit /b 1
)

REM 安装 Python 依赖
echo [4/8] 安装 Python 依赖...
if exist requirements.txt (
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
) else (
    echo requirements.txt 不存在，跳过依赖安装
)

REM 创建 .env 配置
echo [5/8] 创建环境配置...
if not exist .env (
    echo DATABASE_URL=postgresql://postgres:postgres@localhost:5432/agent_hub > .env
    echo EMBEDDING_PROVIDER=glm >> .env
    echo GLM_API_KEY=e6edc7b93f2d4b1e8280b73d37228e40.pOs5JhSDSFOxqcfG >> .env
    echo GLM_EMBEDDING_MODEL=embedding-3 >> .env
    echo HUB_JWT_SECRET=change-me-in-production >> .env
    echo 配置文件已创建
) else (
    echo 配置文件已存在
)

REM 创建启动脚本
echo [6/8] 创建启动脚本...
echo @echo off > start.bat
echo cd /d C:\agent-hub >> start.bat
echo python -m uvicorn hub_server.main:app --host 0.0.0.0 --port 8000 >> start.bat

REM 配置防火墙
echo [7/8] 配置防火墙...
netsh advfirewall firewall add rule name="Agent Hub HTTP" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
echo 防火墙规则已添加

REM 完成
echo [8/8] 部署准备完成！
echo.
echo =====================================
echo   下一步操作
echo =====================================
echo.
echo 1. 安装 PostgreSQL（如果尚未安装）
echo    下载: https://www.postgresql.org/download/windows/
echo.
echo 2. 初始化数据库
echo    psql -U postgres -f scripts\init_db.sql
echo.
echo 3. 启动服务
echo    start.bat
echo.
echo 4. 访问服务
echo    http://your-server-ip:8000/docs
echo.
echo =====================================
pause
