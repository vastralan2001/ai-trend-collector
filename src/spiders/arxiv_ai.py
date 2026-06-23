from __future__ import annotations

from datetime import datetime
from typing import Any

import feedparser
from loguru import logger

from src.core.base_spider import BaseSpider
from src.core.models import TrendItem, TrendType


class ArxivAISpider(BaseSpider):
    """arXiv AI/ML 论文爬虫

    使用 arXiv Atom API：http://export.arxiv.org/api/query
    """

    name = "arxiv_ai"
    source_type = TrendType.RESEARCH_PAPER
    default_max_items = 30
    API_URL = "http://export.arxiv.org/api/query"

    def fetch(self, **kwargs: Any) -> list[TrendItem]:
        source_config = self.config.source_config(self.name)
        categories = source_config.get("categories", ["cs.AI", "cs.LG", "cs.CL", "cs.CV"])
        keywords = source_config.get("keywords", [])
        max_items = source_config.get("max_items", self.default_max_items)

        # 构造查询：按分类 + 关键词
        cat_query = " OR ".join(f"cat:{c}" for c in categories)
        query_parts = [f"({cat_query})"]
        if keywords:
            keyword_query = " OR ".join(f'"{kw}"' for kw in keywords)
            query_parts.append(f"({keyword_query})")

        query = " AND ".join(query_parts)
        params = {
            "search_query": query,
            "start": 0,
            "max_results": min(max_items, 100),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        logger.info(f"[{self.name}] 查询：{query}")
        response = self._get(self.API_URL, params=params)
        feed = feedparser.parse(response.text)

        items: list[TrendItem] = []
        for entry in feed.entries[:max_items]:
            item = self._parse_entry(entry)
            if item:
                items.append(item)

        logger.info(f"[{self.name}] 解析到 {len(items)} 篇论文")
        return items

    def _parse_entry(self, entry: Any) -> TrendItem | None:
        arxiv_id = entry.get("id", "").split("/")[-1].split("v")[0]
        if not arxiv_id:
            return None

        title = entry.get("title", "").replace("\n", " ").strip()
        summary = entry.get("summary", "").replace("\n", " ").strip()
        authors = [a.get("name", "") for a in entry.get("authors", [])]
        tags = [t.get("term", "") for t in entry.get("tags", [])]

        pdf_url = ""
        for link in entry.get("links", []):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
                break

        published = entry.get("published")
        published_at = None
        if published:
            try:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except Exception:
                pass

        return TrendItem(
            id=self.make_id(arxiv_id),
            source=self.name,
            type=TrendType.RESEARCH_PAPER,
            title=title,
            url=entry.get("link", ""),
            summary=summary,
            author=", ".join(authors[:3]) + ("..." if len(authors) > 3 else ""),
            tags=["arxiv", "paper"] + tags[:5],
            metrics={
                "arxiv_id": arxiv_id,
                "pdf_url": pdf_url,
                "authors_count": len(authors),
                "categories": tags,
            },
            published_at=published_at,
            raw_data={"entry": dict(entry)},
        )
