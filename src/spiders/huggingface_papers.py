from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from src.core.base_spider import BaseSpider
from src.core.models import TrendItem, TrendType


class HuggingfacePapersSpider(BaseSpider):
    """Hugging Face Daily Papers 爬虫

    抓取 https://huggingface.co/papers
    """

    name = "huggingface_papers"
    source_type = TrendType.RESEARCH_PAPER
    default_max_items = 30
    LIST_URL = "https://huggingface.co/papers"

    def fetch(self, **kwargs: Any) -> list[TrendItem]:
        source_config = self.config.source_config(self.name)
        max_items = source_config.get("max_items", self.default_max_items)

        response = self._get(self.LIST_URL)
        soup = BeautifulSoup(response.text, "html.parser")

        # HF 页面中论文链接形如 /papers/arxiv_id
        links = soup.find_all("a", href=re.compile(r"^/papers/\d+\.\d+"))
        logger.info(f"[{self.name}] 找到 {len(links)} 个论文链接")

        seen = set()
        items: list[TrendItem] = []
        for link in links:
            if len(items) >= max_items:
                break
            href = link.get("href", "")
            arxiv_id = href.split("/")[-1]
            if not arxiv_id or arxiv_id in seen:
                continue
            seen.add(arxiv_id)

            item = self._parse_paper(arxiv_id, link)
            if item:
                items.append(item)

        return items

    def _parse_paper(self, arxiv_id: str, link: BeautifulSoup) -> TrendItem | None:
        url = f"https://huggingface.co/papers/{arxiv_id}"
        title = link.get_text(strip=True) or arxiv_id

        # 尝试从父元素提取更多信息
        summary = ""
        tags: list[str] = []
        metrics: dict[str, Any] = {"arxiv_id": arxiv_id}

        parent = link.find_parent(["article", "div", "li"])
        if parent:
            # 摘要
            desc = parent.find("p")
            if desc:
                summary = desc.get_text(strip=True)

            # 点赞/评论数
            for span in parent.find_all("span"):
                text = span.get_text(strip=True)
                if re.match(r"^\d+\s*♡", text):
                    metrics["likes"] = text
                elif re.match(r"^\d+\s*💬", text):
                    metrics["comments"] = text

        return TrendItem(
            id=self.make_id(arxiv_id),
            source=self.name,
            type=TrendType.RESEARCH_PAPER,
            title=title,
            url=url,
            summary=summary,
            tags=["huggingface", "paper", "daily-papers"] + tags,
            metrics=metrics,
            published_at=datetime.utcnow(),
            raw_data={"arxiv_id": arxiv_id, "html": str(link)[:2000]},
        )
