"""Webhook Server - P2P task receiver and file delivery endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Callable

import jwt
from fastapi import FastAPI, HTTPException, Request, status, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse

from ..config import HUB_JWT_SECRET, HUB_URL, API_V1_PREFIX
from hub_server.api.contracts import (
    P2PTaskEnvelope,
    P2PAckResponse,
    P2PAddressRequest,
    P2PDeliveryRequest,
)
from client_sdk.core.payload_handler import restore_inbound_payload
from ..security.file_whitelist import FileExtensionWhitelist
from ..gateway.task_cache import TaskCache
from ..gateway.openclaw_bridge import OpenClawBridge
from ..gateway.router import UniversalResourceGateway
from ..gateway.auto_catcher import ResourceMissingError


TaskHandler = Callable[[str, dict], dict | None]

_gateway_instance = None


def set_gateway_instance(gateway):
    global _gateway_instance
    _gateway_instance = gateway


def _load_or_generate_local_token() -> str:
    """加载已有 Token，仅在文件不存在时生成新 Token（无 BOM）。

    复用策略：token 仅用于 localhost 本机认证（OpenClaw 插件 → 本地 API），
    不存在远程攻击面。每次重启都重新生成会破坏与已运行插件的 token 一致性，
    是 403 错误的直接根因。
    """
    token_file = Path.home() / ".agentspace" / ".local_token"
    token_file.parent.mkdir(parents=True, exist_ok=True)

    # 复用已有 token
    if token_file.exists():
        existing = token_file.read_text(encoding="utf-8").strip()
        if len(existing) >= 16:
            return existing

    # 首次启动：生成新 token
    token = secrets.token_hex(32)
    token_file.write_text(token, encoding="utf-8")
    return token


class WebhookServer:
    def __init__(self, port: int = 8000, task_handler: TaskHandler | None = None):
        self.port = port
        self.task_handler = task_handler
        self.app = FastAPI(title="Agent Webhook Receiver")
        self._task_cache = TaskCache()
        self._bridge = OpenClawBridge()
        self._local_token = _load_or_generate_local_token()  # 复用已有 Token
        self._setup_routes()
        self._setup_middleware()

    def _setup_middleware(self):
        @self.app.middleware("http")
        async def jwt_middleware(request: Request, call_next):
            # 本地端点跳过 JWT 验证（使用动态 Token）
            if request.url.path == "/api/local/trigger_demand":
                return await call_next(request)
            if request.url.path.startswith("/api/local/demand/"):
                return await call_next(request)

            # 信令端点不需要 JWT 验证
            if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json", "/api/webhook/signal"]:
                return await call_next(request)

            if request.url.path == "/api/webhook":
                token = request.headers.get("X-Match-Token")
                if not token:
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "error": "MissingTokenError",
                            "message": "Missing X-Match-Token",
                        },
                    )

                try:
                    payload = jwt.decode(token, HUB_JWT_SECRET, algorithms=["HS256"])
                    request.state.jwt_payload = payload
                except jwt.ExpiredSignatureError:
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"error": "TokenExpiredError", "message": "JWT expired"},
                    )
                except jwt.InvalidTokenError as exc:
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"error": "InvalidTokenError", "message": str(exc)},
                    )

            return await call_next(request)

    def _setup_routes(self):
        @self.app.get("/health")
        async def health_check():
            return {"status": "healthy", "service": "agent-webhook"}

        # ==========================================
        # 本地 API 端点（供 Node.js OpenClaw 调用）
        # ==========================================

        @self.app.post("/api/local/trigger_demand")
        async def trigger_demand_local(request: Request):
            """本地接单接口 - 供 OpenClaw (Node.js) 调用"""
            # Token 验证
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing token")

            token = auth_header[7:]
            if token != self._local_token:
                print(f"[WARN] Token mismatch: received {token[:8]}... expected {self._local_token[:8]}...")
                raise HTTPException(status_code=403, detail="Invalid token - AgentSpace may have restarted, please retry")

            # ⚠️ [V1.6 优化] 强制 UTF-8 解码，避免中文乱码
            try:
                body_bytes = await request.body()
                body = json.loads(body_bytes.decode('utf-8'))
            except UnicodeDecodeError:
                # 回退到标准解析
                body = await request.json()
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

            user_id = body.get("user_id", "default_user")
            original_task = body.get("original_task", "")

            try:
                gateway = _gateway_instance or UniversalResourceGateway()
                demand_id = await gateway.publish_bounty_in_background(
                    error=ResourceMissingError(
                        resource_type=body.get("resource_type", "resource"),
                        description=body.get("description", "")
                    ),
                    original_task=original_task,
                    user_id=user_id
                )

                return {
                    "status": "published",
                    "demand_id": demand_id,
                    "original_task": original_task
                }
            except Exception as e:
                print(f"[ERROR] trigger_demand failed: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                return {
                    "status": "error",
                    "demand_id": None,
                    "original_task": original_task,
                    "error": f"{type(e).__name__}: {e}"
                }

        @self.app.delete("/api/local/demand/{demand_id}")
        async def cancel_demand(demand_id: str, request: Request):
            """用户主动取消需求"""
            # Token 验证
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer ") or auth_header[7:] != self._local_token:
                raise HTTPException(status_code=403, detail="Invalid token")

            task_ctx = self._task_cache.get_task(demand_id)

            if task_ctx:
                # 1. 删除本地缓存
                self._task_cache.delete_task(demand_id)

                # 2. 通知 Hub 删除云端需求
                asyncio.create_task(self._cancel_hub_demand(demand_id))

            return {"status": "cancelled", "demand_id": demand_id}

        # ==========================================
        # 原有端点
        # ==========================================

        @self.app.post("/api/webhook")
        async def receive_task(envelope: P2PTaskEnvelope, request: Request):
            jwt_payload = request.state.jwt_payload
            if envelope.sender_id != jwt_payload.get("seeker"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Sender ID does not match JWT seeker",
                )

            restored_context = restore_inbound_payload(envelope.task_context)

            if self.task_handler:
                try:
                    self.task_handler(envelope.task_type, restored_context)
                except Exception as exc:
                    print(f"Task handler error: {exc}")
            else:
                print("No task handler configured")

            return P2PAckResponse(acknowledged=True)

        @self.app.post("/api/p2p/address")
        async def p2p_address_request(request: P2PAddressRequest):
            inventory_file = Path.home() / ".agentspace" / "inventory_map.json"
            if not inventory_file.exists():
                return {"matched_files": [], "total_count": 0}

            inventory = json.loads(inventory_file.read_text(encoding="utf-8"))
            requested_tags = set(request.tags)
            matched_files = []

            for file_entry in inventory.get("files", []):
                file_tags = set(file_entry.get("entity_tags", []))
                if requested_tags & file_tags:
                    matched_files.append({
                        "filename": file_entry.get("filename"),
                        "static_url": file_entry.get("static_url"),
                        "size_bytes": file_entry.get("size_bytes"),
                    })

            return {"matched_files": matched_files, "total_count": len(matched_files)}

        @self.app.post("/api/webhook/delivery")
        async def receive_p2p_delivery(request: P2PDeliveryRequest):
            """
            Receive P2P delivery from other agents.

            This endpoint:
            1. Saves the delivered file to demand_inbox/
            2. Updates the task cache with delivery info
            3. Triggers the gateway's delivery event
            4. Sends wake-up notification to OpenClaw (cross-temporal)

            ⚠️ V1.5 更新：支持 base64 编码的文件内容（全球 HTTP 直邮）
            ⚠️ V1.6 更新：支持中文文件名（URL-safe 编码）
            """
            import urllib.parse

            whitelist = FileExtensionWhitelist()
            inbox_dir = Path.home() / ".agentspace" / "demand_inbox"
            inbox_dir.mkdir(parents=True, exist_ok=True)

            demand_id = request.demand_id

            for file_info in request.files:
                # ⚠️ [V1.6 新增] 支持中文文件名（URL 解码）
                filename = file_info.filename
                try:
                    # 尝试 URL 解码（处理 %E4%B8%AD%E6%96%87 这类编码）
                    filename = urllib.parse.unquote(filename)
                except Exception:
                    pass  # 解码失败，使用原始文件名

                allowed, error = whitelist.validate_file(filename)
                if not allowed:
                    raise HTTPException(status_code=403, detail=error)

                content = file_info.content

                # ⚠️ [V1.5 新增] 支持 base64 编码的文件内容
                if isinstance(content, str):
                    # 如果是字符串，尝试 base64 解码
                    import base64
                    try:
                        content = base64.b64decode(content)
                    except Exception:
                        # 解码失败，可能是原始字节字符串
                        content = content.encode("utf-8")
                elif not isinstance(content, bytes):
                    # 既不是 str 也不是 bytes，转换
                    content = str(content).encode("utf-8")

                file_path = inbox_dir / filename
                with open(file_path, "wb") as f:
                    f.write(content)

                # Save metadata
                meta_file = inbox_dir / f"task_{demand_id}_meta.json"
                meta_content = {
                    "demand_id": demand_id,
                    "filename": filename,
                    "file_path": str(file_path),
                    "received_at": datetime.utcnow().isoformat(),
                    "provider_id": request.provider_id,
                    "file_size": len(content),
                }
                with open(meta_file, "w", encoding="utf-8") as f:
                    json.dump(meta_content, f, indent=2, ensure_ascii=False)

                # Update task cache with delivery info
                task_ctx = self._task_cache.get_task(demand_id)
                if task_ctx:
                    self._task_cache.update_status(
                        demand_id,
                        "completed",
                        result_file=str(file_path),
                        provider_id=request.provider_id,
                    )

                # Trigger gateway delivery event
                if _gateway_instance:
                    _gateway_instance.trigger_delivery(demand_id, str(file_path))

                # Send wake-up notification to OpenClaw (cross-temporal)
                resource_type = task_ctx.resource_type if task_ctx else "resource"
                await self._bridge.notify_delivery(
                    demand_id=demand_id,
                    file_path=str(file_path),
                    provider_id=request.provider_id,
                    resource_type=resource_type,
                )

            return {"status": "received", "demand_id": demand_id}

        @self.app.post("/api/webhook/delivery/stream")
        async def receive_stream_delivery(
            demand_id: str = Form(...),
            provider_id: str = Form(""),
            file: UploadFile = File(...),
        ):
            """
            Strategy B: 分块流式接收端点

            接收 multipart/form-data 流式上传，
            原子化写入 .downloading 临时文件，完成后 rename。
            """

            whitelist = FileExtensionWhitelist()
            inbox_dir = Path.home() / ".agentspace" / "demand_inbox"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            from client_sdk.core.transfer_strategy import CHUNK_SIZE

            filename = file.filename or "unknown"
            allowed, error = whitelist.validate_file(filename)
            if not allowed:
                raise HTTPException(status_code=403, detail=error)

            # 原子化写入：先写 .downloading 临时文件
            dest_path = inbox_dir / filename
            tmp_path = dest_path.with_suffix(dest_path.suffix + ".downloading")

            try:
                import shutil
                with open(tmp_path, "wb") as f:
                    while chunk := await file.read(CHUNK_SIZE):
                        f.write(chunk)

                # 原子 rename
                if tmp_path.exists():
                    tmp_path.rename(dest_path)

                # 保存元数据
                meta_file = inbox_dir / f"task_{demand_id}_meta.json"
                meta_content = {
                    "demand_id": demand_id,
                    "filename": filename,
                    "file_path": str(dest_path),
                    "received_at": datetime.utcnow().isoformat(),
                    "provider_id": provider_id,
                    "file_size": dest_path.stat().st_size if dest_path.exists() else 0,
                    "transfer_mode": "stream",
                }
                with open(meta_file, "w", encoding="utf-8") as f:
                    json.dump(meta_content, f, indent=2, ensure_ascii=False)

                # 触发通知
                if _gateway_instance:
                    _gateway_instance.trigger_delivery(demand_id, str(dest_path))
                if self._bridge:
                    await self._bridge.notify_delivery(
                        demand_id=demand_id,
                        file_path=str(dest_path),
                        provider_id=provider_id,
                        resource_type=filename.rsplit(".", 1)[-1] if "." in filename else "",
                    )

                return {"status": "received", "demand_id": demand_id, "mode": "stream"}

            except Exception as e:
                # 清理脏数据
                if tmp_path.exists():
                    tmp_path.unlink()
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/webhook/delivery/link")
        async def receive_link_delivery(request: Request, background_tasks: BackgroundTasks):
            """
            Strategy C: R2 中转链接接收端点

            收到下载链接后立刻返回 202 Accepted（防超时死锁），
            后台异步下载 + AES 解密 + SHA-256 校验。
            """
            from client_sdk.core.transfer_strategy import CHUNK_SIZE, TransferProgress

            data = await request.json()
            demand_id = data.get("demand_id", "")
            download_url = data.get("download_url", "")
            filename = data.get("filename", "unknown")
            file_size = data.get("file_size", 0)
            checksum = data.get("checksum_sha256", "")
            aes_key_b64 = data.get("aes_key")
            encrypted = data.get("encrypted", False)

            if not download_url:
                raise HTTPException(status_code=400, detail="Missing download_url")

            async def _download_and_process():
                """后台任务：下载 + 解密 + 校验 + 通知"""
                from client_sdk.core.r2_storage import get_r2_storage

                inbox_dir = Path.home() / ".agentspace" / "demand_inbox"
                inbox_dir.mkdir(parents=True, exist_ok=True)

                dest_path = inbox_dir / filename
                tmp_path = dest_path.with_suffix(dest_path.suffix + ".downloading")

                try:
                    # 下载密文/原文件到临时路径
                    import httpx
                    progress = TransferProgress(max(file_size, 1), "R2 Download")

                    with httpx.stream("GET", download_url, timeout=600.0, follow_redirects=True) as resp:
                        resp.raise_for_status()
                        with open(tmp_path, "wb") as f:
                            for chunk in resp.iter_bytes(chunk_size=CHUNK_SIZE):
                                f.write(chunk)
                                progress.update(len(chunk))

                    # AES 解密
                    if encrypted and aes_key_b64:
                        import base64
                        from client_sdk.core.transfer_strategy import aes_key_to_bytes

                        aes_key_bytes = aes_key_to_bytes(aes_key_b64)
                        enc_path = tmp_path
                        dec_path = tmp_path.with_suffix(tmp_path.suffix + ".dec")

                        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                        with open(enc_path, "rb") as fin:
                            nonce = fin.read(12)  # 前 12 字节是 nonce
                            cipher = Cipher(
                                algorithms.AES(aes_key_bytes),
                                modes.CTR(nonce + (0).to_bytes(4, "big")),
                            )
                            decryptor = cipher.decryptor()
                            with open(dec_path, "wb") as fout:
                                while chunk := fin.read(CHUNK_SIZE):
                                    fout.write(decryptor.update(chunk))
                                final = decryptor.finalize()
                                if final:
                                    fout.write(final)

                        # 替换为解密后的文件
                        enc_path.unlink()
                        dec_path.rename(tmp_path)

                    # SHA-256 校验
                    if checksum:
                        h = hashlib.sha256()
                        with open(tmp_path, "rb") as f:
                            while chunk := f.read(CHUNK_SIZE):
                                h.update(chunk)
                        actual = h.hexdigest()
                        if actual != checksum:
                            print(f"[ERROR] SHA-256 mismatch: expected {checksum[:12]}..., got {actual[:12]}...")
                            tmp_path.unlink()
                            return
                        print(f"[OK] SHA-256 verified: {actual[:12]}...")

                    # 原子 rename
                    tmp_path.rename(dest_path)

                    # 保存元数据
                    meta_file = inbox_dir / f"task_{demand_id}_meta.json"
                    meta_content = {
                        "demand_id": demand_id,
                        "filename": filename,
                        "file_path": str(dest_path),
                        "received_at": datetime.utcnow().isoformat(),
                        "provider_id": data.get("provider_id", ""),
                        "file_size": dest_path.stat().st_size if dest_path.exists() else 0,
                        "transfer_mode": "r2_link",
                        "encrypted": encrypted,
                    }
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(meta_content, f, indent=2, ensure_ascii=False)

                    # 触发通知
                    if _gateway_instance:
                        _gateway_instance.trigger_delivery(demand_id, str(dest_path))
                    if self._bridge:
                        await self._bridge.notify_delivery(
                            demand_id=demand_id,
                            file_path=str(dest_path),
                            provider_id=data.get("provider_id", ""),
                            resource_type=filename.rsplit(".", 1)[-1] if "." in filename else "",
                        )

                    print(f"[OK] R2 delivery complete: {filename}")

                except Exception as e:
                    print(f"[ERROR] R2 download failed: {e}")
                    if tmp_path.exists():
                        tmp_path.unlink()

            background_tasks.add_task(_download_and_process)
            return {"status": "accepted", "demand_id": demand_id, "mode": "r2_link"}

        @self.app.post("/api/webhook/signal")
        async def receive_hub_signal(signal_data: dict):
            """接收云端 Hub 发来的控制信令"""

            if signal_data.get("action") == "wake_up_delivery":
                demand_id = signal_data["demand_id"]
                new_seeker_url = signal_data["new_seeker_url"]
                resource_type = signal_data.get("resource_type", "")
                description = signal_data.get("description", "")

                print(f"[信令] 收到云端通知：需求方已上线！正在向新地址补发文件...")

                # 1. 组装 matched_demand
                matched_demand_mock = {
                    "demand_id": demand_id,
                    "seeker_webhook_url": new_seeker_url,
                    "resource_type": resource_type,
                    "description": description,
                }

                # 2. 从本地找到要发送的文件
                supply_dir = Path.home() / ".agentspace" / "supply_provided"

                # 优先用信号中的 resource_type，退化到 demand_id 猜测
                if not resource_type and "_" in demand_id:
                    for part in demand_id.split("_"):
                        if part in ["csv", "pdf", "json", "txt", "xlsx", "md", "wav", "mp3", "mp4"]:
                            resource_type = part
                            break
                if not resource_type:
                    resource_type = "file"

                demand_info = {"resource_type": resource_type, "description": description}
                file_path = self._find_file_for_demand_safe(supply_dir, demand_info)

                if file_path:
                    # 3. 异步触发补发 + 投递确认
                    from ..sender import P2PSender
                    sender = P2PSender()

                    async def _deliver_and_confirm():
                        try:
                            success = await sender.deliver_file(
                                matched_demand=matched_demand_mock,
                                file_path=str(file_path),
                                provider_id="local_provider"
                            )
                            if success:
                                print(f"[信令] 投递成功: {file_path.name} -> {demand_id[:12]}...")
                                # 投递确认：通知 Hub 标记 demand 为 delivered
                                await self._confirm_delivery_to_hub(demand_id)
                            else:
                                print(f"[信令] 投递失败: {file_path.name} -> {demand_id[:12]}...")
                        except Exception as e:
                            print(f"[信令] 投递异常: {e}")

                    asyncio.create_task(_deliver_and_confirm())
                else:
                    print(f"[信令] 无法在 supply_provided/ 中找到匹配的 {resource_type} 文件，跳过自动发货")

            return {"status": "signal_received"}

    def _find_file_for_demand_safe(self, supply_dir: Path, demand_info: dict) -> Path | None:
        """
        安全的本地文件查找

        策略：先按后缀匹配，多个候选时用 description 关键词排序选最佳匹配。
        """
        if not supply_dir.exists():
            return None

        resource_type = demand_info.get("resource_type", "csv")
        description = demand_info.get("description", "")
        expected_ext = f".{resource_type}"

        candidates = [f for f in supply_dir.iterdir() if f.is_file() and f.suffix == expected_ext]

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # 多候选：用 description 中的关键词对文件名打分，选最佳
        if description:
            desc_lower = description.lower()
            best = max(candidates, key=lambda f: sum(1 for w in desc_lower.split() if w in f.name.lower()))
            return best

        return candidates[0]

    async def _confirm_delivery_to_hub(self, demand_id: str):
        """投递成功后通知 Hub 标记 demand 为 delivered"""
        import httpx
        url = f"{HUB_URL}{API_V1_PREFIX}/demand_status"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.put(url, json={
                    "demand_id": demand_id,
                    "status": "delivered",
                    "provider_id": "local_provider",
                })
                print(f"[信令] Delivery confirmed to Hub: HTTP {resp.status_code}")
        except Exception as e:
            print(f"[WARNING] Delivery confirmation failed: {e}")

    async def _cancel_hub_demand(self, demand_id: str):
        """通知 Hub 删除云端需求"""
        import httpx
        url = f"{HUB_URL}{API_V1_PREFIX}/pending_demands/{demand_id}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.delete(url)
        except Exception as e:
            print(f"[WARNING] 取消 Hub 需求失败: {e}")

    def run(self, host: str = "0.0.0.0"):
        import uvicorn
        uvicorn.run(self.app, host=host, port=self.port, log_level="info")

    async def run_async(self, host: str = "0.0.0.0"):
        import uvicorn
        config = uvicorn.Config(self.app, host=host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
