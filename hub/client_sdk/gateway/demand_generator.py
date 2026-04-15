from __future__ import annotations

import re
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
    # V1.6.6: 追加去噪 — 英文指令残留 + 标点碎片
    r"\bweb_search\b", r"\bfetch\s*failed\b", r"\bfetch\b",
    r"\bsearch\b", r"\bfailed\b",
    r"（[^）]*）",  # 括号内的状态描述如（fetch failed）
]

# 引号/书名号模式 — 提取其中的完整复合词
_QUOTED_CONTENT_PATTERNS = [
    r"《([^》]+)》",
    r"【([^】]+)】",
    r'"([^"]+)"',
    r'\u201c([^\u201d]+)\u201d',  # 中文引号""
]


def _denoise_description(description: str) -> str:
    """
    去除 Demand 描述中的指令性/状态性噪音，保留核心语义。

    V1.6.6 增强:
    - 去除括号内状态描述
    - 去除英文指令残留 (web_search, fetch failed 等)
    """
    cleaned = description
    for pattern in _DEMAND_NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    # 压缩多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned if cleaned else description


def _extract_compound_terms(description: str) -> list[str]:
    """
    从引号/书名号中提取完整复合词，避免被 jieba 切碎。

    例：'Claude Code Harness：从逆向工程到产品原理完整还原'
    → 保留为完整 tag（不被切成 claude, code, harness...）
    """
    compounds = []
    for pattern in _QUOTED_CONTENT_PATTERNS:
        for match in re.findall(pattern, description):
            match = match.strip()
            # 去掉末尾标点
            match = re.sub(r'[：:，,。.！!？?；;]+$', '', match).strip()
            if len(match) >= 2:
                compounds.append(match)
    return compounds


@dataclass
class DemandTicket:
    demand_id: str
    resource_type: str
    description: str
    tags: list[str]
    created_at: str
    seeker_id: str | None = None
    original_task: str = ""


class DemandGenerator:
    """Generate a demand ticket from resource-missing context."""

    def __init__(self):
        self._extractor = EntityExtractor()

    async def generate_ticket(self, context: dict) -> DemandTicket:
        resource_type = context.get("resource_type", "resource")
        description = context.get("description", "")
        seeker_id = context.get("seeker_id")

        # V1.6.8: 先更新 jieba 动态词库，让分词器认识新复合词
        from ..utils.tag_utils import update_compound_dict
        update_compound_dict(description)

        # V1.6.6: 三步提取策略
        # 1. 去噪
        cleaned_desc = _denoise_description(description)

        # 2. 从引号/书名号提取完整复合词（不被 jieba 切碎）
        compound_terms = _extract_compound_terms(description)

        # 3. 从去噪后的文本提取 token tags（jieba 已加载新词库）
        tags = self._extractor.extract_tags(cleaned_desc)

        # 4. 合并：复合词 + token tags，去重
        all_tags = list(dict.fromkeys(compound_terms + tags))
        if not all_tags:
            all_tags = [resource_type]

        return DemandTicket(
            demand_id=str(uuid.uuid4()),
            resource_type=resource_type,
            description=description,
            tags=all_tags,
            created_at=datetime.utcnow().isoformat(),
            seeker_id=seeker_id,
            original_task=context.get("original_task", ""),
        )
