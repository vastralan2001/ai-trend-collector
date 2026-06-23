from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from src.core.base_spider import BaseSpider
from src.core.models import TrendItem, TrendType


class ProductHuntSpider(BaseSpider):
    """Product Hunt 爬虫

    使用 Product Hunt GraphQL API v2：
    https://api.producthunt.com/v2/docs

    需要在 config.yaml 中配置：
        sources:
          product_hunt:
            enabled: true
            api_token: "YOUR_API_TOKEN"
            max_items: 30
    """

    name = "product_hunt"
    source_type = TrendType.AI_PRODUCT
    default_max_items = 30
    API_URL = "https://api.producthunt.com/v2/api/graphql"

    def fetch(self, **kwargs: Any) -> list[TrendItem]:
        source_config = self.config.source_config(self.name)
        max_items = source_config.get("max_items", self.default_max_items)
        api_token = source_config.get("api_token", "")

        if not api_token:
            logger.warning(
                f"[{self.name}] 未配置 api_token，跳过。"
                "请在 config.yaml 的 sources.product_hunt.api_token 中填写。"
            )
            return []

        self.session.headers["Authorization"] = f"Bearer {api_token}"
        self.session.headers["Accept"] = "application/json"

        query = """
        query GetFeaturedPosts($first: Int) {
            posts(first: $first, order: RANKING, featured: true) {
                edges {
                    node {
                        id
                        name
                        tagline
                        description
                        url
                        website
                        votesCount
                        commentsCount
                        createdAt
                        topics {
                            edges {
                                node {
                                    name
                                }
                            }
                        }
                        user {
                            name
                        }
                    }
                }
            }
        }
        """

        variables = {"first": min(max_items, 100)}
        response = self._post(
            self.API_URL,
            json={"query": query, "variables": variables},
        )
        data = response.json()

        if "errors" in data:
            logger.error(f"[{self.name}] API 错误：{data['errors']}")
            return []

        edges = data.get("data", {}).get("posts", {}).get("edges", [])
        logger.info(f"[{self.name}] 获取到 {len(edges)} 个产品")

        items: list[TrendItem] = []
        for edge in edges:
            node = edge.get("node", {})
            item = self._parse_node(node)
            if item:
                items.append(item)

        return items

    def _parse_node(self, node: dict[str, Any]) -> TrendItem | None:
        product_id = node.get("id")
        if not product_id:
            return None

        name = node.get("name", "")
        tagline = node.get("tagline", "")
        description = node.get("description", "")
        summary = tagline or description or ""
        url = node.get("url") or node.get("website", "")
        votes = node.get("votesCount", 0)
        comments = node.get("commentsCount", 0)

        topics = [
            t["node"]["name"]
            for t in node.get("topics", {}).get("edges", [])
            if "node" in t and "name" in t["node"]
        ]

        created_at = node.get("createdAt")
        published_at = None
        if created_at:
            try:
                published_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                pass

        return TrendItem(
            id=self.make_id(product_id),
            source=self.name,
            type=TrendType.AI_PRODUCT,
            title=name,
            url=url,
            summary=summary,
            author=node.get("user", {}).get("name"),
            tags=["product-hunt", "ai-product"] + topics[:5],
            metrics={
                "votes": votes,
                "comments": comments,
                "topics": topics,
            },
            published_at=published_at,
            raw_data={"node": node},
        )
