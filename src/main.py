from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import schedule
from loguru import logger

from src.bots.feishu import FeishuBot
from src.core.config import Config
from src.core.models import TrendItem
from src.core.ranker import rank_items, select_top_items
from src.core.storage import create_storage
from src.spiders.arxiv_ai import ArxivAISpider
from src.spiders.github_trends import GitHubTrendsSpider
from src.spiders.huggingface_papers import HuggingfacePapersSpider
from src.spiders.product_hunt import ProductHuntSpider

# 爬虫注册表
SPIDER_REGISTRY: dict[str, type] = {
    "github_trends": GitHubTrendsSpider,
    "product_hunt": ProductHuntSpider,
    "arxiv_ai": ArxivAISpider,
    "huggingface_papers": HuggingfacePapersSpider,
}


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


def run_spider(name: str, config: Config, **kwargs: Any) -> list[TrendItem]:
    if name not in SPIDER_REGISTRY:
        raise ValueError(f"未知爬虫：{name}。可用：{', '.join(SPIDER_REGISTRY.keys())}")

    spider_cls = SPIDER_REGISTRY[name]
    storage = create_storage(config)
    spider = spider_cls(config, storage)
    return spider.run(**kwargs)


def run_all_spiders(config: Config) -> list[TrendItem]:
    """运行所有启用的爬虫，返回当天所有新条目"""
    all_items: list[TrendItem] = []
    for name in SPIDER_REGISTRY:
        source_config = config.source_config(name)
        if not source_config.get("enabled", True):
            logger.info(f"跳过未启用的爬虫：{name}")
            continue
        try:
            items = run_spider(name, config)
            all_items.extend(items)
        except Exception as e:
            logger.error(f"运行 {name} 失败：{e}")
    return all_items


def build_review_markdown(items: list[TrendItem], title: str = "AI 趋势日报") -> str:
    """生成飞书知识库归档用的完整 markdown 内容"""
    from collections import defaultdict

    lines = [f"# {title}", f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC", ""]

    groups: dict[str, list[TrendItem]] = defaultdict(list)
    for item in items:
        groups[item.category or item.source].append(item)

    category_order = ["AI产品", "论文", "开源项目", "竞对资讯", "资讯"]
    for category in category_order:
        if category not in groups:
            continue
        source_items = groups.pop(category)
        lines.append(f"## {category}（{len(source_items)} 条）")
        lines.append("")
        for idx, item in enumerate(source_items, 1):
            summary = item.summary[:500] + "..." if len(item.summary) > 500 else item.summary
            lines.append(f"### {idx}. {item.title}")
            if item.author:
                lines.append(f"来源：{item.author}")
            if summary:
                lines.append(summary)
            if item.url:
                lines.append(f"链接：{item.url}")
            lines.append("")

    # 其他未分类的
    for category, source_items in groups.items():
        lines.append(f"## {category}（{len(source_items)} 条）")
        lines.append("")
        for idx, item in enumerate(source_items, 1):
            summary = item.summary[:500] + "..." if len(item.summary) > 500 else item.summary
            lines.append(f"### {idx}. {item.title}")
            if item.author:
                lines.append(f"来源：{item.author}")
            if summary:
                lines.append(summary)
            if item.url:
                lines.append(f"链接：{item.url}")
            lines.append("")

    return "\n".join(lines)


def create_knowledge_base_archive(config: Config, items: list[TrendItem], date_str: str = "") -> str | None:
    """把完整日报写入飞书文档，返回文档链接"""
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    bot = FeishuBot(config)
    if not bot.is_configured():
        logger.warning("飞书未配置，跳过知识库归档")
        return None

    title = f"AI 趋势日报 · {date_str}"
    markdown = build_review_markdown(items, title)
    folder_token = config.get("feishu.folder_token", "")
    return bot.create_document(title, markdown, folder_token=folder_token)


def build_daily_brief(items: list[TrendItem], date_str: str = "", kb_url: str = "") -> str:
    """生成群聊用的中文精简日报"""
    from src.core.ranker import format_daily_brief

    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    brief = format_daily_brief(items, date_str)
    if kb_url:
        brief += f"\n\n完整日报已归档至飞书知识库：[查看]({kb_url})"
    return brief


def daily_job(config: Config, limit: int = 5) -> None:
    """每日任务：抓取 → 归档 → 推送"""
    logger.info("开始执行每日定时任务")
    items = run_all_spiders(config)
    if not items:
        logger.info("今日无新数据，跳过推送")
        return

    ranked = rank_items(items)
    top_items = select_top_items(ranked, total=limit, max_per_category=2)

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    kb_url = create_knowledge_base_archive(config, ranked, date_str)

    bot = FeishuBot(config)
    bot.send_daily_brief(top_items, date_str, kb_url)
    logger.info(f"每日推送完成：{len(top_items)} 条资讯")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Trend Collector — AI 趋势爬虫")
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yaml",
        help="配置文件路径（默认：config/config.yaml）",
    )
    parser.add_argument(
        "--spider",
        type=str,
        choices=list(SPIDER_REGISTRY.keys()),
        help="指定运行单个爬虫",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="运行所有启用的爬虫",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="抓取完成后推送到飞书群（生产模式）",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="仅在控制台打印日报预览，不发送",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="生成飞书知识库文档并发送链接到群",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="每日群聊推送条数（默认 5）",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="启动定时调度器，按配置时间自动运行",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用爬虫",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出 DEBUG 日志",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.list:
        print("可用爬虫：")
        for name in SPIDER_REGISTRY:
            print(f"  - {name}")
        return

    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"配置文件不存在：{config_path}")
        logger.info("请复制 config/config.example.yaml 为 config/config.yaml 并填写配置")
        sys.exit(1)

    config = Config(config_path)

    if args.daemon:
        schedule_time = config.get("schedule.time", "10:00")
        logger.info(f"启动定时调度器，每天 {schedule_time} 执行")
        schedule.every().day.at(schedule_time).do(daily_job, config, args.limit)
        while True:
            schedule.run_pending()
            time.sleep(60)
        return

    if args.spider:
        items = run_spider(args.spider, config)
        logger.info(f"共抓取 {len(items)} 条新数据")
        return

    if args.all or args.push or args.preview or args.review:
        items = run_all_spiders(config)
        if not items:
            logger.info("今日无新数据")
            return

        ranked = rank_items(items)
        top_items = select_top_items(ranked, total=args.limit, max_per_category=2)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

        if args.preview:
            # 仅控制台预览
            kb_url = ""
            if args.review:
                kb_url = create_knowledge_base_archive(config, ranked, date_str) or ""
            brief = build_daily_brief(top_items, date_str, kb_url)
            print("\n========== 日报预览 ==========\n")
            print(brief)
            print("\n==============================\n")
            logger.info(f"预览完成：共 {len(items)} 条新数据，精选 {len(top_items)} 条")
            return

        if args.review or args.push:
            # 创建知识库文档
            kb_url = create_knowledge_base_archive(config, ranked, date_str)

            if args.review:
                # 只发文档链接
                bot = FeishuBot(config)
                bot.send_markdown(
                    f"AI 趋势日报 · {date_str}",
                    f"📄 今日共抓取 {len(items)} 条趋势数据，已整理成文档：\n\n[点击审阅]({kb_url})",
                )
            elif args.push:
                # 发送精简日报到群
                bot = FeishuBot(config)
                bot.send_daily_brief(top_items, date_str, kb_url)

        logger.info(f"所有爬虫共抓取 {len(items)} 条新数据，精选 {len(top_items)} 条")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
