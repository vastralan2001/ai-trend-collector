from __future__ import annotations

import base64
import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import requests
from loguru import logger

from src.core.config import Config
from src.core.models import TrendItem, TrendType


class BaseFeishuBot(ABC):
    """飞书机器人抽象基类"""

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def send_text(self, text: str) -> dict[str, Any]:
        return self.send({
            "msg_type": "text",
            "content": {"text": text},
        })

    def send_markdown(self, title: str, content: str) -> dict[str, Any]:
        return self.send({
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

        return self.send({
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


class WebhookBot(BaseFeishuBot):
    """飞书自定义机器人（Webhook 模式）

    文档：https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
    """

    def __init__(self, webhook_url: str, secret: str = "") -> None:
        self.webhook_url = webhook_url
        self.secret = secret
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

    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            logger.warning("[WebhookBot] 未配置 webhook_url，跳过推送")
            return {}

        timestamp = str(int(datetime.utcnow().timestamp()))
        payload["timestamp"] = timestamp
        payload["sign"] = self._sign(timestamp)

        try:
            response = self.session.post(self.webhook_url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                logger.error(f"[WebhookBot] 推送失败：{result}")
            else:
                logger.info("[WebhookBot] 推送成功")
            return result
        except Exception as e:
            logger.error(f"[WebhookBot] 请求异常：{e}")
            return {}


class AppBot(BaseFeishuBot):
    """飞书企业自建应用机器人（App 模式）

    通过 app_id + app_secret 获取 tenant_access_token，
    再调用消息 API 发送到指定 chat_id。

    文档：https://open.feishu.cn/document/server-docs/im-v1/message/create
    """

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str, chat_id: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json; charset=utf-8"
        self._tenant_access_token: str | None = None
        self._token_expire_at: float = 0

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.chat_id)

    def _get_tenant_access_token(self) -> str | None:
        """获取并缓存 tenant_access_token"""
        import time

        if self._tenant_access_token and time.time() < self._token_expire_at - 60:
            return self._tenant_access_token

        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }
        try:
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                logger.error(f"[AppBot] 获取 tenant_access_token 失败：{result}")
                return None
            self._tenant_access_token = result["tenant_access_token"]
            self._token_expire_at = time.time() + result.get("expire", 7200)
            logger.debug("[AppBot] tenant_access_token 已刷新")
            return self._tenant_access_token
        except Exception as e:
            logger.error(f"[AppBot] 请求 tenant_access_token 异常：{e}")
            return None

    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            logger.warning("[AppBot] 未配置 app_id/app_secret/chat_id，跳过推送")
            return {}

        token = self._get_tenant_access_token()
        if not token:
            return {}

        url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=chat_id"
        headers = {"Authorization": f"Bearer {token}"}
        body = {
            "receive_id": self.chat_id,
            "msg_type": payload.get("msg_type", "text"),
            "content": json.dumps(payload.get("content") or payload.get("card") or {}, ensure_ascii=False),
        }

        try:
            response = self.session.post(url, headers=headers, json=body, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                logger.error(f"[AppBot] 推送失败：{result}")
            else:
                logger.info("[AppBot] 推送成功")
            return result
        except Exception as e:
            logger.error(f"[AppBot] 请求异常：{e}")
            return {}


class FeishuBot:
    """飞书机器人统一入口，根据配置自动选择 Webhook 或 App 模式"""

    def __init__(self, config: Config) -> None:
        mode = config.get("feishu.mode", "webhook")
        if mode == "app":
            self._bot: BaseFeishuBot = AppBot(
                app_id=config.get("feishu.app_id", ""),
                app_secret=config.get("feishu.app_secret", ""),
                chat_id=config.get("feishu.chat_id", ""),
            )
        else:
            self._bot = WebhookBot(
                webhook_url=config.get("feishu.webhook_url", ""),
                secret=config.get("feishu.secret", ""),
            )

    def is_configured(self) -> bool:
        return self._bot.is_configured()

    def send_text(self, text: str) -> dict[str, Any]:
        return self._bot.send_text(text)

    def send_markdown(self, title: str, content: str) -> dict[str, Any]:
        return self._bot.send_markdown(title, content)

    def send_trend_items(self, items: list[TrendItem], title: str = "AI 趋势日报") -> dict[str, Any]:
        return self._bot.send_trend_items(items, title)
