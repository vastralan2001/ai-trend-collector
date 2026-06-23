from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.models import TrendItem, TrendType


class BaseStorage(ABC):
    """存储抽象基类"""

    @abstractmethod
    def save(self, items: list[TrendItem]) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, item_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list_items(self, source: str | None = None, limit: int = 100) -> list[TrendItem]:
        raise NotImplementedError


class JSONStorage(BaseStorage):
    """JSON 文件存储，适合快速启动和小规模数据"""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self.output_dir / "index.json"
        self._index: dict[str, str] = self._load_index()

    def _load_index(self) -> dict[str, str]:
        if not self._index_file.exists():
            return {}
        try:
            with open(self._index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载索引失败：{e}，将重建索引")
            return {}

    def _save_index(self) -> None:
        with open(self._index_file, "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2)

    def _item_path(self, item_id: str) -> Path:
        # 按日期分目录，避免单目录文件过多
        today = datetime.utcnow().strftime("%Y-%m-%d")
        dir_path = self.output_dir / today
        dir_path.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(c if c.isalnum() else "_" for c in item_id)[:120]
        return dir_path / f"{safe_id}.json"

    def save(self, items: list[TrendItem]) -> None:
        for item in items:
            path = self._item_path(item.id)
            with open(path, "w", encoding="utf-8") as f:
                f.write(item.model_dump_json(indent=2, ensure_ascii=False))
            self._index[item.id] = str(path)
        if items:
            self._save_index()
            logger.info(f"已保存 {len(items)} 条数据到 {self.output_dir}")

    def exists(self, item_id: str) -> bool:
        return item_id in self._index

    def list_items(self, source: str | None = None, limit: int = 100) -> list[TrendItem]:
        items: list[TrendItem] = []
        for item_id, path_str in self._index.items():
            if source and not item_id.startswith(f"{source}:"):
                continue
            try:
                with open(path_str, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items.append(TrendItem.model_validate(data))
            except Exception as e:
                logger.warning(f"读取 {path_str} 失败：{e}")
            if len(items) >= limit:
                break
        return items


class SQLiteStorage(BaseStorage):
    """SQLite 存储，适合中等规模数据和简单查询"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trend_items (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    summary TEXT,
                    author TEXT,
                    tags TEXT,
                    metrics TEXT,
                    published_at TEXT,
                    fetched_at TEXT NOT NULL,
                    raw_data TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON trend_items(source)")

    def save(self, items: list[TrendItem]) -> None:
        with self._connect() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trend_items
                    (id, source, type, title, url, summary, author, tags, metrics,
                     published_at, fetched_at, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.source,
                        item.type.value,
                        item.title,
                        str(item.url) if item.url else None,
                        item.summary,
                        item.author,
                        json.dumps(item.tags, ensure_ascii=False),
                        json.dumps(item.metrics, ensure_ascii=False),
                        item.published_at.isoformat() if item.published_at else None,
                        item.fetched_at.isoformat(),
                        json.dumps(item.raw_data, ensure_ascii=False) if item.raw_data else None,
                    ),
                )
        if items:
            logger.info(f"已保存 {len(items)} 条数据到 SQLite")

    def exists(self, item_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM trend_items WHERE id = ?", (item_id,)
            ).fetchone()
            return row is not None

    def list_items(self, source: str | None = None, limit: int = 100) -> list[TrendItem]:
        query = "SELECT * FROM trend_items"
        params: tuple[Any, ...] = ()
        if source:
            query += " WHERE source = ?"
            params = (source,)
        query += " ORDER BY fetched_at DESC LIMIT ?"
        params += (limit,)

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [self._row_to_item(dict(row)) for row in rows]

    def _row_to_item(self, row: dict[str, Any]) -> TrendItem:
        return TrendItem(
            id=row["id"],
            source=row["source"],
            type=TrendType(row["type"]),
            title=row["title"],
            url=row["url"],
            summary=row["summary"] or "",
            author=row["author"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            metrics=json.loads(row["metrics"]) if row["metrics"] else {},
            published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            raw_data=json.loads(row["raw_data"]) if row["raw_data"] else None,
        )


def create_storage(config: Any) -> BaseStorage:
    """工厂函数，根据配置创建存储后端"""
    storage_type = config.storage_type
    if storage_type == "sqlite":
        db_path = config.get("storage.sqlite_path", "./data/trends.db")
        return SQLiteStorage(db_path)
    return JSONStorage(config.storage_output_dir)
