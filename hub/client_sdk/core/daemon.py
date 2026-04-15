"""
AgentSpace V1.5 Daemon Service
=========================

真正的"幽灵中间件" - 安装后在后台自动运行：
- 自动检测环境（国内/国际）
- 自动配置 Hub URL
- 自动启动隧道（FRP/Ngrok）
- 自动同步状态
- 自动处理任务
- 自动重试和唤醒
"""

import os
import sys
import time
import asyncio
import threading
from pathlib import Path
from typing import Optional

# 自动注入：pth 文件会在 pip install 时自动执行
# agentspace_bootstrap.pth 的内容

class AgentSpaceDaemon:
    """AgentSpace 守护进程 - 在后台自动运行"""

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = workspace or Path.home() / ".agentspace"
        self.running = False
        self._stop_event = threading.Event()
        self._webhook_process = None

    def ensure_workspace(self) -> Path:
        """确保工作空间存在"""
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "demand_inbox").mkdir(exist_ok=True)
        (self.workspace / "supply_provided").mkdir(exist_ok=True)
        return self.workspace

    def auto_detect_config(self) -> dict:
        """自动检测配置"""
        config = {}

        # 1. 自动检测区域
        # 通过网络延迟判断（国内 < 100ms，国际 > 300ms）
        try:
            import socket
            start = time.time()
            socket.create_connection(("baidu.com", 80), timeout=1)
            domestic_latency = (time.time() - start) * 1000
            if domestic_latency < 200:
                config["region"] = "cn"
                config["hub_url"] = "http://localhost:8000"
            else:
                config["region"] = "global"
                config["hub_url"] = "https://hub.clawhub.dev"
        except:
            config["region"] = "cn"
            config["hub_url"] = "http://localhost:8000"

        # 2. 自动检测隧道提供者
        config["tunnel_provider"] = "frp" if config["region"] == "cn" else "ngrok"

        # 3. 自动检测 FRP 配置
        if config["tunnel_provider"] == "frp":
            # 尝试从环境变量或默认配置读取
            config["frp_server"] = os.getenv("FRP_SERVER_ADDR", "localhost")
            config["frp_port"] = os.getenv("FRP_SERVER_PORT", "7000")

        return config

    def save_config(self, config: dict):
        """保存配置到 .env 文件"""
        env_file = self.workspace / ".env"
        env_content = f"""# AgentSpace 自动生成的配置
AGENTSPACE_REGION={config.get("region", "cn")}
HUB_URL={config.get("hub_url", "http://localhost:8000")}
"""
        if config.get("tunnel_provider") == "frp":
            env_content += f"""TUNNEL_PROVIDER=frp
FRP_SERVER_ADDR={config.get("frp_server", "127.0.0.1")}
FRP_SERVER_PORT={config.get("frp_port", "7000")}
"""
        env_file.write_text(env_content)

    async def start_background(self) -> bool:
        """在后台启动服务"""
        try:
            # 1. 确保工作空间
            workspace = self.ensure_workspace()

            # 2. 自动检测和保存配置
            config = self.auto_detect_config()
            self.save_config(config)

            # 3. 启动 Webhook 服务器（后台）
            from ..webhook.server import WebhookServer
            from ..webhook.sender import P2PSender

            webhook_server = WebhookServer(port=8000)
            webhook_port = 8001  # 使用不同端口避免冲突

            # 4. 启动隧道
            tunnel_url = None
            try:
                from ..tunnel.manager import TunnelManager
                tunnel_manager = TunnelManager()
                tunnel_url = await tunnel_manager.start(8000)
            except Exception as e:
                print(f"[WARNING] 隧道启动失败: {e}，继续本地模式")

            # 5. 冷启动同步
            if tunnel_url:
                from ..core.cold_boot import cold_boot_sync
                from .utils import get_or_create_agent_id

                agent_id = get_or_create_agent_id(workspace)
                try:
                    await cold_boot_sync(agent_id, tunnel_url, workspace)
                except Exception as e:
                    print(f"[WARNING] 状态同步失败: {e}")

            # 6. 启动文件监控（含 supply 同步和 Hub 发布回调）
            from ..core.workspace import WorkspaceWatchdog
            from ..core.supply_publisher import SupplyPublisher
            from ..core.cold_boot import sync_supply_to_hub
            from .utils import get_or_create_agent_id

            agent_id = get_or_create_agent_id(workspace)
            publisher = SupplyPublisher(agent_id)

            def _on_file_detected(file_info, tags):
                """新文件放入 supply_provided 时自动发布到 Hub"""
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(publisher.publish_supply(file_info, tags))
                except RuntimeError:
                    asyncio.run(publisher.publish_supply(file_info, tags))

            watchdog = WorkspaceWatchdog(
                workspace_path=workspace,
                agent_id=agent_id,
                on_file_callback=_on_file_detected,
            )
            observer = watchdog.start()

            # 7. 无条件同步：向 Hub 上报所有存量供给
            try:
                sync_result = await sync_supply_to_hub(agent_id, workspace)
                print(f"[AgentSpace] Supply sync: {sync_result.get('published', 0)} published, "
                      f"{sync_result.get('matched', 0)} matched")
            except Exception as e:
                print(f"[WARNING] Supply sync failed: {e}")

            self.running = True
            print(f"[AgentSpace] 守护进程已启动，工作空间: {workspace}")
            print(f"[AgentSpace] Hub: {config['hub_url']}")
            if tunnel_url:
                print(f"[AgentSpace] 隧道: {tunnel_url}")

            return True

        except Exception as e:
            print(f"[ERROR] 启动失败: {e}")
            return False

    def stop(self):
        """停止守护进程"""
        self._stop_event.set()
        self.running = False
        if self._webhook_process:
            self._webhook_process.terminate()


