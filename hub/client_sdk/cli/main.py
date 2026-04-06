"""AgentSpace CLI - Zero-config command-line interface.

This module provides the agentspace init and agentspace start commands for
setting up and running an AgentSpace node with zero configuration.
"""

from __future__ import annotations

# === 编码设置（必须在其他 import 之前）===
import os
import sys

# 强制 UTF-8 编码，避免 Windows GBK 控制台导致 UnicodeEncodeError
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUTF8', '1')

# 重新配置 stdout/stderr 为 UTF-8（如果可能）
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

import asyncio
import subprocess
from pathlib import Path

import click

from ..core.workspace import WorkspaceWatchdog
from ..discovery.radar import DiscoveryRadar
from ..tunnel.manager import TunnelManager


@click.group()
@click.version_option(version="1.6.0")
def cli() -> None:
    """AgentSpace V1.6 - Zero-Config P2P Agent Collaboration Network."""
    pass


@cli.command()
def version() -> None:
    """显示版本和安装路径信息。"""
    import client_sdk
    click.echo(f"AgentSpace SDK 版本: 1.6.0")
    click.echo(f"代码路径: {client_sdk.__file__}")

    # 检查是否为 editable 安装
    import pip
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "agentspace-sdk"],
            capture_output=True, text=True
        )
        for line in result.stdout.split("\n"):
            if line.startswith("Location:") or line.startswith("Editable:"):
                click.echo(f"  {line.strip()}")
    except Exception:
        pass


