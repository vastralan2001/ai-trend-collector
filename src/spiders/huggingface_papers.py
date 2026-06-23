from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import feedparser
from bs4 import BeautifulSoup
from loguru import logger

from src.core.base_spider import BaseSpider
from src.core.models import TrendItem, TrendType


class HuggingfacePapersSpider(BaseSpider):
    """Hugging Face Daily Papers 爬虫

    抓取 https://huggingface.co/papers 的 arxiv_id 列表，
    再通过 arXiv API 批量获取标题和摘要。
    """

    name = "huggingface_papers"
    source_type = TrendType.RESEARCH_PAPER
    default_max_items = 30
    LIST_URL = "https://huggingface.co/papers"
    ARXIV_API_URL = "http://export.arxiv.org/api/query"

    def fetch(self, **kwargs: Any) -> list[TrendItem]:
        source_config = self.config.source_config(self.name)
        max_items = source_config.get("max_items", self.default_max_items)

        response = self._get(self.LIST_URL)
        soup = BeautifulSoup(response.text, "html.parser")

        # HF 页面中论文链接形如 /papers/arxiv_id
        links = soup.find_all("a", href=re.compile(r"^/papers/\d+\.\d+"))
        logger.info(f"[{self.name}] 找到 {len(links)} 个论文链接")

        seen = set()
        arxiv_ids: list[str] = []
        for link in links:
            if len(arxiv_ids) >= max_items:
                break
            href = link.get("href", "")
            arxiv_id = href.split("/")[-1]
            if not arxiv_id or arxiv_id in seen:
                continue
            seen.add(arxiv_id)
            arxiv_ids.append(arxiv_id)

        if not arxiv_ids:
            return []

        return self._fetch_arxiv_details(arxiv_ids)

    def _fetch_arxiv_details(self, arxiv_ids: list[str]) -> list[TrendItem]:
        """通过 arXiv API 批量获取论文详情"""
        id_list = ",".join(arxiv_ids)
        params = {
            "id_list": id_list,
            "max_results": len(arxiv_ids),
        }
        logger.info(f"[{self.name}] 通过 arXiv API 批量查询 {len(arxiv_ids)} 篇论文")

        response = self._get(self.ARXIV_API_URL, params=params)
        feed = feedparser.parse(response.text)

        items: list[TrendItem] = []
        for entry in feed.entries:
            item = self._parse_arxiv_entry(entry)
            if item:
                items.append(item)

        logger.info(f"[{self.name}] 解析到 {len(items)} 篇论文详情")
        return items

    def _parse_arxiv_entry(self, entry: Any) -> TrendItem | None:
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
            title=title or arxiv_id,
            url=f"https://huggingface.co/papers/{arxiv_id}",
            summary=summary,
            author=", ".join(authors[:3]) + ("..." if len(authors) > 3 else ""),
            tags=["huggingface", "paper", "daily-papers"] + tags[:5],
            metrics={
                "arxiv_id": arxiv_id,
                "pdf_url": pdf_url,
                "authors_count": len(authors),
                "categories": tags,
            },
            published_at=published_at,
            raw_data={"arxiv_id": arxiv_id, "entry": dict(entry)},
        )
