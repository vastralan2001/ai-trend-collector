from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from src.core.models import TrendItem

# 数据源 → 中文分类
SOURCE_CATEGORY = {
    "product_hunt": "AI产品",
    "github_trends": "开源项目",
    "arxiv_ai": "论文",
    "huggingface_papers": "论文",
}

# Kimi / 月之暗面 相关关键词
KIMI_KEYWORDS = [
    "kimi", "moonshot", "月之暗面", "长文本", "long context",
    "中文大模型", "chinese llm", "多模态", "multimodal",
    "agent", "智能体", "推理模型", "reasoning",
]

# AIHues 相关关键词（出海增长工具、AI 工具导航、独立开发者）
AIHUES_KEYWORDS = [
    "ai工具", "ai工具导航", "出海", "indie hacker", "独立开发者",
    "增长工具", "growth tools", "saas", "productivity", "效率工具",
    "design tools", "设计工具", "开源项目", "open source",
    "内容生成", "seo", "marketing", "automation",
]


def normalize(text: str) -> str:
    return text.lower().replace("-", " ").replace("_", " ")


def count_keyword_matches(text: str, keywords: list[str]) -> int:
    text_norm = normalize(text)
    return sum(1 for kw in keywords if normalize(kw) in text_norm)


def score_relevance(item: TrendItem) -> float:
    """计算与 Kimi/AIHues 的相关度，返回 0-1 之间的分数"""
    searchable_text = " ".join([
        item.title,
        item.summary,
        item.author or "",
        " ".join(item.tags),
        " ".join(f"{k}:{v}" for k, v in item.metrics.items() if isinstance(v, str)),
    ])

    kimi_matches = count_keyword_matches(searchable_text, KIMI_KEYWORDS)
    aihues_matches = count_keyword_matches(searchable_text, AIHUES_KEYWORDS)

    # 基础分 + 匹配分，最高不超过 1.0
    score = 0.1 + kimi_matches * 0.15 + aihues_matches * 0.12
    return min(score, 1.0)


def enrich_item(item: TrendItem) -> TrendItem:
    """补充分类和相关度分数"""
    category = SOURCE_CATEGORY.get(item.source, "资讯")
    item.category = category
    item.relevance_score = score_relevance(item)
    return item


def score_recency(item: TrendItem) -> float:
    """时间越近分越高，7 天内线性衰减"""
    if not item.published_at:
        return 0.5
    now = datetime.now(timezone.utc)
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    days_old = (now - published).total_seconds() / 86400
    if days_old <= 0:
        return 1.0
    if days_old >= 7:
        return 0.1
    return 1.0 - (days_old / 7) * 0.9


def rank_items(items: list[TrendItem]) -> list[TrendItem]:
    """综合相关度和时效性排序"""
    enriched = [enrich_item(item) for item in items]
    for item in enriched:
        item.relevance_score = score_relevance(item) * 0.7 + score_recency(item) * 0.3

    enriched.sort(key=lambda x: x.relevance_score, reverse=True)
    return enriched


def select_top_items(items: list[TrendItem], total: int = 5, max_per_category: int = 2) -> list[TrendItem]:
    """
    选出 top N 条资讯，尽量保证分类多样性。

    策略：
    1. 先按相关度排序
    2. 每个分类最多取 max_per_category 条
    3. 如果选不够，再从剩余中补
    """
    ranked = rank_items(items)
    selected: list[TrendItem] = []
    category_counts: dict[str, int] = {}
    remaining: list[TrendItem] = []

    for item in ranked:
        cat = item.category or "资讯"
        if category_counts.get(cat, 0) < max_per_category and len(selected) < total:
            selected.append(item)
            category_counts[cat] = category_counts.get(cat, 0) + 1
        else:
            remaining.append(item)

    # 补满到 total
    while len(selected) < total and remaining:
        selected.append(remaining.pop(0))

    # 最终按相关度再排一次
    selected.sort(key=lambda x: x.relevance_score, reverse=True)
    return selected


def format_daily_brief(items: list[TrendItem], date_str: str = "") -> str:
    """生成 aihot 风格的中文日报 Markdown"""
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    lines = [f"**AI 趋势早报 · {date_str}**", ""]

    for idx, item in enumerate(items, 1):
        source_label = _source_label(item)
        title_line = f"{idx}. [{item.category}] {item.title} — {source_label}"
        lines.append(title_line)

        summary = item.summary[:80] + "..." if len(item.summary) > 80 else item.summary
        if summary:
            lines.append(summary)

        if item.url:
            lines.append(str(item.url))
        lines.append("")

    lines.append("数据来自 AI Trend Collector · 每天 10:00 生成")
    return "\n".join(lines)


def _source_label(item: TrendItem) -> str:
    """生成来源标签"""
    if item.author:
        return item.author
    source_display = {
        "product_hunt": "Product Hunt",
        "github_trends": "GitHub",
        "arxiv_ai": "arXiv",
        "huggingface_papers": "Hugging Face",
    }
    return source_display.get(item.source, item.source)
