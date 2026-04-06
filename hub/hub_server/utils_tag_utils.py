# -*- coding: utf-8 -*-
"""
全局通用 关键词/Tag 清洗工具
适用：中英文、日志、系统、SDK、OpenClaw、AgentSpace 全场景
功能：jieba 统一分词 + 双语停用词 + 小写归一化，支持跨语种匹配

V2.0 重构：
- 引入 jieba 统一中英文分词，替代正则暴力切分
- 双语停用词（中文 200+ / 英文 50+）统一过滤
- 小写归一化，解决跨语种大小写不匹配
- extract_multilingual_tokens() 核心函数替代所有正则提取
"""

import re
from typing import Optional

# ======================
# 【jieba 懒加载】
# ======================
_jieba_initialized = False


def _ensure_jieba():
    """懒加载 jieba，首次调用时初始化（~0.5s），后续调用无开销"""
    global _jieba_initialized
    if not _jieba_initialized:
        import jieba
        jieba.setLogLevel(20)  # WARNING 级别，抑制 verbose 日志
        _jieba_initialized = True


# ======================
# 【英文停用词】
# ======================
EN_STOPWORDS = {
    # 冠词/代词/介词
    "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "can",
    "with", "from", "by", "as", "not", "no", "so", "if", "than",
    "this", "that", "these", "those", "it", "its", "we", "you",
    "they", "them", "our", "your", "their", "my", "his", "her",
    # 无区分度常见词
    "content", "data", "info", "information", "need", "using",
    "just", "also", "very", "about", "into", "over", "then",
    "when", "where", "how", "what", "which", "who", "why",
    "there", "here", "all", "each", "every", "both", "any",
    "few", "more", "most", "other", "some", "such", "only",
    "own", "same", "new", "old", "first", "last", "next",
    "get", "got", "make", "made", "like", "well", "back",
    "even", "still", "way", "take", "come", "know", "see",
    "use", "find", "give", "tell", "try", "ask", "put",
    # HTTP/错误相关
    "error", "fail", "failed", "exception", "null", "none", "undefined",
    "400", "401", "402", "403", "404", "500", "501", "502", "503", "504",
}


# ======================
# 【中文停用词】200+ 条
# ======================
CHINESE_STOPWORDS = {
    # 助词/语气词
    "的", "了", "在", "是", "我", "你", "他", "它",
    "这", "那", "此", "该", "都", "就", "会", "可",
    "也", "而", "及", "与", "或", "但", "却", "又",
    "吗", "呢", "吧", "啊", "呀", "哦", "嗯", "哈",
    "啦", "嘛", "着", "过", "地", "得", "把", "被",
    "让", "给", "对", "比", "从", "向", "往", "到",

    # 代词/指示词
    "我们", "你们", "他们", "自己", "什么", "怎么",
    "哪里", "为什么", "这个", "那个", "这些", "那些",
    "这样", "那样", "怎样", "这么", "那么", "一些",
    "一个", "所有", "每个", "各种", "某些", "任何",

    # 连词/副词
    "如果", "因为", "所以", "虽然", "但是", "然而",
    "不过", "而且", "并且", "以及", "还是", "或者",
    "既然", "即使", "尽管", "不但", "不仅", "而是",
    "非常", "很", "最", "更", "太", "真的", "确实",
    "其实", "仍然", "已经", "正在", "将要", "刚刚",
    "一直", "总是", "从来", "往往", "逐渐", "暂时",

    # 无区分度动词
    "需要", "获取", "进行", "通过", "使用", "根据",
    "可以", "应该", "必须", "可能", "能够", "想要",
    "希望", "开始", "继续", "完成", "结束", "停止",
    "保持", "使得", "导致", "包括", "包含", "属于",
    "作为", "称为", "表示", "说明", "显示", "提供",
    "支持", "实现", "处理", "解决", "确定", "认为",
    "发现", "存在", "出现", "发生", "形成", "产生",
    "建立", "提出", "分析", "了解", "知道", "看到",
    "当前", "目前", "现在", "时候", "今天", "昨天",
    "明天", "今年", "去年", "近年", "近年来", "以来",

    # 无区分度名词
    "内容", "情况", "问题", "方面", "方法", "结果",
    "过程", "方式", "时候", "时间", "地方", "东西",
    "样子", "办法", "部分", "整体", "全文", "整篇",
    "完整版", "完整", "版本", "报告", "内容", "信息",
    "整", "篇", "完", "全", "文", "本", "篇", "篇",
    "这篇", "这篇", "题目", "标题", "题为",

    # 量词/介词
    "个", "只", "条", "件", "种", "类", "次", "位",
    "份", "项", "册", "套", "组", "批", "堆", "点",

    # 无意义短语组合（仅限通用指令性短语，不包含具体内容标题）
    "均失败", "当前使用", "需要获取题为", "本地无缓存",
    "缓存页", "转载页或作者发布页", "需要获取题为",
    "全网搜寻", "尽量返回", "可访问全文",

    # Demand 侧噪音词（指令性/状态性/搜索相关，无区分度）
    "失败", "本地", "链接", "副本", "尽量", "访问", "返回",
    "来源", "搜寻", "检索", "相关", "缓存", "转载", "镜像",
    "可验证", "作者", "关键词", "变体", "发布页", "原文",
    "原题", "题目为", "名为", "求", "找", "想要", "有没有",
    "求购", "悬赏", "求助", "跪求", "哪位", "谁能",
}


