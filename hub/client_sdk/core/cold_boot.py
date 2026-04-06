"""Cold boot sync - Event-driven P2P delivery initialization."""
import asyncio
import json
from pathlib import Path
from ..webhook.sender import P2PSender
from ..config import HUB_URL, API_V1_PREFIX
from .entity_extractor import EntityExtractor


async def sync_supply_to_hub(agent_id: str, workspace: Path) -> dict:
    """
    V1.6.4: 无条件同步 - 将 inventory 中所有存量供给上报到 Hub。

    不管 tunnel 是否可用，只要 supply_provided 中有文件，
    就逐个调用 Hub 的 supply endpoint 进行语义匹配。

    Args:
        agent_id: Agent ID
        workspace: 工作空间路径

    Returns:
        {"published": int, "matched": int, "errors": int}
    """
    supply_dir = workspace / "supply_provided"
    inventory_file = workspace / "inventory_map.json"

    if not supply_dir.exists() or not any(supply_dir.iterdir()):
        return {"published": 0, "matched": 0, "errors": 0}

    # 从 inventory_map.json 读取已有文件信息（含 tags）
    inventory_files = []
    if inventory_file.exists():
        try:
            data = json.loads(inventory_file.read_text(encoding="utf-8"))
            inventory_files = data.get("files", [])
        except Exception:
            pass

    # 如果 inventory 为空但目录有文件，扫描并提取 tags
    if not inventory_files:
        extractor = EntityExtractor()
        for f in supply_dir.iterdir():
            if f.is_file() and not f.name.startswith("."):
                tags = extractor.extract_tags(f.name)
                inventory_files.append({
                    "filename": f.name,
                    "local_path": str(f),
                    "entity_tags": tags,
                    "file_type": f.suffix,
                    "size_bytes": f.stat().st_size,
                })

    import httpx

    published = 0
    matched = 0
    errors = 0
    hub_url = f"{HUB_URL}{API_V1_PREFIX}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        for file_entry in inventory_files:
            filename = file_entry.get("filename", "")
            tags = file_entry.get("entity_tags", [])

            if not tags:
                extractor = EntityExtractor()
                tags = extractor.extract_tags(filename)

            payload = {
                "agent_id": agent_id,
                "resource_type": file_entry.get("file_type", filename.rsplit(".", 1)[-1] if "." in filename else "file").lstrip("."),
                "tags": tags,
                "supply_vector": None,
                "description": filename,
            }

            try:
                response = await client.post(
                    f"{hub_url}/agents/{agent_id}/supply",
                    json=payload,
                )
                if response.status_code == 200:
                    published += 1
                    data = response.json()
                    demands = data.get("matched_demands", [])
                    matched += len(demands)
                    if demands:
                        print(f"[COLD-BOOT] ✅ {filename} matched {len(demands)} demand(s)")
                else:
                    errors += 1
                    print(f"[COLD-BOOT] ⚠️ {filename}: Hub returned {response.status_code}")
            except Exception as e:
                errors += 1
                print(f"[COLD-BOOT] ⚠️ {filename}: {e}")

    print(f"[COLD-BOOT] Summary: {published} published, {matched} matched, {errors} errors")
    return {"published": published, "matched": matched, "errors": errors}


async def cold_boot_sync(agent_id: str, public_webhook_url: str, workspace: Path):
    """
    冷启动同步：盘点库存并上报 Hub

    Args:
        agent_id: Agent ID
        public_webhook_url: 公网 Base URL (不含路径)
        workspace: 工作空间路径
    """
    supply_dir = workspace / "supply_provided"

    # 1. 扫描文件夹，提取存量标签
    inventory_tags = _extract_tags_from_folder(supply_dir)

    # 2. 组装上线广播
    # ⚠️ URL 修正：只上报 Base URL，不含路径
    payload = {
        "node_status": "active",
        "live_broadcast": f"系统冷启动上线，拥有资源：{','.join(inventory_tags)}",
        "tags": inventory_tags,
        "webhook_url": public_webhook_url  # 👈 仅根地址，例如 https://xxx.ngrok.app
    }

    # 3. 发送给 Hub
    # ⚠️ 路由修正：包含 agent_id 路径参数
    url = f"{HUB_URL}/api/v1/agents/{agent_id}/status"
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.patch(url, json=payload)

        if response.status_code == 200:
            data = response.json()
            delivery_tasks = data.get("delivery_tasks", [])

            if delivery_tasks:
                print(f"[AgentSpace] 检测到 {len(delivery_tasks)} 个待发货订单且需求方在线，正在自动投递...")
                sender = P2PSender()

                for task in delivery_tasks:
                    # ⚠️ 安全修正：根据 resource_type 匹配文件
                    file_path = _find_file_for_demand(supply_dir, task)
                    if file_path:
                        # 异步触发直邮
                        asyncio.create_task(
                            sender.send_file_to_seeker(
                                matched_demand=task,
                                file_path=str(file_path),
                                provider_id=agent_id
                            )
                        )


def _extract_tags_from_folder(folder: Path) -> list:
    """从文件夹提取标签"""
    tags = set()
    if not folder.exists():
        return []

    for file in folder.iterdir():
        if file.is_file():
            # 从文件名提取标签（简化实现）
            tags.add(file.suffix[1:])  # 扩展名作为标签

    return list(tags)


def _find_file_for_demand(supply_dir: Path, demand_info: dict) -> Path | None:
    """
    根据需求信息查找本地文件 (安全版本)

    ⚠️ 防止发错文件：必须根据 resource_type 匹配文件后缀
    """
    if not supply_dir.exists():
        return None

    # 从 demand_info 或从 demand_id 推断资源类型
    # 简化实现：假设 demand_id 包含资源类型，或使用默认值
    resource_type = demand_info.get("resource_type", "csv")
    expected_ext = f".{resource_type}"

    for file in supply_dir.iterdir():
        if file.is_file() and file.suffix == expected_ext:
            return file

    print(f"[WARNING] 无法在本地找到匹配 {expected_ext} 的文件，取消自动发货")
    return None
