from __future__ import annotations

import json
import os
from typing import Any

import requests
from loguru import logger

from src.core.models import TrendItem


class LLMClient:
    """基于 OpenAI 兼容接口的 LLM 客户端，用于生成中文概述和产品影响分析。"""

    # 提供商默认配置
    PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1",
            "model": "moonshot-v1-8k",
            "env_key": "KIMI_API_KEY",
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "env_key": "DEEPSEEK_API_KEY",
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "env_key": "OPENAI_API_KEY",
        },
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        provider = self.config.get("provider", "openai").lower()
        self.provider = provider if provider in self.PROVIDER_DEFAULTS else "openai"
        defaults = self.PROVIDER_DEFAULTS[self.provider]

        self.base_url = self.config.get("base_url") or defaults["base_url"]
        self.model = self.config.get("model") or defaults["model"]
        self.api_key = self.config.get("api_key") or os.getenv(defaults["env_key"], "")
        self.timeout = self.config.get("timeout", 60)
        self.max_tokens = self.config.get("max_tokens", 300)
        self.temperature = self.config.get("temperature", 0.3)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _build_messages(self, item: TrendItem) -> list[dict[str, str]]:
        content = f"""请基于下面的 AI 资讯，生成两段中文内容：

1. **一句话概述**：用 1 句话概括这条新闻的核心内容，50 字以内，口语化、信息明确。
2. **产品参考与影响**：分析这条资讯对我们产品（Kimi 智能助手、AIHues AI 工具导航站）的参考价值或潜在影响，100 字以内，具体、可执行，避免空话。

请严格按下面的 JSON 格式输出，不要添加其他说明：
{{
  "chinese_summary": "...",
  "product_impact": "..."
}}

标题：{item.title}
分类：{item.category}
来源：{item.source}
摘要：{item.summary}
"""
        return [
            {
                "role": "system",
                "content": "你是一位 AI 产品分析师，擅长把海外 AI 资讯提炼成中文一句话概述，并分析对国内 AI 产品的参考价值。只输出 JSON，不要解释。",
            },
            {"role": "user", "content": content},
        ]

    @staticmethod
    def _parse_json(content: str) -> dict[str, str] | None:
        """从 LLM 输出中提取 JSON 对象。"""
        text = content.strip()
        # 去掉可能的 markdown 代码块
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"LLM 输出不是标准 JSON：{content[:200]}")
            return None

    def enrich_item(self, item: TrendItem) -> TrendItem:
        """为单条资讯生成中文概述和产品影响。"""
        if not self.is_configured():
            return item

        messages = self._build_messages(item)
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            parsed = self._parse_json(content)
            if parsed:
                item.chinese_summary = parsed.get("chinese_summary", "").strip()
                item.product_impact = parsed.get("product_impact", "").strip()
                logger.debug(f"LLM enrichment 成功：{item.title[:30]}...")
            else:
                logger.warning(f"无法解析 LLM 输出：{content[:150]}")

        except Exception as e:
            logger.error(f"LLM 调用失败（{item.title[:30]}）：{e}")

        return item


def enrich_items_with_llm(items: list[TrendItem], llm_config: dict[str, Any] | None) -> list[TrendItem]:
    """批量为资讯生成中文概述和产品影响，只处理传入的列表（建议只传 top items 以控制成本）。"""
    client = LLMClient(llm_config)
    if not client.is_configured():
        logger.warning(
            "未配置 LLM API Key，跳过中文概述和产品影响生成。"
            "请在 config.yaml 中配置 llm.api_key 或设置环境变量 KIMI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY。"
        )
        return items

    logger.info(f"开始为 {len(items)} 条资讯生成中文概述和产品影响...")
    enriched: list[TrendItem] = []
    for idx, item in enumerate(items, 1):
        logger.debug(f"[{idx}/{len(items)}] 生成：{item.title[:40]}")
        enriched.append(client.enrich_item(item))
    logger.info("LLM enrichment 完成")
    return enriched
