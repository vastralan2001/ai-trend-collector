#!/usr/bin/env python3
"""
Generate AIHues Resources articles from ai-trend-collector daily hot trends.

Usage:
    python scripts/generate-aihues-articles.py [--date YYYY-MM-DD] [--limit 5] [--dry-run]

Behavior:
    - Reads trend items from ai-trend-collector/data/{date}/
    - Selects top N items with category diversity
    - Generates SEO articles in template mode
    - Writes HTML files to ../apps/aihues-web/public/resources/{slug}.html
    - Appends metadata to ../apps/aihues-web/content/resources/posts.json
    - In --dry-run mode, writes to a staging directory instead and does not touch AIHues repo
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

# Allow importing src from the script location
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.article_generator import ArticleGenerator
from src.core.config import Config
from src.core.models import TrendItem
from src.core.storage import create_storage


AIHUES_REPO = PROJECT_ROOT.parent  # ai-trend-collector is inside AIHues repo
RESOURCES_DIR = AIHUES_REPO / "apps" / "aihues-web" / "public" / "resources"
POSTS_JSON = AIHUES_REPO / "apps" / "aihues-web" / "content" / "resources" / "posts.json"
STAGING_DIR = PROJECT_ROOT / "staging" / "aihues-articles"


def setup_logging(verbose: bool = False) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
    )


def load_trend_items(date_str: str, config: Config) -> list[TrendItem]:
    """加载指定日期的所有趋势条目。"""
    storage = create_storage(config)
    items = storage.list_items(limit=1000)
    # 只保留抓取日期匹配或发布日期匹配的条目
    result: list[TrendItem] = []
    for item in items:
        fetched_date = item.fetched_at.strftime("%Y-%m-%d")
        published_date = item.published_at.strftime("%Y-%m-%d") if item.published_at else ""
        if fetched_date == date_str or published_date == date_str:
            result.append(item)
    return result


def select_items(items: list[TrendItem], limit: int = 5, max_per_category: int = 2) -> list[TrendItem]:
    """按相关度排序，尽量保证分类多样性。"""
    from src.core.ranker import rank_items

    ranked = rank_items(items)
    selected: list[TrendItem] = []
    category_counts: dict[str, int] = {}
    remaining: list[TrendItem] = []

    for item in ranked:
        cat = item.category or "资讯"
        if category_counts.get(cat, 0) < max_per_category and len(selected) < limit:
            selected.append(item)
            category_counts[cat] = category_counts.get(cat, 0) + 1
        else:
            remaining.append(item)

    while len(selected) < limit and remaining:
        selected.append(remaining.pop(0))

    selected.sort(key=lambda x: x.relevance_score, reverse=True)
    return selected


def load_existing_slugs() -> set[str]:
    """加载 AIHues Resources 已有的 slug，避免覆盖。"""
    slugs: set[str] = set()
    if POSTS_JSON.exists():
        with open(POSTS_JSON, "r", encoding="utf-8") as f:
            posts = json.load(f)
        slugs = {p["slug"] for p in posts}
    return slugs


def write_articles(
    articles: list[dict[str, Any]],
    posts_entries: list[dict[str, Any]],
    dry_run: bool = False,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """写入 HTML 文件并更新 posts.json。"""
    output_dir = STAGING_DIR / datetime.utcnow().strftime("%Y-%m-%d") if dry_run else RESOURCES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    for article in articles:
        path = output_dir / f"{article['slug']}.html"
        path.write_text(article["html"], encoding="utf-8")
        written_paths.append(path)
        logger.info(f"Wrote {path}")

    if dry_run:
        # 在 staging 中保存一份 posts.json 预览
        preview_json = output_dir / "posts-preview.json"
        preview_json.write_text(json.dumps(posts_entries, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Dry-run: preview metadata saved to {preview_json}")
        return written_paths, posts_entries

    # 更新 AIHues posts.json
    posts: list[dict[str, Any]] = []
    if POSTS_JSON.exists():
        with open(POSTS_JSON, "r", encoding="utf-8") as f:
            posts = json.load(f)

    # 新条目放在最前面
    new_posts = posts_entries + posts

    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(new_posts, f, ensure_ascii=False, indent=2)

    logger.info(f"Updated {POSTS_JSON} with {len(posts_entries)} new articles")
    return written_paths, new_posts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AIHues articles from daily trends")
    parser.add_argument("--date", type=str, default=datetime.utcnow().strftime("%Y-%m-%d"), help="Target date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=5, help="Number of articles to generate")
    parser.add_argument("--dry-run", action="store_true", help="Write to staging dir instead of AIHues repo")
    parser.add_argument("--config", type=str, default="config/config.yaml", help="Config file path")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    config_path = PROJECT_ROOT / args.config
    if not config_path.exists():
        logger.error(f"Config not found: {config_path}")
        sys.exit(1)

    config = Config(config_path)

    items = load_trend_items(args.date, config)
    if not items:
        logger.warning(f"No trend items found for {args.date}")
        sys.exit(0)

    logger.info(f"Found {len(items)} trend items for {args.date}")

    selected = select_items(items, limit=args.limit)
    logger.info(f"Selected {len(selected)} items to generate articles")

    existing_slugs = load_existing_slugs()
    generator = ArticleGenerator(config.raw.get("article_generation", {}))

    articles: list[dict[str, Any]] = []
    posts_entries: list[dict[str, Any]] = []

    for item in selected:
        article = generator.generate(item, date_str=args.date)
        if article["slug"] in existing_slugs:
            logger.warning(f"Skipping {article['slug']}: already exists in AIHues")
            continue
        article["html"] = generator.render_html(article)
        articles.append(article)
        posts_entries.append(generator.to_posts_json_entry(article))
        existing_slugs.add(article["slug"])

    if not articles:
        logger.info("No new articles to generate (all slugs already exist)")
        sys.exit(0)

    written_paths, _ = write_articles(articles, posts_entries, dry_run=args.dry_run)

    print("\n========== Generated Articles ==========\n")
    for idx, article in enumerate(articles, 1):
        print(f"{idx}. [{article['tag']}] {article['title']}")
        print(f"   slug: {article['slug']}")
        print(f"   file: {written_paths[idx - 1]}")
        print()

    if args.dry_run:
        print("Dry-run complete. Articles staged for review.")
        print(f"Staging directory: {STAGING_DIR / args.date}")
    else:
        print(f"Articles written to {RESOURCES_DIR}")
        print(f"Remember to run: pnpm check && pnpm moon run aihues-web:build")


if __name__ == "__main__":
    main()
