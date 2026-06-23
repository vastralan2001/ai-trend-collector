from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

import requests
from loguru import logger

from src.core.config import Config
from src.core.models import TrendItem, TrendType


class FeishuBot:
    """飞书自定义机器人（Webhook）推送

    文档：https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
    """

    def __init__(self, config: Config) -> None:
        self.webhook_url = config.get("feishu.webhook_url", "")
        self.secret = config.get("feishu.secret", "")
        self.default_chat_id = config.get("feishu.default_chat_id", "")
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json; charset=utf-8"

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def _sign(self, timestamp: str) -> str:
        """生成飞书签名"""
        if not self.secret:
            return ""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            logger.warning("[FeishuBot] 未配置 webhook_url，跳过推送")
            return {}

        timestamp = str(int(datetime.utcnow().timestamp()))
        payload["timestamp"] = timestamp
        payload["sign"] = self._sign(timestamp)

        try:
            response = self.session.post(self.webhook_url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                logger.error(f"[FeishuBot] 推送失败：{result}")
            else:
                logger.info("[FeishuBot] 推送成功")
            return result
        except Exception as e:
            logger.error(f"[FeishuBot] 请求异常：{e}")
            return {}

    def send_text(self, text: str) -> dict[str, Any]:
        return self._send({
            "msg_type": "text",
            "content": {"text": text},
        })

    def send_markdown(self, title: str, content: str) -> dict[str, Any]:
        return self._send({
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": content},
                    }
                ],
            },
        })

    def send_trend_items(self, items: list[TrendItem], title: str = "AI 趋势日报") -> dict[str, Any]:
        """批量推送 TrendItem"""
        if not items:
            return self.send_text("今日暂无新的 AI 趋势数据。")

        sections: list[dict[str, Any]] = []
        for item in items:
            emoji = self._type_emoji(item.type)
            sections.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"{emoji} **{item.title}**\n{item.summary[:200]}{'...' if len(item.summary) > 200 else ''}\n[查看详情]({item.url})",
                },
            })
            sections.append({"tag": "hr"})

        # 去掉最后一个分割线
        sections = sections[:-1]

        return self._send({
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"{title} ({len(items)} 条)"},
                },
                "elements": sections,
            },
        })

    @staticmethod
    def _type_emoji(trend_type: TrendType) -> str:
        mapping = {
            TrendType.AI_PRODUCT: "🚀",
            TrendType.OPEN_SOURCE: "🛠️",
            TrendType.RESEARCH_PAPER: "📄",
            TrendType.TECH_NEWS: "📰",
            TrendType.TREND: "🔥",
        }
        return mapping.get(trend_type, "📌")
