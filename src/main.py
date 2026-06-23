import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from src.bots.feishu import FeishuBot
from src.core.config import Config
from src.core.models import TrendItem
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


def group_by_source(items: list[TrendItem]) -> dict[str, list[TrendItem]]:
    groups: dict[str, list[TrendItem]] = defaultdict(list)
    for item in items:
        groups[item.source].append(item)
    return dict(groups)


def build_review_markdown(items: list[TrendItem], title: str = "AI 趋势日报") -> str:
    """生成飞书文档用的 markdown 内容"""
    lines = [f"# {title}", f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC", ""]

    groups = group_by_source(items)
    source_labels = {
        "github_trends": "GitHub 热门仓库",
        "product_hunt": "Product Hunt 热门产品",
        "arxiv_ai": "arXiv AI/ML 论文",
        "huggingface_papers": "Hugging Face 每日论文",
    }

    for source, source_items in groups.items():
        label = source_labels.get(source, source)
        lines.append(f"## {label}（{len(source_items)} 条）")
        lines.append("")
        for idx, item in enumerate(source_items, 1):
            summary = item.summary[:400] + "..." if len(item.summary) > 400 else item.summary
            lines.append(f"### {idx}. {item.title}")
            if item.author:
                lines.append(f"作者/发布者：{item.author}")
            if summary:
                lines.append(summary)
            if item.url:
                lines.append(f"链接：{item.url}")
            if item.tags:
                lines.append(f"标签：{', '.join(item.tags[:8])}")
            if item.metrics:
                metrics_str = " | ".join(
                    f"{k}: {v}" for k, v in item.metrics.items()
                    if k not in ("raw_data", "categories", "topics") and not isinstance(v, list)
                )
                if metrics_str:
                    lines.append(f"指标：{metrics_str}")
            lines.append("")

    return "\n".join(lines)


def limit_per_source(items: list[TrendItem], limit: int) -> list[TrendItem]:
    """每个 source 最多保留 limit 条"""
    groups = group_by_source(items)
    result: list[TrendItem] = []
    for source_items in groups.values():
        result.extend(source_items[:limit])
    return result


def run_all(config: Config, push_feishu: bool = False, review: bool = False, limit: int = 5) -> list[TrendItem]:
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

    if not push_feishu or not all_items:
        return all_items

    bot = FeishuBot(config)
    if review:
        # 审阅模式：生成飞书文档，只发文档链接
        review_title = "AI 趋势日报 · 待审阅"
        markdown = build_review_markdown(all_items, review_title)
        doc_url = bot.create_document(review_title, markdown)
        if doc_url:
            bot.send_markdown(
                review_title,
                f"📄 今日共抓取 {len(all_items)} 条趋势数据，已整理成文档：\n\n[点击审阅]({doc_url})\n\n确认后可直接在群里转发，或回复我再发卡片。",
            )
        else:
            logger.warning("创建飞书文档失败，跳过推送")
    else:
        # 正常模式：每个源最多发 limit 条卡片
        display_items = limit_per_source(all_items, limit)
        bot.send_trend_items(display_items, title="AI 趋势日报")
        if len(display_items) < len(all_items):
            logger.info(f"群消息已折叠：展示 {len(display_items)}/{len(all_items)} 条")

    return all_items


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
        help="抓取完成后推送到飞书",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="审阅模式：生成飞书文档并发送链接，不直接发卡片到群",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="每个数据源最多展示几条（默认 5，仅普通推送模式生效）",
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

    if args.spider:
        items = run_spider(args.spider, config)
        if args.push and items:
            display_items = items[:args.limit] if not args.review else items
            bot = FeishuBot(config)
            if args.review:
                title = f"{args.spider} 更新（待审阅）"
                doc_url = bot.create_document(title, build_review_markdown(display_items, title))
                if doc_url:
                    bot.send_markdown(title, f"[点击审阅]({doc_url})")
            else:
                bot.send_trend_items(display_items, title=f"{args.spider} 更新")
        logger.info(f"共抓取 {len(items)} 条新数据")
    elif args.all:
        items = run_all(config, push_feishu=args.push, review=args.review, limit=args.limit)
        logger.info(f"所有爬虫共抓取 {len(items)} 条新数据")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
