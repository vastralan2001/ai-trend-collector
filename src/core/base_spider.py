from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any

import requests
from loguru import logger

from src.core.config import Config
from src.core.models import TrendItem
from src.core.storage import BaseStorage


class BaseSpider(ABC):
    """爬虫基类，封装通用请求、去重、存储逻辑"""

    name: str = ""
    source_type: str = ""
    default_max_items: int = 30

    def __init__(self, config: Config, storage: BaseStorage) -> None:
        self.config = config
        self.storage = storage
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.crawler_user_agent,
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            }
        )
        if config.crawler_proxy:
            self.session.proxies.update(
                {
                    "http": config.crawler_proxy,
                    "https": config.crawler_proxy,
                }
            )

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """带重试和延迟的统一请求方法"""
        timeout = kwargs.pop("timeout", self.config.crawler_timeout)
        retries = self.config.crawler_retries
        delay = self.config.crawler_delay

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                if delay > 0:
                    time.sleep(delay)
                logger.debug(f"[{self.name}] 请求 {method} {url} (attempt {attempt})")
                response = self.session.request(
                    method, url, timeout=timeout, **kwargs
                )
                response.raise_for_status()
                return response
            except Exception as e:
                last_error = e
                logger.warning(f"[{self.name}] 请求失败 ({attempt}/{retries})：{e}")
                if attempt < retries:
                    time.sleep(delay * attempt)

        raise last_error or RuntimeError(f"请求最终失败：{url}")

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def _post(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def make_id(self, identifier: str) -> str:
        """生成全局唯一 ID"""
        safe_id = "".join(c if c.isalnum() or c in "-_:." else "_" for c in identifier)
        return f"{self.name}:{safe_id[:100]}"

    def md5_id(self, *parts: str) -> str:
        """基于内容生成 MD5 ID"""
        content = "|".join(parts).encode("utf-8")
        return f"{self.name}:{hashlib.md5(content).hexdigest()}"

    def dedupe(self, items: list[TrendItem]) -> list[TrendItem]:
        """去重，只保留未存储过的条目"""
        new_items = []
        for item in items:
            if self.storage.exists(item.id):
                logger.debug(f"[{self.name}] 已存在，跳过：{item.id}")
                continue
            new_items.append(item)
        return new_items

    @abstractmethod
    def fetch(self, **kwargs: Any) -> list[TrendItem]:
        """子类实现具体的抓取逻辑"""
        raise NotImplementedError

    def run(self, **kwargs: Any) -> list[TrendItem]:
        """运行爬虫并保存结果"""
        logger.info(f"[{self.name}] 开始抓取")
        try:
            items = self.fetch(**kwargs)
            new_items = self.dedupe(items)
            if new_items:
                self.storage.save(new_items)
                logger.info(f"[{self.name}] 新增 {len(new_items)}/{len(items)} 条数据")
            else:
                logger.info(f"[{self.name}] 没有新数据")
            return new_items
        except Exception as e:
            logger.error(f"[{self.name}] 抓取异常：{e}")
            raise