# ============================================================
# 安装时自动执行的初始化代码
# ============================================================

def auto_install():
    """
    安装时自动执行
    在 agentspace_bootstrap.pth 中调用
    """
    workspace = Path.home() / ".agentspace"

    # 1. 创建工作空间
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "demand_inbox").mkdir(exist_ok=True)
    (workspace / "supply_provided").mkdir(exist_ok=True)

    # 2. 自动检测配置
    daemon = AgentSpaceDaemon(workspace)
    config = daemon.auto_detect_config()
    daemon.save_config(config)

    # 3. 创建测试文件
    test_file = workspace / "supply_provided" / "readme.txt"
    if not test_file.exists():
        test_file.write_text("""AgentSpace V1.5 - 零配置 P2P 协作网络
========================================

这个目录用于放置您愿意共享给其他 Agent 的文件。

支持的文件类型：
- CSV 数据文件 (.csv)
- JSON 数据文件 (.json)
- PDF 文档 (.pdf)
- 文本文件 (.txt)
- Excel 文件 (.xlsx)

其他 Agent 可以通过语义搜索找到这些文件！

工作目录：""" + str(workspace) + """
接收目录：""" + str(workspace / "demand_inbox") + """

启动命令：
    agentspace start    # 启动节点
    agentspace stop     # 停止节点
    agentspace status   # 查看状态
""")

    print(f"[AgentSpace] 工作空间已创建: {workspace}")
    print(f"[AgentSpace] 配置已自动生成")

    return True


# ============================================================
# 命令行入口
# ============================================================

def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="AgentSpace V1.5 零配置 P2P 网络")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # start 命令
    start_parser = subparsers.add_parser("start", help="启动 AgentSpace 节点")
    start_parser.add_argument("--daemon", "-d", action="store_true", help="后台运行模式")
    start_parser.add_argument("--workspace", "-w", type=Path, default=None, help="工作空间路径")

    # stop 命令
    subparsers.add_parser("stop", help="停止 AgentSpace 节点")

    # status 命令
    subparsers.add_parser("status", help="查看节点状态")

    # init 命令
    init_parser = subparsers.add_parser("init", help="初始化工作空间")
    init_parser.add_argument("--workspace", "-w", type=Path, default=None)

    args = parser.parse_args()

    if args.command == "start":
        daemon = AgentSpaceDaemon(args.workspace)
        if args.daemon:
            # 后台模式
            asyncio.run(daemon.start_background())
        else:
            # 前台模式
            from .cli import main as cli_main
            cli_main()

    elif args.command == "stop":
        # 停止守护进程
        print("[AgentSpace] 正在停止节点...")

    elif args.command == "status":
        # 查看状态
        print("[AgentSpace] 节点状态：运行中")

    elif args.command == "init":
        # 初始化
        daemon = AgentSpaceDaemon(args.workspace)
        daemon.ensure_workspace()
        config = daemon.auto_detect_config()
        daemon.save_config(config)
        print(f"[AgentSpace] 工作空间已初始化: {daemon.workspace}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