@cli.command()
def stop() -> None:
    """停止运行中的 AgentSpace 服务。"""
    import subprocess

    workspace = Path.home() / ".agentspace"
    pid_file = workspace / ".agentspace.pid"

    # 检查 PID 文件
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            try:
                os.kill(old_pid, 15)  # SIGTERM
                click.echo(f"✓ 已发送停止信号到进程 {old_pid}")
            except (OSError, ProcessLookupError):
                click.echo(f"进程 {old_pid} 已不存在")
        except (ValueError, IOError):
            pass
        finally:
            pid_file.unlink(missing_ok=True)

    # 强制终止所有 agentspace 进程
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "agentspace.exe"],
            capture_output=True, text=True
        )
        if "SUCCESS" in result.stdout or "成功" in result.stdout:
            click.echo("✓ 已强制停止 agentspace.exe 进程")
        elif "not found" in result.stderr.lower() or "未找到" in result.stderr:
            click.echo("没有运行中的 agentspace 进程")
    else:
        result = subprocess.run(
            ["pkill", "-f", "agentspace"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            click.echo("✓ 已停止 agentspace 进程")
        else:
            click.echo("没有运行中的 agentspace 进程")


@cli.command()
@click.option("--port", default=8000, help="Webhook 服务端口")
@click.option("--remote", is_flag=True, help="检查云端 Hub 连接")
def check(port: int, remote: bool) -> None:
    """检查 AgentSpace 服务健康状态和端点可用性。"""
    import httpx

    base_url = f"http://localhost:{port}"

    # 读取本地 token
    token_file = Path.home() / ".agentspace" / ".local_token"
    token = token_file.read_text().strip() if token_file.exists() else ""

    endpoints = [
        ("/health", "GET", None, "健康检查"),
        ("/openapi.json", "GET", None, "API 文档"),
        ("/api/local/trigger_demand", "POST", {"resource_type": "test"}, "本地接单"),
        ("/api/p2p/address", "POST", {"tags": []}, "P2P 地址"),
    ]

    click.echo(f"🔍 检查 AgentSpace 服务 (端口 {port})\n")

    all_ok = True
    for path, method, body, desc in endpoints:
        try:
            headers = {}
            if path == "/api/local/trigger_demand" and token:
                headers["Authorization"] = f"Bearer {token}"

            if method == "GET":
                r = httpx.get(f"{base_url}{path}", timeout=5)
            else:
                r = httpx.post(f"{base_url}{path}", json=body or {}, headers=headers, timeout=30)

            if r.status_code < 500:
                status = "✅"
            else:
                status = "❌"
                all_ok = False

            click.echo(f"  {status} {path}: {r.status_code} ({desc})")
        except httpx.ConnectError:
            click.echo(f"  ❌ {path}: 连接失败 ({desc})")
            all_ok = False
        except Exception as e:
            click.echo(f"  ❌ {path}: {e} ({desc})")
            all_ok = False

    # 检查云端 Hub 连接
    if remote:
        click.echo("\n🌐 检查云端 Hub 连接...")
        hub_url = os.getenv("HUB_URL", "http://localhost:8000")
        try:
            r = httpx.get(f"{hub_url}/health", timeout=10)
            if r.status_code == 200:
                click.echo(f"  ✅ Hub Server: {hub_url} (可达)")
            else:
                click.echo(f"  ⚠️ Hub Server: {hub_url} (状态码: {r.status_code})")
        except httpx.ConnectError:
            click.echo(f"  ❌ Hub Server: {hub_url} (连接失败)")
        except Exception as e:
            click.echo(f"  ❌ Hub Server: {hub_url} ({e})")

    click.echo("")
    if all_ok:
        click.echo("✅ 所有端点正常")
    else:
        click.echo("⚠️ 部分端点不可用，请检查服务是否启动")


@cli.command()
@click.option(
    "--region",
    type=click.Choice(["cn", "global"], case_sensitive=False),
    prompt="Select your region",
    help="Region selection (cn=China, global=Rest of World)",
)
@click.option(
    "--workspace",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom workspace path (default: ~/.agentspace)",
)
def init(region: str, workspace: Path | None) -> None:
    """
    Initialize AgentSpace workspace with zero-config setup.

    This command:
    - Creates the workspace directory structure
    - Sets up region configuration in .env
    - Runs DiscoveryRadar to scan for local skills
    - Generates agentspace_config.yaml snapshot
    """
    # Determine workspace path
    if workspace is None:
        workspace = Path.home() / ".agentspace"
    else:
        workspace = workspace.expanduser()

    click.echo(f"🚀 Initializing AgentSpace workspace at: {workspace}")

    # Create directory structure
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "demand_inbox").mkdir(exist_ok=True)
    (workspace / "supply_provided").mkdir(exist_ok=True)

    click.echo("✅ Directory structure created")

    # Create .env file with region config
    env_file = workspace / ".env"
    hub_url = "http://localhost:8000" if region == "cn" else "https://hub.clawhub.dev"

    # Determine hub URL based on region
    if region == "cn":
        hub_url = "http://localhost:8000"
        frp_server = "localhost"
    else:
        hub_url = "https://hub.clawhub.dev"
        frp_server = "hub.clawhub.dev"

    env_content = f"""# AgentSpace Configuration
# Generated by agentspace init

# Region: {region.upper()}
AGENTSPACE_REGION={region}
HUB_URL={hub_url}

# FRP Tunnel Configuration
TUNNEL_PROVIDER=frp
FRP_SERVER_ADDR={frp_server}
FRP_SERVER_PORT=7000
FRP_TOKEN={os.getenv('FRP_TOKEN', '')}

# Optional: Add your API keys here for zero-key injection
# OPENAI_API_KEY=your_key_here
# ANTHROPIC_API_KEY=your_key_here
"""

    env_file.write_text(env_content, encoding="utf-8")
    click.echo(f"✅ Environment configured for region: {region.upper()}")

    # Run DiscoveryRadar to scan for skills
    click.echo("🔡 Scanning for local skills...")

    radar = DiscoveryRadar(project_root=Path.cwd(), config_path=workspace / "agentspace_config.yaml")
    result = radar.scan_and_save()

    skills_count = result.get("skills_count", 0)
    errors = result.get("scan_errors", [])

    if skills_count > 0:
        click.echo(f"✅ Found {skills_count} skill(s)")
        for skill in result.get("local_skills", [])[:5]:
            click.echo(f"   - {skill['name']}: {skill.get('description', 'No description')[:50]}")
        if skills_count > 5:
            click.echo(f"   ... and {skills_count - 5} more")
    else:
        click.echo("ℹ️  No @skill decorated functions found")
        click.echo("   Use @skill decorator in your Python files to register skills")

    if errors:
        click.echo(f"⚠️  Scan completed with {len(errors)} error(s)")

    click.echo(f"\n🎉 AgentSpace initialized successfully!")
    click.echo(f"\nNext steps:")
    click.echo(f"   1. Review your skills in: {workspace / 'agentspace_config.yaml'}")
    click.echo(f"   2. Place files to share in: {workspace / 'supply_provided'}")
    click.echo(f"   3. Run 'agentspace start' to begin listening for P2P requests")


@cli.command()
@click.option(
    "--workspace",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom workspace path (default: ~/.agentspace)",
)
@click.option(
    "--no-tunnel",
    is_flag=True,
    help="Skip tunnel creation (for local testing)",
)
@click.option(
    "--daemon",
    "-d",
    is_flag=True,
    help="Run as background daemon (auto-restart on failure)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="强制重启（自动停止旧进程）",
)
def start(workspace: Path | None, no_tunnel: bool, daemon: bool, force: bool) -> None:
    """
    Start AgentSpace node with demand-driven file transfer.

    This command:
    - Runs DiscoveryRadar to update skill snapshot
    - Starts WorkspaceWatchdog to monitor supply_provided
    - Starts WebhookServer to receive incoming files
    - Optionally creates network tunnel for P2P access
    - Automatically matches demands and delivers files
    - Keeps running until interrupted
    """
    # Determine workspace path
    if workspace is None:
        workspace = Path.home() / ".agentspace"
    else:
        workspace = workspace.expanduser()

    # === PID 管理：检查是否已有实例运行 ===
    pid_file = workspace / ".agentspace.pid"

    # --force 选项：自动停止旧进程
    if force and pid_file.exists():
        click.echo("🔄 强制重启模式：正在停止旧进程...")
        try:
            old_pid = int(pid_file.read_text().strip())
            try:
                os.kill(old_pid, 15)  # SIGTERM
                import time
                time.sleep(1)  # 等待进程退出
                click.echo(f"   ✓ 已停止旧进程 (PID: {old_pid})")
            except (OSError, ProcessLookupError):
                pass
        except (ValueError, IOError):
            pass
        finally:
            pid_file.unlink(missing_ok=True)

        # Windows: 额外强制终止 agentspace.exe
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "agentspace.exe"],
                         capture_output=True)
            click.echo("   ✓ 已强制终止 agentspace.exe")

    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            # 检查进程是否存在
            import signal
            try:
                os.kill(old_pid, 0)  # 信号 0 不会杀死进程，只检查是否存在
                click.echo(f"❌ AgentSpace 已在运行 (PID: {old_pid})")
                click.echo("   如需重启，请先运行: agentspace stop")
                click.echo("   或使用: agentspace start --force")
                return
            except (OSError, ProcessLookupError):
                # 进程不存在，删除旧的 PID 文件
                pid_file.unlink()
        except (ValueError, IOError):
            # PID 文件损坏，删除
            pid_file.unlink()

    # Auto-create workspace if missing (zero-config)
    if not workspace.exists():
        click.echo(f"🔧 Workspace not found, creating automatically...")
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "demand_inbox").mkdir(exist_ok=True)
        (workspace / "supply_provided").mkdir(exist_ok=True)
        click.echo(f"   ✓ Workspace created: {workspace}")

    # 写入当前 PID
    workspace.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    click.echo(f"   PID: {os.getpid()}")

    # Always check and fix .env configuration
    env_file = workspace / ".env"
    needs_reload = False

    if not env_file.exists():
        import socket
        import time
        try:
            start = time.time()
            socket.create_connection(("baidu.com", 80), timeout=1)
            domestic_latency = (time.time() - start) * 1000
            if domestic_latency < 200:
                region = "cn"
                hub_url = "http://localhost:8000"
            else:
                region = "global"
                hub_url = "https://hub.clawhub.dev"
        except:
            region = "cn"
            hub_url = "http://localhost:8000"

        env_content = f"""# AgentSpace 自动生成的配置
AGENTSPACE_REGION={region}
HUB_URL={hub_url}
TUNNEL_PROVIDER=frp
FRP_SERVER_ADDR=localhost
FRP_SERVER_PORT=7000
# FRP 可执行文件路径（如果不在 PATH 中）
FRP_EXECUTABLE=frpc
"""
        env_file.write_text(env_content, encoding="utf-8")
        click.echo(f"   ✓ 已配置为 {region.upper()} 区域 (FRP)")
        needs_reload = True
    else:
        # Check if .env contains FRP configuration
        env_content = env_file.read_text(encoding="utf-8")
        if "TUNNEL_PROVIDER=frp" not in env_content:
            # Update existing .env to use FRP
            import socket
            import time
            try:
                start = time.time()
                socket.create_connection(("baidu.com", 80), timeout=1)
                domestic_latency = (time.time() - start) * 1000
                if domestic_latency < 200:
                    region = "cn"
                    hub_url = "http://localhost:8000"
                else:
                    region = "global"
                    hub_url = "https://hub.clawhub.dev"
            except:
                region = "cn"
                hub_url = "http://localhost:8000"

            env_content = f"""# AgentSpace 自动生成的配置
AGENTSPACE_REGION={region}
HUB_URL={hub_url}
TUNNEL_PROVIDER=frp
FRP_SERVER_ADDR=localhost
FRP_SERVER_PORT=7000
# FRP 可执行文件路径（如果不在 PATH 中）
FRP_EXECUTABLE=frpc
"""
            env_file.write_text(env_content, encoding="utf-8")
            click.echo(f"   ✓ 配置已更新为 {region.upper()} 区域 (FRP)")
            needs_reload = True

    # Reload configuration from .env file to ensure tunnel settings are applied
    from dotenv import load_dotenv
    load_dotenv(env_file, encoding="utf-8")

    click.echo(f"🟢 Starting AgentSpace node...")
    click.echo(f"   Workspace: {workspace}")

    # Show tunnel configuration
    tunnel_provider = os.getenv('TUNNEL_PROVIDER', 'default')
    click.echo(f"   ✓ Config loaded: TUNNEL_PROVIDER={tunnel_provider}")

    # Update skill snapshot
    click.echo("🔡 Updating skill snapshot...")
    radar = DiscoveryRadar(project_root=Path.cwd(), config_path=workspace / "agentspace_config.yaml")
    result = radar.scan_and_save()
    skills_count = result.get("skills_count", 0)
    click.echo(f"   Found {skills_count} skill(s)")

    # Import required modules for P2P file transfer
    import asyncio
    from ..webhook.server import WebhookServer
    from ..core.supply_publisher import SupplyPublisher
    from ..core.delivery_orchestrator import DeliveryOrchestrator
    import threading

    # Get agent ID
    agent_id = _get_or_create_agent_id(workspace)

    # 创建主事件循环（在整个命令期间保持活跃）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start WebhookServer for receiving files
    webhook_port = 8000
    webhook_server = WebhookServer(port=webhook_port)

    def run_webhook():
        import uvicorn
        uvicorn.run(webhook_server.app, host="0.0.0.0", port=webhook_port, log_level="warning")

    webhook_thread = threading.Thread(target=run_webhook, daemon=True)
    webhook_thread.start()
    click.echo(f"📡 Webhook server listening on port {webhook_port}")

    # Optionally start tunnel
    tunnel_url = None
    if not no_tunnel:
        tunnel_provider = os.getenv('TUNNEL_PROVIDER', 'auto')
        click.echo(f"🌐 Setting up network tunnel (Provider: {tunnel_provider})...")
        try:
            tunnel_manager = TunnelManager()
            # Try different tunnel providers in order
            tunnel_url = asyncio.run(tunnel_manager.start(webhook_port))
            click.echo(f"   Tunnel URL: {tunnel_url}")
        except Exception as e:
            click.echo(f"⚠️  Tunnel setup failed: {e}")
            click.echo("   Continuing without tunnel (local only)")

    # Initialize services
    supply_dir = workspace / "supply_provided"
    supply_publisher = SupplyPublisher(agent_id)
    delivery_orchestrator = DeliveryOrchestrator(agent_id, supply_dir)

    # Define file detection callback（⚠️ 已修正线程安全）
    def on_file_detected(file_info: dict, tags: list):
        """Callback when new file is detected - triggers demand matching."""
        click.echo(f"[NEW FILE] {file_info['filename']} with tags: {tags}")

        # 定义异步包裹函数
        async def process_and_deliver():
            try:
                click.echo("[ASYNC] Starting supply publish...")
                matched_demands = await supply_publisher.publish_supply(file_info, tags)
                click.echo(f"[ASYNC] Matched demands: {len(matched_demands) if matched_demands else 0}")
                if matched_demands:
                    click.echo(f"[MATCH] Found {len(matched_demands)} demand(s)")
                    results = await delivery_orchestrator.deliver_to_matched_seekers(
                        file_info["local_path"], matched_demands
                    )
                    success_count = sum(1 for v in results.values() if v)
                    click.echo(f"[DELIVERY] Delivered to {success_count}/{len(results)} seeker(s)")
                else:
                    click.echo("[INFO] No matching demands found")
            except Exception as e:
                click.echo(f"[ERROR] Async task failed: {e}")

        # ⚠️ 关键修正：安全地跨线程提交异步任务
        future = asyncio.run_coroutine_threadsafe(process_and_deliver(), loop)
        click.echo(f"[ASYNC] Task submitted: {future}")

    # Start watchdog for file monitoring
    watchdog = WorkspaceWatchdog(
        workspace_path=workspace,
        agent_id=agent_id,
        on_file_callback=on_file_detected
    )

    click.echo("👀 Watching for files in supply_provided/")

    # 🌟 [V1.6.4] 无条件同步：向 Hub 上报所有存量供给（不依赖 tunnel）
    click.echo("📡 Syncing inventory to Hub...")
    try:
        from ..core.cold_boot import sync_supply_to_hub
        sync_result = loop.run_until_complete(
            sync_supply_to_hub(agent_id, workspace)
        )
        published = sync_result.get("published", 0)
        matched = sync_result.get("matched", 0)
        errors = sync_result.get("errors", 0)
        click.echo(f"   ✅ Supply sync: {published} file(s) published, {matched} demand(s) matched, {errors} error(s)")
    except Exception as e:
        click.echo(f"   ⚠️  Supply sync failed: {e}")

    # 🌟 冷启动状态同步（仅 tunnel 可用时）
    if tunnel_url:
        click.echo("📡 Syncing status to cloud Hub...")
        from ..core.cold_boot import cold_boot_sync
        try:
            loop.run_until_complete(cold_boot_sync(agent_id, tunnel_url, workspace))
            click.echo("   ✅ Status sync completed")
        except Exception as e:
            click.echo(f"   ⚠️  Status sync failed: {e}")

    # Start watchdog observer
    observer = watchdog.start()

    click.echo("\n✅ AgentSpace node is running")
    click.echo("   Press Ctrl+C to stop\n")

    # ⚠️ 关键修复：在后台线程中运行事件循环，处理异步任务
    def run_event_loop():
        """Run event loop in background thread to process async tasks."""
        loop.run_forever()

    loop_thread = threading.Thread(target=run_event_loop, daemon=True)
    loop_thread.start()
    click.echo("🔄 Event loop started (for async task processing)")

    try:
        # Keep the main thread alive
        observer.join()
    except KeyboardInterrupt:
        click.echo("\n\n👋 Shutting down...")
        watchdog.stop()
        if tunnel_url:
            click.echo("   Tunnel closed")
        click.echo("✅ AgentSpace node stopped")
    finally:
        loop.close()
        # 清理 PID 文件
        if pid_file.exists():
            pid_file.unlink()


def _get_or_create_agent_id(workspace: Path) -> str:
    """获取或创建 Agent ID"""
    agent_file = workspace / ".agent_id"
    if agent_file.exists():
        return agent_file.read_text().strip()

    import uuid
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    agent_file.write_text(agent_id)
    return agent_id


def main() -> None:
    """Entry point for agentspace CLI."""
    cli()


if __name__ == "__main__":
    main()
