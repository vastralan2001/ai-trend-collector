import argparse
import sys
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


def run_all(config: Config, push_feishu: bool = False) -> list[TrendItem]:
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

    if push_feishu and all_items:
        bot = FeishuBot(config)
        bot.send_trend_items(all_items)

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
            FeishuBot(config).send_trend_items(items, title=f"{args.spider} 更新")
        logger.info(f"共抓取 {len(items)} 条新数据")
    elif args.all:
        items = run_all(config, push_feishu=args.push)
        logger.info(f"所有爬虫共抓取 {len(items)} 条新数据")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
