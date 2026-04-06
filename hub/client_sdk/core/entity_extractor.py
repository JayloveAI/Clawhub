# -*- coding: utf-8 -*-
"""
Entity Extractor - 文件名/描述文本标签提取器

V2.0 重构：
- 使用 jieba 统一中英文分词，替代正则暴力切分
- 删除硬编码金融领域词，通过分词 + 停用词自然过滤
- 统一调用 extract_multilingual_tokens() 实现跨语种匹配
"""
from __future__ import annotations

import re
from client_sdk.utils.tag_utils import (
    clean_extract_tags,
    extract_multilingual_tokens,
)


class EntityExtractor:
    """
    Lightweight entity tag extractor for filenames and description text.

    Design:
    - No LLM usage.
    - jieba 统一分词 + 双语停用词过滤.
    - Supports both filenames and description text.
    - V2.0: Cross-language (Chinese + English) token extraction.
    """

    # 领域关键词映射（用于分类标签，不用于提取）
    DOMAIN_KEYWORDS = {
        "finance": ["股票", "基金", "债券", "期货", "回测", "k线", "a股", "港股", "美股"],
        "education": ["教材", "习题", "课程", "k12", "试卷", "学习", "考试"],
        "coding": ["代码", "api", "sdk", "库", "框架", "开发", "程序"],
    }

    # 正则模式（用于提取特定格式的实体，如股票代码、日期）
    ENTITY_PATTERNS = {
        "stock_code": r"\b\d{6}\.(?:SH|SZ)\b",
        "date_range": r"\b\d{4}-\d{2}-\d{2}\b",
        "chinese_stock": r"(?:A股|港股|美股|中概股)",
        "keywords": r"(?:宏观经济|美联储|央行|通胀|GDP)",
    }

    # 中文话题模式（书名号、方括号、引号）
    CHINESE_TOPIC_PATTERNS = [
        r"《([^》]+)》",
        r"【([^】]+)】",
        r'"([^"]+)"',
    ]

    def extract_tags(self, filename_or_description: str, content_preview: str = "") -> list[str]:
        """
        Extract entity tags from filename or description text.

        Args:
            filename_or_description: 文件名或描述文本
            content_preview: 可选的内容预览

        Returns:
            清洗后的标签列表
        """
        raw_tags = set()
        text = filename_or_description

        # 统一使用 jieba 分词提取
        combined_text = f"{filename_or_description} {content_preview}"
        raw_tags.update(extract_multilingual_tokens(filename_or_description))

        # 判断是文件名还是描述文本
        is_description = " " in text or len(re.findall(r"[\u4e00-\u9fff]", text)) > 3

        if is_description:
            raw_tags.update(self._extract_from_description(text))
        else:
            raw_tags.update(self._extract_from_filename(text))

        # 从内容预览提取
        if content_preview:
            raw_tags.update(self._extract_from_text(content_preview))

        # 域关键词匹配（仅添加域标签）
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            if any(kw in combined_text.lower() for kw in keywords):
                raw_tags.add(domain)

        # 使用全局 tag_utils 清洗
        return clean_extract_tags(list(raw_tags))

    def _extract_from_filename(self, filename: str) -> set[str]:
        """从文件名提取标签"""
        tags = set()
        base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

        # 统一分词提取（替代正则中文切分）
        tags.update(extract_multilingual_tokens(base_name))

        # 提取文件扩展名
        if "." in filename:
            file_ext = filename.rsplit(".", 1)[-1].lower()
            tags.add(file_ext)

        # 从正则模式提取（股票代码、日期等格式化实体）
        for pattern in self.ENTITY_PATTERNS.values():
            for match in re.findall(pattern, filename, re.IGNORECASE):
                if isinstance(match, tuple):
                    match = " ".join(part for part in match if part)
                if match:
                    tags.add(str(match).lower())

        return tags

    def _extract_from_description(self, description: str) -> set[str]:
        """从描述文本提取标签

        V1.6.6: 引号/书名号内容同时保留完整短语 + tokenized 版本，
        确保复合词（如"逆向工程"）不被 jieba 切碎后丢失。
        """
        tags = set()

        # 1. 提取书名号、方括号、引号中的内容
        for pattern in self.CHINESE_TOPIC_PATTERNS:
            matches = re.findall(pattern, description)
            for match in matches:
                match = match.strip()
                # 去掉末尾标点
                match_clean = re.sub(r'[：:，,。.！!？?；;]+$', '', match).strip()
                # 保留完整复合词（如果长度 >= 2 且含中文或英文词）
                if len(match_clean) >= 2 and re.search(r'[a-zA-Z\u4e00-\u9fff]', match_clean):
                    tags.add(match_clean.lower())
                # 同时也做 tokenized 提取
                tags.update(extract_multilingual_tokens(match))

        # 2. 统一分词提取
        tags.update(extract_multilingual_tokens(description))

        return tags

    def _extract_from_phrase(self, phrase: str) -> set[str]:
        """从短语中提取关键词"""
        return set(extract_multilingual_tokens(phrase))

    def _extract_from_text(self, text: str) -> set[str]:
        """从文本中提取特定格式实体"""
        entities = set()

        # 格式化实体（股票代码、日期等）
        for pattern in self.ENTITY_PATTERNS.values():
            for match in re.findall(pattern, text, re.IGNORECASE):
                if isinstance(match, tuple):
                    match = " ".join(part for part in match if part)
                if match:
                    entities.add(str(match).lower())

        # 统一分词
        entities.update(extract_multilingual_tokens(text))

        return entities
