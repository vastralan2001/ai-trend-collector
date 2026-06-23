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

    def send_daily_brief(self, items: list[TrendItem], date_str: str = "", kb_url: str = "") -> dict[str, Any]:
        """发送 aihot 风格的中文精简日报"""
        from src.core.ranker import format_daily_brief

        if not items:
            return self.send_text("今日暂无新的 AI 趋势数据。")

        if not date_str:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

        brief_md = format_daily_brief(items, date_str)
        if kb_url:
            brief_md += f"\n完整日报已归档至飞书知识库：[查看]({kb_url})"

        return self.send_markdown(f"AI 趋势早报 · {date_str}", brief_md)

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

    def __init__(self, app_id: str, app_secret: str, chat_id: str, folder_token: str = "") -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.folder_token = folder_token
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

    def create_document(self, title: str, markdown_content: str, folder_token: str = "") -> str | None:
        """创建飞书文档，返回文档 URL。需要应用开通 docx:document 权限。"""
        token = self._get_tenant_access_token()
        if not token:
            return None

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

        # 1. 创建空文档
        create_body: dict[str, Any] = {"title": title}
        if folder_token:
            create_body["folder_token"] = folder_token

        try:
            resp = self.session.post(
                f"{self.BASE_URL}/docx/v1/documents",
                headers=headers,
                json=create_body,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"[AppBot] 创建文档失败：{data}")
                return None
            doc_id = data["data"]["document"]["document_id"]
            logger.info(f"[AppBot] 文档已创建：{doc_id}")
        except Exception as e:
            logger.error(f"[AppBot] 创建文档异常：{e}")
            return None

        # 2. 把 markdown 拆成段落写入文档（写到根 page 下）
        blocks = self._markdown_to_blocks(markdown_content)
        try:
            chunk_size = 50
            for i in range(0, len(blocks), chunk_size):
                chunk = blocks[i : i + chunk_size]
                resp = self.session.post(
                    f"{self.BASE_URL}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?document_revision_id=-1",
                    headers=headers,
                    json={
                        "children": chunk,
                        "document_revision_id": -1,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                result = resp.json()
                if result.get("code") != 0:
                    logger.error(f"[AppBot] 写入文档内容失败：{result}")
                    return None
                logger.debug(f"[AppBot] 已写入 {len(chunk)} 个 block")
        except Exception as e:
            logger.error(f"[AppBot] 写入文档异常：{e}")
            return None

        return f"https://www.feishu.cn/docx/{doc_id}"

    def create_folder(self, name: str, parent_folder_token: str = "") -> str | None:
        """创建云文档文件夹，返回 folder_token。需要 drive:drive 权限。"""
        token = self._get_tenant_access_token()
        if not token:
            return None

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        url = f"{self.BASE_URL}/drive/v1/files"
        body: dict[str, Any] = {
            "name": name,
            "type": "folder",
        }
        if parent_folder_token:
            body["folder_token"] = parent_folder_token

        try:
            resp = self.session.post(url, headers=headers, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"[AppBot] 创建文件夹失败：{data}")
                return None
            folder_token = data["data"]["token"]
            logger.info(f"[AppBot] 文件夹已创建：{folder_token}")
            return folder_token
        except Exception as e:
            logger.error(f"[AppBot] 创建文件夹异常：{e}")
            return None

    @staticmethod
    def _markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
        """极简 markdown 转飞书 docx block（使用数字 block_type）"""
        blocks: list[dict[str, Any]] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            content = stripped.lstrip("# ").lstrip("## ").lstrip("### ").strip()
            text_run = {"text_run": {"content": content, "text_element_style": {}}}

            if stripped.startswith("# "):
                blocks.append({
                    "block_type": 3,
                    "heading1": {"elements": [text_run], "style": {"align": 1, "folded": False}},
                })
            elif stripped.startswith("## "):
                blocks.append({
                    "block_type": 4,
                    "heading2": {"elements": [text_run], "style": {"align": 1, "folded": False}},
                })
            elif stripped.startswith("### "):
                blocks.append({
                    "block_type": 5,
                    "heading3": {"elements": [text_run], "style": {"align": 1, "folded": False}},
                })
            else:
                blocks.append({
                    "block_type": 2,
                    "text": {"elements": [text_run], "style": {"align": 1, "folded": False}},
                })
        return blocks


class FeishuBot:
    """飞书机器人统一入口，根据配置自动选择 Webhook 或 App 模式"""

    def __init__(self, config: Config) -> None:
        mode = config.get("feishu.mode", "webhook")
        if mode == "app":
            self._bot: BaseFeishuBot = AppBot(
                app_id=config.get("feishu.app_id", ""),
                app_secret=config.get("feishu.app_secret", ""),
                chat_id=config.get("feishu.chat_id", ""),
                folder_token=config.get("feishu.folder_token", ""),
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

    def send_daily_brief(self, items: list[TrendItem], date_str: str = "", kb_url: str = "") -> dict[str, Any]:
        return self._bot.send_daily_brief(items, date_str, kb_url)

    def create_document(self, title: str, markdown_content: str, folder_token: str = "") -> str | None:
        """创建飞书文档并返回链接，仅 App 模式支持"""
        if isinstance(self._bot, AppBot):
            return self._bot.create_document(title, markdown_content, folder_token)
        logger.warning("[FeishuBot] 创建文档仅支持 app 模式")
        return None

    def create_folder(self, name: str, parent_folder_token: str = "") -> str | None:
        """创建云文档文件夹，仅 App 模式支持"""
        if isinstance(self._bot, AppBot):
            return self._bot.create_folder(name, parent_folder_token)
        logger.warning("[FeishuBot] 创建文件夹仅支持 app 模式")
        return None