# ======================
# 【全局黑名单】统一中英文过滤入口
# ======================
GLOBAL_BLACKLIST = EN_STOPWORDS | CHINESE_STOPWORDS


# ======================
# 【全局白名单】仅保留系统/技术词
# ======================
GLOBAL_WHITELIST = {
    # 核心系统
    "agentai", "openclaw", "agentspace", "hub", "bridge",
    "sdk", "api", "llm", "ui", "web", "server", "client",
    "plugin", "plugins", "tool", "tools", "service",

    # 技术通用
    "npm", "pip", "whl", "tgz", "json", "sqlite", "db",
    "http", "https", "rest", "rpc", "config", "env",
    "install", "deploy", "package", "packages", "script",

    # 业务功能
    "search", "match", "demand", "pending", "matched",
    "trigger", "callback", "route", "dispatch", "task",
    "session", "token", "user", "admin", "scope",

    # AI 通用
    "prompt", "agent", "model", "embedding", "context",
    "gpt", "claude", "gemini", "llama", "mistral",

    # 基础组件
    "system", "log", "file", "path", "network",
    "local", "global", "online", "offline", "sync", "async",

    # 文件格式
    "csv", "xlsx", "pdf", "txt", "md", "py", "js", "html",
}


# ======================
# 核心函数：统一多语种分词提取
# ======================
def extract_multilingual_tokens(text: str) -> list[str]:
    """
    统一中英文分词提取，替代所有正则暴力切分。

    - 中文：jieba 分词（词边界准确，非暴力切片）
    - 英文：jieba 按空格切分 + 小写归一化
    - 统一过滤：长度 2-15、双语停用词、纯数字/标点

    Args:
        text: 输入文本（中文/英文/混合均可）

    Returns:
        去重后的有效关键词列表

    示例:
        >>> extract_multilingual_tokens("需要获取题为Claude Code Harness的全文内容")
        ['claude', 'code', 'harness']
        >>> extract_multilingual_tokens("华创证券动力煤研究报告")
        ['华创', '证券', '动力煤', '研究', '报告']
    """
    if not isinstance(text, str) or not text.strip():
        return []

    try:
        _ensure_jieba()
        import jieba

        text_lower = text.lower()
        tokens = jieba.lcut(text_lower)

        cleaned = []
        for t in tokens:
            t = t.strip()
            if not t:
                continue

            # 长度过滤：统一 2-15（中文 2-6 字/英文 2-15 字符）
            if len(t) < 2 or len(t) > 15:
                continue

            # 黑名单过滤（含双语停用词）
            if t in GLOBAL_BLACKLIST:
                continue

            # 过滤纯数字
            if t.isdigit():
                continue

            # 过滤纯标点/符号
            if all(c in '.,!?;:()[]\'"\\-=_~/@#$%^&*+={}<>|`~' for c in t):
                continue

            # 必须含字母或中文字符（过滤纯符号混合）
            if not re.search(r'[a-z\u4e00-\u9fff]', t):
                continue

            cleaned.append(t)

        # 去重 + 排序
        return sorted(list(set(cleaned)))

    except Exception:
        # 兜底：SDK 不崩溃，返回空列表
        return []


