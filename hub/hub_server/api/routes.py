"""
Hub API Routes - 撮合中枢路由实现
=================================
实现 /publish, /search, /task_completed, /status 四个核心端点

V1.5 Updates:
- Added PATCH /status endpoint for live status updates
- Enhanced /search with node_status filtering

V1.6 Updates:
- Added timeout handling for /search
- Added GET /pending_demands query endpoint
- Supply endpoint now returns match_token for P2P communication
"""
import asyncio
import numpy as np
from fastapi import APIRouter, HTTPException, status
from datetime import datetime
from hub_server.api.contracts import (
    PublishRequest, PublishResponse,
    SearchRequest, SearchResponse, MatchResult,
    TaskCompletedRequest, TaskCompletedResponse,
    ErrorResponse,
    # V1.5: New contracts
    StatusUpdateRequest, StatusUpdateResponse,
)
from hub_server.services.jwt_service import jwt_service
from hub_server.services.match_service import embedding_service


def cosine_similarity(vec_a, vec_b):
    """计算余弦相似度"""
    a, b = np.array(vec_a), np.array(vec_b)
    norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

router = APIRouter()

# V1.5: Import MatchService for status updates
from hub_server.services.match_service import MatchService


# ============================================================================
# 状态存储（开发阶段使用，生产环境替换为数据库）
# ============================================================================
# TODO: 替换为 PostgreSQL + pgvector
_agent_store = {}
_task_completion_store = set()


# ============================================================================
# ① 发布/更新名片
# ============================================================================

@router.post("/publish", response_model=PublishResponse, status_code=status.HTTP_200_OK)
async def publish_agent_card(request: PublishRequest):
    """
    发布或更新 Agent 名片
    
    流程：
    1. 接收 identity.md 内容（纯文本）
    2. 调用 OpenAI API 进行向量化（服务端处理）
    3. 存入数据库
    4. 返回注册结果
    
    关键：向量化在服务端完成，客户端无需配置 API Key
    """
    try:
        # 向量化处理（服务端负责）
        description_vector = await embedding_service.get_embedding(request.description)
        
        # 存储记录
        is_update = request.agent_id in _agent_store
        
        _agent_store[request.agent_id] = {
            "agent_id": request.agent_id,
            "domain": request.domain,
            "intent_type": request.intent_type,
            "contact_endpoint": request.contact_endpoint,
            "description": request.description,
            "description_vector": description_vector,
            "tasks_requested": 0,
            "tasks_provided": 0,
            "last_active": datetime.utcnow(),
            "created_at": datetime.utcnow(),
            # V1.5: Add default status fields
            "node_status": "active",
            "live_broadcast": None,
            "status_updated_at": datetime.utcnow()
        }
        
        return PublishResponse(
            agent_id=request.agent_id,
            status="updated" if is_update else "registered",
            registered_at=datetime.utcnow()
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"发布名片失败: {str(e)}"
        )


# ============================================================================
# ② 寻找协同资源
# ============================================================================

@router.post("/search", response_model=SearchResponse)
async def search_collaborators(request: SearchRequest):
    """
    寻找协同资源

    流程：
    1. 向量化查询文本
    2. 混合检索：domain 过滤 + 向量相似度排序
    3. 签发 JWT 门票
    4. 返回 Top 3 匹配结果
    """
    try:
        # 向量化查询（添加超时处理）
        try:
            query_vector = await asyncio.wait_for(
                embedding_service.get_embedding(request.query),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Embedding service timeout, please try again later"
            )
        
        # TODO: 实现真实的向量相似度检索
        # 这里是简化版的开发实现
        
        matches = []

        # V1.5: 筛选条件
        # 1. intent_type 必须是 'bid' (服务提供方)
        # 2. node_status 必须是 'active' (可用状态)
        candidates = [
            agent for agent in _agent_store.values()
            if agent["intent_type"] == "bid"
            and agent.get("node_status", "offline") == "active"  # V1.5: Filter by node_status
        ]
        
        # 如果指定了 domain，先过滤
        if request.domain:
            candidates = [
                agent for agent in candidates
                if agent["domain"] == request.domain
            ]
        
        # 计算余弦相似度并排序
        scored_candidates = []
        for agent in candidates:
            agent_vector = agent["description_vector"]
            similarity = cosine_similarity(query_vector, agent_vector)
            scored_candidates.append((similarity, agent))
        
        # 按相似度降序排序，取 Top 3
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        
        # 签发 JWT 门票
        for similarity, agent in scored_candidates[:3]:
            # 获取需求方 ID（从 session 或 token 中获取）
            # 这里简化为使用 agent_id 作为 seeker
            seeker_id = "current_user"  # TODO: 从认证中获取
            
            jwt_token = jwt_service.issue_match_token(
                seeker_id=seeker_id,
                provider_id=agent["agent_id"],
                seeker_endpoint=""  # TODO: 从请求中获取
            )
            
            matches.append(MatchResult(
                agent_id=agent["agent_id"],
                contact_endpoint=agent["contact_endpoint"],
                match_token=jwt_token,
                tasks_provided=agent["tasks_provided"]
            ))
        
        return SearchResponse(
            matches=matches,
            total_searched=len(candidates)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"搜索失败: {str(e)}"
        )


