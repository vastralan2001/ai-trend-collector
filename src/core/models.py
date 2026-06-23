from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


class TrendType(str, Enum):
    AI_PRODUCT = "ai_product"
    OPEN_SOURCE = "open_source"
    RESEARCH_PAPER = "research_paper"
    TECH_NEWS = "tech_news"
    TREND = "trend"


class TrendItem(BaseModel):
    """统一的数据条目模型"""

    id: str = Field(..., description="全局唯一 ID，格式建议 source:identifier")
    source: str = Field(..., description="数据源名称，如 github_trends, arxiv_ai")
    type: TrendType = Field(..., description="内容类型")
    title: str = Field(..., description="标题")
    url: Optional[HttpUrl] = Field(default=None, description="原始链接")
    summary: str = Field(default="", description="摘要/描述")
    author: Optional[str] = Field(default=None, description="作者/发布者")
    tags: list[str] = Field(default_factory=list, description="标签/分类")
    metrics: dict[str, Any] = Field(default_factory=dict, description="相关指标，如 stars, votes, citations")
    category: str = Field(default="", description="中文分类标签，如 AI产品 / 论文 / 开源项目 / 竞对资讯")
    relevance_score: float = Field(default=0.0, description="与 Kimi/AIHues 的相关度得分，0-1")
    published_at: Optional[datetime] = Field(default=None, description="发布时间")
    fetched_at: datetime = Field(default_factory=datetime.utcnow, description="抓取时间")
    raw_data: Optional[dict[str, Any]] = Field(default=None, description="原始数据，用于调试")

    def to_markdown(self) -> str:
        """转换为 Markdown 格式，便于飞书推送"""
        lines = [f"**{self.title}**"]
        if self.author:
            lines.append(f"作者/发布者：{self.author}")
        if self.summary:
            lines.append(self.summary[:300] + ("..." if len(self.summary) > 300 else ""))
        if self.url:
            lines.append(f"[查看详情]({self.url})")
        if self.tags:
            lines.append(f"标签：{', '.join(self.tags)}")
        if self.metrics:
            metrics_str = " | ".join(f"{k}: {v}" for k, v in self.metrics.items())
            lines.append(f"指标：{metrics_str}")
        return "\n\n".join(lines)
