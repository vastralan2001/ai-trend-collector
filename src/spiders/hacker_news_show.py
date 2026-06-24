from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger

from src.core.base_spider import BaseSpider
from src.core.models import TrendItem, TrendType


class HackerNewsShowSpider(BaseSpider):
    """Hacker News "Show HN" 爬虫

    抓取 https://news.ycombinator.com/show 中的项目发布帖，
    重点筛选与小游戏、互动 Demo、AI 工具相关的项目。

    HN 官方 Firebase API：
    - showstories: https://hacker-news.firebaseio.com/v0/showstories.json
    - item: https://hacker-news.firebaseio.com/v0/item/{id}.json
    """

    name = "hacker_news_show"
    source_type = TrendType.GAMES
    default_max_items = 30
    API_BASE = "https://hacker-news.firebaseio.com/v0"

    # 标题中必须命中这些强游戏关键词才算游戏（HN 标题通常很直接）
    STRONG_GAME_KEYWORDS = [
        "game", "games", "gaming", "puzzle", "puzzles", "arcade", "platformer",
        "roguelike", "roguelite", "multiplayer", "browser game", "web game",
        "mini game", "mini-game", "idle game", "card game", "board game",
        "sandbox", "simulator", "tycoon", "strategy game", "action game",
    ]

    # 正文可以补充这些可玩/demo 关键词，但标题必须先通过强过滤
    BODY_GAME_KEYWORDS = [
        "play", "playable", "demo", "interactive", "canvas", "webgl",
    ]

    # 明确排除的非游戏内容
    BLOCKED_KEYWORDS = [
        "hiring", "job", "jobs", "course", "courses", "bootcamp",
        "consulting", "agency", "freelance", "promoted", "sponsored",
        "open-source alternative", "alternative for", "platform for",
        "workspace", "collaboration tool", "management tool",
    ]

    def fetch(self, **kwargs: Any) -> list[TrendItem]:
        source_config = self.config.source_config(self.name)
        max_items = source_config.get("max_items", self.default_max_items)
        min_score = source_config.get("min_score", 10)

        story_ids = self._fetch_show_story_ids()
        logger.info(f"[{self.name}] 获取到 {len(story_ids)} 个 Show HN 故事")

        items: list[TrendItem] = []
        for story_id in story_ids[:max_items * 3]:
            if len(items) >= max_items:
                break
            story = self._fetch_item(story_id)
            if not story:
                continue
            item = self._parse_story(story, min_score)
            if item:
                items.append(item)

        logger.info(f"[{self.name}] 解析到 {len(items)} 个有效项目")
        return items

    def _fetch_show_story_ids(self) -> list[int]:
        response = self._get(f"{self.API_BASE}/showstories.json")
        return response.json()

    def _fetch_item(self, item_id: int) -> dict[str, Any] | None:
        try:
            response = self._get(f"{self.API_BASE}/item/{item_id}.json")
            return response.json()
        except Exception as e:
            logger.warning(f"[{self.name}] 获取故事 {item_id} 失败：{e}")
            return None

    def _parse_story(self, story: dict[str, Any], min_score: int) -> TrendItem | None:
        if not story or story.get("deleted") or story.get("dead"):
            return None

        title = (story.get("title") or "").strip()
        # 去掉常见的 Show HN / Launch HN 前缀，让标题更干净
        title = re.sub(r"^(Show HN|Launch HN)\s*[:\-]?\s*", "", title, flags=re.IGNORECASE)
        url = story.get("url", "")
        text = (story.get("text") or "").strip()
        score = story.get("score", 0)
        story_id = story.get("id")

        if not title or not story_id:
            return None
        if score < min_score:
            return None
        if not self._is_game_or_demo_related(title, text):
            return None

        # 没有外部 URL 的 Show HN 通常是讨论帖，用 HN 自身链接
        if not url:
            url = f"https://news.ycombinator.com/item?id={story_id}"

        published_at = None
        time_val = story.get("time")
        if time_val:
            published_at = datetime.utcfromtimestamp(time_val)

        return TrendItem(
            id=self.make_id(str(story_id)),
            source=self.name,
            type=TrendType.GAMES,
            title=title,
            url=url,
            summary=self._extract_summary(title, text),
            author=story.get("by"),
            tags=["show-hn", "hacker-news", self._detect_tag(title, text)],
            metrics={
                "hn_id": story_id,
                "score": score,
                "comments": story.get("descendants", 0),
            },
            published_at=published_at,
            raw_data={"story": story},
        )

    def _is_game_or_demo_related(self, title: str, text: str) -> bool:
        title_lower = title.lower()
        combined = f"{title} {text}".lower()
        if any(kw in combined for kw in self.BLOCKED_KEYWORDS):
            return False
        # 标题必须包含强游戏关键词
        if not any(kw in title_lower for kw in self.STRONG_GAME_KEYWORDS):
            return False
        return True

    def _detect_tag(self, title: str, text: str) -> str:
        combined = f"{title} {text}".lower()
        has_game = any(kw in combined for kw in self.STRONG_GAME_KEYWORDS + self.BODY_GAME_KEYWORDS)
        # 用正则匹配完整单词，避免 "daily" 被误判为 "ai"
        has_ai = bool(re.search(r"\b(ai|llm|machine learning)\b", combined))
        if has_game and has_ai:
            return "ai-game"
        if "multiplayer" in combined:
            return "multiplayer"
        if "puzzle" in combined:
            return "puzzle"
        return "browser-game"

    def _extract_summary(self, title: str, text: str) -> str:
        # 正文存在时取前 400 字符作为摘要，否则回退到标题
        if text:
            clean_text = text.replace("<p>", " ").replace("</p>", " ")
            clean_text = re.sub(r"<[^>]+>", " ", clean_text)
            clean_text = " ".join(clean_text.split())
            if len(clean_text) > 40:
                return (title + ". " + clean_text[:400]).strip()
        return title
