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


MASTER_DOC_ID_FILE = "data/master_doc_id.txt"


def save_preview_file(items: list[TrendItem], top_items: list[TrendItem], date_str: str = "") -> Path:
    """把完整预览内容写到文件，方便用户查看不被截断的详细信息"""
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"preview_{date_str}.md"

    lines = [f"# AI 趋势日报完整预览 · {date_str}", ""]
    lines.append(f"共抓取 {len(items)} 条，精选 {len(top_items)} 条。\n")

    lines.append("## 精选条目（将推送到群）\n")
    for idx, item in enumerate(top_items, 1):
        lines.append(f"### {idx}. [{item.category}] {item.title}")
        if item.author:
            lines.append(f"来源：{item.author}")
        if item.summary:
            lines.append(item.summary)
        if item.url:
            lines.append(f"链接：{item.url}")
        if item.tags:
            lines.append(f"标签：{', '.join(item.tags)}")
        lines.append(f"相关度：{item.relevance_score:.2f}")
        lines.append("")

    lines.append("## 全部条目\n")
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}. [{item.category}] {item.title} — {str(item.url or '')}")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _load_master_doc_id() -> str | None:
    try:
        with open(MASTER_DOC_ID_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _save_master_doc_id(doc_id: str) -> None:
    Path(MASTER_DOC_ID_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_DOC_ID_FILE, "w", encoding="utf-8") as f:
        f.write(doc_id)


def get_or_create_master_doc(config: Config, bot: FeishuBot) -> str | None:
    """获取或创建主索引文档，返回 doc_id"""
    existing_id = _load_master_doc_id()
    if existing_id:
        return existing_id

    if not bot.is_configured():
        return None

    title = "AI 趋势日报索引"
    subscribe_url = config.get("feishu.subscribe_url", "")
    if subscribe_url:
        subscribe_line = f"\n**👉 [点击订阅每日 AI 趋势早报]({subscribe_url})**\n"
    else:
        subscribe_line = "\n**👉 订阅入口：** 请联系管理员添加 `feishu.subscribe_url`\n"
    markdown = f"# AI 趋势日报索引\n\n每天子文档链接汇总。{subscribe_line}\n"

    folder_token = config.get("feishu.folder_token", "")
    doc_url = bot.create_document(title, markdown, folder_token=folder_token)
    if not doc_url:
        return None

    doc_id = doc_url.split("/")[-1]
    _save_master_doc_id(doc_id)
    logger.info(f"主索引文档已创建：{doc_url}")
    return doc_id


def append_daily_to_master(master_doc_id: str, date_str: str, daily_url: str, bot: FeishuBot) -> bool:
    """在主索引文档中追加一条今日日报链接"""
    blocks = [
        {
            "block_type": 4,
            "heading2": {
                "elements": [{"text_run": {"content": date_str, "text_element_style": {}}}],
                "style": {"align": 1, "folded": False},
            },
        },
        {
            "block_type": 2,
            "text": {
                "elements": [
                    {"text_run": {"content": "今日日报：", "text_element_style": {}}},
                    {
                        "text_run": {
                            "content": daily_url,
                            "text_element_style": {"link": {"url": daily_url}},
                        }
                    },
                ],
                "style": {"align": 1, "folded": False},
            },
        },
    ]
    return bot.append_to_document(master_doc_id, blocks)


def create_knowledge_base_archive(config: Config, items: list[TrendItem], date_str: str = "") -> tuple[str | None, str | None]:
    """把完整日报写入飞书文档，并更新主索引。返回 (日报链接, 主索引链接)"""
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    bot = FeishuBot(config)
    if not bot.is_configured():
        logger.warning("飞书未配置，跳过知识库归档")
        return None, None

    # 创建当日子文档
    title = f"AI 趋势日报 · {date_str}"
    markdown = build_review_markdown(items, title)
    folder_token = config.get("feishu.folder_token", "")
    daily_url = bot.create_document(title, markdown, folder_token=folder_token)
    if not daily_url:
        return None, None

    # 更新主索引
    master_doc_id = get_or_create_master_doc(config, bot)
    if master_doc_id:
        append_daily_to_master(master_doc_id, date_str, daily_url, bot)
        master_url = f"https://www.feishu.cn/docx/{master_doc_id}"
        logger.info(f"主索引已更新：{master_url}")
        return daily_url, master_url

    return daily_url, None


def build_daily_brief(items: list[TrendItem], date_str: str = "", master_url: str = "", daily_url: str = "") -> str:
    """生成群聊用的中文精简日报"""
    from src.core.ranker import format_daily_brief

    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    brief = format_daily_brief(items, date_str)
    if master_url:
        brief += f"\n\n📁 完整日报索引：[查看全部]({master_url})"
    elif daily_url:
        brief += f"\n\n📄 完整日报：[查看]({daily_url})"
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
    daily_url, master_url = create_knowledge_base_archive(config, ranked, date_str)

    bot = FeishuBot(config)
    bot.send_daily_brief(top_items, date_str, master_url, daily_url)
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
            master_url = ""
            daily_url = ""
            if args.review:
                daily_url, master_url = create_knowledge_base_archive(config, ranked, date_str)
            brief = build_daily_brief(top_items, date_str, master_url or "", daily_url or "")
            preview_path = save_preview_file(items, top_items, date_str)
            print("\n========== 日报预览（精简版） ==========\n")
            print(brief)
            print("\n========================================\n")
            print(f"完整预览已保存到：{preview_path}")
            logger.info(f"预览完成：共 {len(items)} 条新数据，精选 {len(top_items)} 条")
            return

        if args.review or args.push:
            # 创建知识库文档
            daily_url, master_url = create_knowledge_base_archive(config, ranked, date_str)

            if args.review:
                # 只发文档链接
                bot = FeishuBot(config)
                link_url = master_url or daily_url
                bot.send_markdown(
                    f"AI 趋势日报 · {date_str}",
                    f"📄 今日共抓取 {len(items)} 条趋势数据，已整理成文档：\n\n[点击审阅]({link_url})",
                )
            elif args.push:
                # 发送精简日报到群
                bot = FeishuBot(config)
                bot.send_daily_brief(top_items, date_str, master_url or "", daily_url or "")

        logger.info(f"所有爬虫共抓取 {len(items)} 条新数据，精选 {len(top_items)} 条")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
