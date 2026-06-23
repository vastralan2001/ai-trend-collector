from __future__ import annotations

from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from src.core.base_spider import BaseSpider
from src.core.models import TrendItem, TrendType


class GitHubTrendsSpider(BaseSpider):
    """GitHub Trending 爬虫

    抓取 https://github.com/trending 页面。
    由于 GitHub 页面结构可能变化，建议结合 GitHub API 或定期验证选择器。
    """

    name = "github_trends"
    source_type = TrendType.OPEN_SOURCE
    default_max_items = 30

    def fetch(self, **kwargs: Any) -> list[TrendItem]:
        source_config = self.config.source_config(self.name)
        languages = source_config.get("languages", [])
        period = source_config.get("period", "daily")
        max_items = source_config.get("max_items", self.default_max_items)

        items: list[TrendItem] = []
        # 分别抓取每个语言的 trending，最后再抓一次全量的
        targets = languages + [""]

        for lang in targets:
            if len(items) >= max_items:
                break

            url = "https://github.com/trending"
            params: dict[str, str] = {"since": period}
            if lang:
                url = f"{url}/{lang}"
                params = {"since": period}

            try:
                response = self._get(url, params=params)
                soup = BeautifulSoup(response.text, "html.parser")
                repo_articles = soup.select("article.Box-row")
                logger.info(f"[{self.name}] {lang or 'all'} 找到 {len(repo_articles)} 个仓库")

                for article in repo_articles:
                    if len(items) >= max_items:
                        break
                    item = self._parse_article(article, lang or "all")
                    if item:
                        items.append(item)
            except Exception as e:
                logger.error(f"[{self.name}] 抓取 {lang or 'all'} 失败：{e}")

        return items

    def _parse_article(self, article: BeautifulSoup, language: str) -> TrendItem | None:
        # 仓库名
        link = article.select_one("h2 a")
        if not link or not link.get("href"):
            return None

        repo_path = link["href"].strip()
        repo_name = repo_path.lstrip("/")
        url = f"https://github.com{repo_path}"

        # 描述
        desc_tag = article.select_one("p.col-9")
        summary = desc_tag.get_text(strip=True) if desc_tag else ""

        # 星星数与今日新增
        stars_text = ""
        today_stars = ""
        for span in article.select("a.Link--muted, span.d-inline-block"):
            text = span.get_text(strip=True)
            if "stars" in text or text.replace(",", "").replace(".", "").isdigit():
                if not stars_text:
                    stars_text = text
                elif not today_stars:
                    today_stars = text
                    break

        # 语言
        lang_tag = article.select_one("span[itemprop='programmingLanguage']")
        detected_lang = lang_tag.get_text(strip=True) if lang_tag else language

        return TrendItem(
            id=self.make_id(repo_name),
            source=self.name,
            type=TrendType.OPEN_SOURCE,
            title=repo_name,
            url=url,
            summary=summary,
            author=repo_name.split("/")[0] if "/" in repo_name else None,
            tags=["github", "trending", detected_lang] if detected_lang else ["github", "trending"],
            metrics={
                "language": detected_lang,
                "stars": stars_text,
                "today_stars": today_stars,
            },
            published_at=datetime.utcnow(),
            raw_data={"language": language, "html": str(article)[:2000]},
        )
