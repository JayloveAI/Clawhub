from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from client_sdk.core.entity_extractor import EntityExtractor

# Demand 描述中常见的指令性/状态性噪音词（不携带语义信息）
_DEMAND_NOISE_PATTERNS = [
    # 指令性动词短语
    r"请全网搜寻.*", r"尽量返回.*", r"并尽量.*",
    r"请.*搜寻.*", r"请.*检索.*", r"请.*获取.*",
    r"需要获取题为", r"需要.*全文", r"需要.*原文",
    r"请全网.*", r"全网搜寻.*",
    # 状态描述
    r"当前使用.*均失败", r"均失败.*",
    r"本地无缓存副本", r"本地.*缓存.*",
    r"fetch\s*failed", r"访问限制",
    # 方法/修饰描述
    r"使用\s*web_search.*检索",
    r"使用\s*browser.*访问",
    r"通过.*检索.*关键词",
    r"使用.*英文变体.*检索",
    r"检索该中文标题.*关键词.*均失败",
    r"检索.*相关关键词.*英文变体.*均失败",
    r"或可验证的原文来源链接",
    r"或.*来源链接",
    r"可验证的.*",
]


def _denoise_description(description: str) -> str:
    """
    去除 Demand 描述中的指令性/状态性噪音，保留核心语义。

    OpenClaw bridge 生成的描述包含大量指令文本：
    - "请全网搜寻..."
    - "当前使用 web_search 检索...均失败"
    - "本地无缓存副本"
    这些不携带需求语义，但会被 jieba 提取成噪音 tags。
    """
    import re
    cleaned = description
    for pattern in _DEMAND_NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    # 压缩多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned if cleaned else description


@dataclass
class DemandTicket:
    demand_id: str
    resource_type: str
    description: str
    tags: list[str]
    created_at: str
    seeker_id: str | None = None


class DemandGenerator:
    """Generate a demand ticket from resource-missing context."""

    def __init__(self):
        self._extractor = EntityExtractor()

    async def generate_ticket(self, context: dict) -> DemandTicket:
        resource_type = context.get("resource_type", "resource")
        description = context.get("description", "")
        seeker_id = context.get("seeker_id")

        # V1.6.5: 先去噪再提取 tags，减少指令性文本噪音
        cleaned_desc = _denoise_description(description)
        tags = self._extractor.extract_tags(cleaned_desc)
        if not tags:
            tags = [resource_type]

        return DemandTicket(
            demand_id=str(uuid.uuid4()),
            resource_type=resource_type,
            description=description,
            tags=tags,
            created_at=datetime.utcnow().isoformat(),
            seeker_id=seeker_id,
        )