# ============================================================================
# ③ 任务完工上报
# ============================================================================

@router.post("/task_completed", response_model=TaskCompletedResponse)
async def report_task_completed(request: TaskCompletedRequest):
    """
    任务完工上报 - 信用记账
    
    流程：
    1. 验证 JWT 门票
    2. 提取 seeker 和 provider ID
    3. 使用数据库事务同时更新双方的计数
    4. 防重：同一门票只能上报一次
    """
    try:
        # 验证门票
        payload = jwt_service.verify_match_token(request.match_token)
        
        seeker_id = payload["seeker"]
        provider_id = payload["provider"]
        
        # 防重检查
        token_hash = jwt_service.get_token_hash(request.match_token)
        if token_hash in _task_completion_store:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该任务已完成上报，请勿重复提交"
            )
        
        # 获取 Agent 记录
        if seeker_id not in _agent_store or provider_id not in _agent_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent 不存在"
            )
        
        # 更新信用账本（事务）
        _agent_store[seeker_id]["tasks_requested"] += 1
        _agent_store[provider_id]["tasks_provided"] += 1
        
        # 记录已完成的任务
        _task_completion_store.add(token_hash)
        
        return TaskCompletedResponse(
            success=True,
            message="任务完成记录成功",
            requester_tasks=_agent_store[seeker_id]["tasks_requested"],
            provider_tasks=_agent_store[provider_id]["tasks_provided"]
        )
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上报失败: {str(e)}"
        )


# ============================================================================
# V1.5: ④ Live Status Update (新增)
# ============================================================================

@router.patch("/agents/{agent_id}/status", response_model=StatusUpdateResponse, status_code=status.HTTP_200_OK)
async def update_agent_status(agent_id: str, request: StatusUpdateRequest):
    """
    V1.5 更新 Agent 实时状态（支持路径参数和双向事件驱动）
    """
    try:
        if agent_id not in _agent_store:
            raise ValueError(f"Agent {agent_id} not found")

        # 更新 Agent 状态
        _agent_store[agent_id]["node_status"] = request.node_status
        _agent_store[agent_id]["live_broadcast"] = request.live_broadcast
        _agent_store[agent_id]["webhook_url"] = request.webhook_url
        _agent_store[agent_id]["status_updated_at"] = datetime.utcnow()

        # 触发反向撞库（向量匹配）
        new_tags = request.tags or []
        new_vector = await embedding_service.get_embedding(request.live_broadcast or "")

        # 双向事件驱动检查
        delivery_tasks = []

        if request.node_status == "active" and request.webhook_url:
            # TODO: 添加数据库查询和事件触发逻辑
            pass

        return StatusUpdateResponse(
            agent_id=agent_id,
            node_status=request.node_status,
            live_broadcast=request.live_broadcast,
            status_updated_at=datetime.utcnow(),
            vector_regenerated=True,
            delivery_tasks=delivery_tasks
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"状态更新失败: {str(e)}"
        )

# ---------------------------------------------------------------------------
# V1.5: Pending Demands (best-effort in-memory store)
# ---------------------------------------------------------------------------
_pending_demands = []


@router.post("/pending_demands")
async def create_pending_demand(payload: dict):
    """Create pending demand and store in repository for matching."""
    from hub_server.services.lite_repository import get_repository, PendingDemand
    from hub_server.services.match_service import embedding_service
    from datetime import datetime

    # Generate vector from tags/description for semantic matching
    tags = payload.get("tags", [])
    description = payload.get("description", "")

    # Extract clean tags from description if tags are empty or noisy
    from hub_server.utils_tag_utils import extract_and_clean, clean_extract_tags
    extracted = extract_and_clean(description) if description else []
    tags = clean_extract_tags(tags) if tags else []
    # Merge: user-provided tags + extracted tags, dedup
    all_tags = sorted(set(tags + extracted))
    if all_tags:
        tags = all_tags

    # Generate semantic vector from clean tags (not raw noisy description)
    tag_text = " ".join(tags) if tags else description
    try:
        demand_vector = await asyncio.wait_for(
            embedding_service.get_embedding(tag_text),
            timeout=15.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service timeout, please try again later"
        )

    # Store in repository for matching
    repo = get_repository()
    demand = PendingDemand(
        demand_id=payload.get("demand_id"),
        resource_type=payload.get("resource_type", ""),
        description=description,
        tags=tags,
        demand_vector=demand_vector,
        seeker_id=payload.get("seeker_id"),
        seeker_webhook_url=payload.get("seeker_webhook_url", ""),
        created_at=datetime.utcnow().isoformat(),
        status="pending"
    )
    repo.add_demand(demand)

    # Also keep in memory for backward compatibility
    _pending_demands.append(payload)
    return {"status": "queued", "demand_id": payload.get("demand_id")}


