from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger


class Config:
    """简单的 YAML 配置加载器"""

    def __init__(self, path: str | Path = "config/config.yaml") -> None:
        self._path = Path(path)
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        if not self._path.exists():
            logger.warning(f"配置文件不存在：{self._path}，使用空配置")
            self._data = {}
            return

        with open(self._path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        logger.debug(f"已加载配置：{self._path}")

    def get(self, key: str, default: Any = None) -> Any:
        """支持点号分隔的 key，如 'feishu.webhook_url'"""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    @property
    def feishu_webhook_url(self) -> str | None:
        return self.get("feishu.webhook_url")

    @property
    def feishu_secret(self) -> str | None:
        return self.get("feishu.secret")

    @property
    def storage_type(self) -> str:
        return self.get("storage.type", "json")

    @property
    def storage_output_dir(self) -> Path:
        return Path(self.get("storage.output_dir", "./data"))

    @property
    def crawler_timeout(self) -> int:
        return self.get("crawler.timeout", 30)

    @property
    def crawler_delay(self) -> float:
        return self.get("crawler.delay", 1.0)

    @property
    def crawler_retries(self) -> int:
        return self.get("crawler.retries", 3)

    @property
    def crawler_user_agent(self) -> str:
        return self.get("crawler.user_agent", "AI-Trend-Collector/0.1.0")

    @property
    def crawler_proxy(self) -> str | None:
        return self.get("crawler.proxy") or None

    def source_config(self, name: str) -> dict[str, Any]:
        return self.get(f"sources.{name}", {})