# ======================
# 核心清洗函数（全场景通用）
# ======================
def clean_extract_tags(tags: list) -> list:
    """
    统一清洗 Tag / 关键词

    :param tags: 原始标签列表
    :return: 干净、去重、有序的关键词列表

    示例:
        >>> clean_extract_tags(['agentai', 'openclaw', '的行业临界点'])
        ['agentai', 'openclaw']
    """
    if not tags:
        return []

    # 预处理：去空 + 去空格 + 小写
    tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
    valid_tags = []

    for tag in tags:
        # 1. 黑名单直接跳过
        if tag in GLOBAL_BLACKLIST:
            continue

        # 2. 白名单强制保留
        if tag in GLOBAL_WHITELIST:
            valid_tags.append(tag)
            continue

        # 3. 长度过滤
        tag_len = len(tag)
        if tag_len < 2 or tag_len > 20:
            continue

        # 4. 英文关键词：字母/数字/下划线/短横线 → 保留
        if tag.isascii() and all(c.isalnum() or c in "_-" for c in tag):
            valid_tags.append(tag)
            continue

        # 5. 中文过滤：黑名单中的字 → 跳过
        invalid_chars = ["的", "这", "那", "我", "你", "他", "整", "篇", "完", "全", "文"]
        if any(char in tag for char in invalid_chars):
            continue

        # 6. 合法中文关键词
        valid_tags.append(tag)

    # 去重 + 排序
    valid_tags = sorted(list(set(valid_tags)))
    return valid_tags


# ======================
# 便捷函数：从文本直接提取并清洗
# ======================
def extract_and_clean(text: str, min_word_len: int = 3) -> list:
    """
    从文本中提取关键词并清洗（使用 jieba 统一分词）

    :param text: 输入文本
    :param min_word_len: 英文单词最小长度
    :return: 清洗后的关键词列表

    示例:
        >>> extract_and_clean("需要《Claude Code Harness》报告的完整内容")
        ['claude', 'code', 'harness']
    """
    if not text:
        return []

    raw_tags = set()

    # 1. 提取书名号/方括号/引号中的特殊内容
    special_patterns = [
        r"《([^》]+)》",
        r"【([^】]+)】",
        r'"([^"]+)"',
    ]
    for pattern in special_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            raw_tags.update(extract_multilingual_tokens(match))

    # 2. 对整体文本进行统一分词提取
    raw_tags.update(extract_multilingual_tokens(text))

    # 3. 最终清洗
    return clean_extract_tags(list(raw_tags))


# ======================
# 模块测试
# ======================
if __name__ == "__main__":
    print("=" * 60)
    print("Tag Utils V2.0 测试 — jieba 统一分词 + 双语停用词")
    print("=" * 60)

    # 测试 1: 垃圾标签回归
    garbage_tests = [
        "均失败", "当前使用", "需要获取题为",
        "整全文内容", "这篇报告的完",
    ]
    print("\n--- 垃圾标签回归测试 ---")
    for text in garbage_tests:
        result = extract_multilingual_tokens(text)
        status = "✗ 漏过" if result else "✓ 过滤"
        print(f"  {status}: '{text}' → {result}")

    # 测试 2: 有意义中文
    print("\n--- 有意义中文提取 ---")
    cases = [
        "华创证券动力煤研究报告",
        "Claude Code Harness 逆向工程分析",
        "CLAUDE Code HARNESS",
    ]
    for text in cases:
        result = extract_multilingual_tokens(text)
        print(f"  '{text}' → {result}")

    # 测试 3: extract_and_clean
    print("\n--- extract_and_clean 测试 ---")
    desc = '需要获取题为"Claude Code Harness：从逆向工程到产品原理完整还原"的全文内容...'
    result = extract_and_clean(desc)
    print(f"  输入: {desc}")
    print(f"  输出: {result}")

    # 测试 4: clean_extract_tags 兼容性
    print("\n--- clean_extract_tags 兼容性 ---")
    tag_cases = [
        ['agentai', 'openclaw', '的行业临界点', '整全文内容', '这篇报告的完'],
        ['401', 'error', 'agentspace', 'sdk', 'api'],
        ['需要', '获取', '用户', '数据', 'file'],
    ]
    for raw in tag_cases:
        clean = clean_extract_tags(raw)
        print(f"  {raw} → {clean}")