@router.get("/pending_demands")
async def list_pending_demands(seeker_id: str = None):
    """
    V1.6: 查询当前挂起的需求

    Args:
        seeker_id: 可选，筛选特定需求方的需求

    Returns:
        挂起的需求列表
    """
    from hub_server.services.lite_repository import get_repository

    repo = get_repository()
    demands = repo.get_all_pending()

    if seeker_id:
        demands = [d for d in demands if d.seeker_id == seeker_id]

    return {
        "total": len(demands),
        "demands": [
            {
                "demand_id": d.demand_id,
                "resource_type": d.resource_type,
                "description": d.description,
                "tags": d.tags,
                "seeker_id": d.seeker_id,
                "status": d.status,
                "created_at": d.created_at
            }
            for d in demands
        ]
    }


# ---------------------------------------------------------------------------
# V1.5: Supply Announcement (需求驱动的反向匹配)
# ---------------------------------------------------------------------------

@router.post("/agents/{agent_id}/supply")
async def handle_supply_announcement(agent_id: str, payload: dict):
    """
    Handle supply announcement from provider agent.

    V1.6 Update: Now returns match_token for P2P communication!

    This endpoint:
    1. Receives supply information (file, tags, vector)
    2. Queries pending demands for matches
    3. Returns matching demands with match_token to provider

    Provider will then deliver files directly to seekers using the match_token.
    """
    from hub_server.services.lite_repository import get_repository
    from hub_server.services.match_service import embedding_service

    repo = get_repository()
    tags = payload.get("tags", [])
    description = payload.get("description", "")
    supply_vector = payload.get("supply_vector")

    # Extract clean tags from description if tags are sparse
    from hub_server.utils_tag_utils import extract_and_clean, clean_extract_tags
    cleaned_tags = clean_extract_tags(tags) if tags else []
    extracted = extract_and_clean(description) if description else []
    tags = sorted(set(cleaned_tags + extracted)) or tags

    # 🔍 Debug logging
    print(f"[DEBUG-HUB] ========== Supply Announcement ==========")
    print(f"[DEBUG-HUB] From agent_id: {agent_id}")
    print(f"[DEBUG-HUB] Tags: {tags}")
    print(f"[DEBUG-HUB] Supply vector present: {supply_vector is not None}")

    # ⚠️ 如果 SDK 没传向量，用 tags 生成真实的语义向量
    if not supply_vector:
        tag_text = " ".join(tags)
        try:
            supply_vector = await asyncio.wait_for(
                embedding_service.get_embedding(tag_text),
                timeout=15.0
            )
            print(f"[DEBUG] Generated vector from tags: '{tag_text}'")
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Embedding service timeout, please try again later"
            )

    # 🔍 Query all pending demands for debugging
    all_demands = repo.get_all_pending()
    print(f"[DEBUG-HUB] Total pending demands in DB: {len(all_demands)}")
    for d in all_demands:
        print(f"[DEBUG-HUB]   - demand_id={d.demand_id}, tags={d.tags}, seeker_id={d.seeker_id}, status={d.status}")

    # 查找匹配需求
    matched_demands = repo.find_matches(
        new_tags=tags,
        new_vector=supply_vector,
        threshold=0.7
    )

    print(f"[DEBUG-HUB] Matched demands count: {len(matched_demands)}")
    for m in matched_demands:
        print(f"[DEBUG-HUB]   ✓ Matched: demand_id={m.demand_id}, resource_type={m.resource_type}, webhook={m.seeker_webhook_url}")
    print(f"[DEBUG-HUB] ========================================")

    # 格式化返回结果 - V1.6: 添加 match_token
    results = []
    for demand in matched_demands:
        # 🔑 V1.6: 为每个匹配签发 match_token
        match_token = jwt_service.issue_match_token(
            seeker_id=demand.seeker_id or "unknown",
            provider_id=agent_id,
            seeker_endpoint=demand.seeker_webhook_url or ""
        )

        results.append({
            "demand_id": demand.demand_id,
            "resource_type": demand.resource_type,
            "description": demand.description,
            "tags": demand.tags,
            "seeker_webhook_url": demand.seeker_webhook_url,
            "match_token": match_token  # ← V1.6 新增！
        })

    return {"matched_demands": results}


# ---------------------------------------------------------------------------
# V1.6: Delete Pending Demand (用户主动取消)
# ---------------------------------------------------------------------------

@router.delete("/pending_demands/{demand_id}")
async def delete_pending_demand(demand_id: str):
    """
    V1.6: 删除云端挂起的需求

    当用户在本地取消需求时，Node.js 调用此端点删除云端记录，
    避免 Provider 白白发货。
    """
    from hub_server.services.lite_repository import get_repository

    repo = get_repository()
    deleted = repo.delete_demand(demand_id)

    if deleted:
        # 同时从内存中删除
        global _pending_demands
        _pending_demands = [d for d in _pending_demands if d.get("demand_id") != demand_id]
        return {"status": "deleted", "demand_id": demand_id}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Demand {demand_id} not found"
        )
