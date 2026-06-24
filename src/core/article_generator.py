from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from loguru import logger

from src.core.llm import LLMClient
from src.core.models import TrendItem


# Unsplash preset photo IDs mapped by AIHues article tag.
# Curated to avoid abstract/blank images and keep strong visual contrast.
UNSPLASH_PRESETS: dict[str, list[str]] = {
    "AI Tools": [
        "photo-1485827404703-89b55fcc595e",  # white robot
        "photo-1518770660439-4636190af475",  # circuit board
        "photo-1550751827-4bd374c3f58b",  # cybersecurity terminal
        "photo-1504639725590-34d0984388bd",  # laptop workspace
        "photo-1519389950473-47ba0277781c",  # team working
        "photo-1522202176988-66273c2fd55f",  # team at table
        "photo-1555949963-ff9fe0c870eb",  # code screen
        "photo-1531297484001-80022131f5a1",  # AI chip
        "photo-1526374965328-7f61d4dc18c5",  # server room
        "photo-1460925895917-afdab827c52f",  # analytics dashboard
    ],
    "AI Research": [
        "photo-1485827404703-89b55fcc595e",  # white robot
        "photo-1518770660439-4636190af475",  # circuit board
        "photo-1526374965328-7f61d4dc18c5",  # server room
        "photo-1531297484001-80022131f5a1",  # AI chip
        "photo-1550751827-4bd374c3f58b",  # cybersecurity terminal
        "photo-1504639725590-34d0984388bd",  # laptop workspace
        "photo-1555949963-ff9fe0c870eb",  # code screen
        "photo-1460925895917-afdab827c52f",  # analytics dashboard
    ],
    "Development": [
        "photo-1461749280684-dccba630e2f6",  # code editor
        "photo-1516116216624-53e697fedbea",  # code on screen
        "photo-1555066931-4365d14bab8c",  # laptop code
        "photo-1516321318423-f06f85e504b3",  # MacBook
        "photo-1555949963-ff9fe0c870eb",  # code screen
        "photo-1504639725590-34d0984388bd",  # laptop workspace
    ],
    "Growth": [
        "photo-1552664730-d307ca884978",
        "photo-1460925895917-afdab827c52f",
        "photo-1553877522-43269d4ea984",
        "photo-1531403009284-440f080d1e12",
        "photo-1559136555-9303baea8ebd",
        "photo-1542744173-8e7e53415bb0",
        "photo-1517245386807-bb43f82c33c4",
        "photo-1556761175-5973dc0f32e7",
    ],
    "Indie Dev": [
        "photo-1507003211169-0a1dd7228f2d",
        "photo-1517694712202-14dd9538aa97",
        "photo-1455390582262-044cdead277a",
        "photo-1498050108023-c5249f4df085",
        "photo-1522071820081-009f0129c71c",
        "photo-1521737711867-e3b97375f902",
        "photo-1542744173-8e7e53415bb0",
    ],
    "Productivity": [
        "photo-1484480974693-6ca0a78fb36b",
        "photo-1506784365847-bbad939e9335",
        "photo-1456324504439-367cee3b3c32",
        "photo-1434030216411-0b793f4b4173",
        "photo-1488190211105-8b0e65b80b4e",
        "photo-1517842645767-c639042777db",
        "photo-1499951360447-b19be8fe80f5",
    ],
    "SEO": [
        "photo-1432888498266-38ffec3eaf0a",
        "photo-1563986768609-322da13575f3",
        "photo-1553484771-371a605b060b",
        "photo-1551288049-bebda4e38f71",
    ],
    "Games": [
        "photo-1550745165-9bc0b252726f",  # retro arcade cabinet
        "photo-1511512578047-dfb367046420",  # game controller neon
        "photo-1606092195730-5d7b9af1efc5",  # puzzle pieces
        "photo-1529699211952-734e80c4d42b",  # chessboard strategy game
        "photo-1551103782-8ab07afd45c1",  # joystick close-up
        "photo-1611996575749-79a3a250f948",  # tabletop game pieces
        "photo-1542751371-adc38448a05e",  # esports / competition
        "photo-1493711662062-fa541adb3fc8",  # mobile game hand
    ],
}

DEFAULT_UNSPLASH = "photo-1485827404703-89b55fcc595e"

# Topic-specific cover images for better article-to-image relevance.
# When the title or summary contains one of these keywords, the matching photo IDs are tried first.
# Longer/more specific phrases are sorted first so they win over generic keywords.
_TOPIC_COVER_IMAGES: dict[str, list[str]] = {
    # Math / reasoning
    "mathematical reasoning": ["photo-1456513080510-7bf3a84b82f8"],
    "mathematical": ["photo-1456513080510-7bf3a84b82f8"],
    "reasoning": ["photo-1456513080510-7bf3a84b82f8"],
    "math": ["photo-1456513080510-7bf3a84b82f8", "photo-1503676260728-1c00da094a0b"],
    # AI memory / knowledge
    "ai memory": ["photo-1550751827-4bd374c3f58b"],
    "memory platform": ["photo-1550751827-4bd374c3f58b"],
    "knowledge graph": ["photo-1550751827-4bd374c3f58b"],
    "memory": ["photo-1550751827-4bd374c3f58b", "photo-1518770660439-4636190af475"],
    "knowledge": ["photo-1550751827-4bd374c3f58b"],
    # Cache / performance / multimodal
    "kv cache": ["photo-1526374965328-7f61d4dc18c5"],
    "cache": ["photo-1526374965328-7f61d4dc18c5", "photo-1550751827-4bd374c3f58b"],
    "multimodal": ["photo-1526374965328-7f61d4dc18c5", "photo-1531297484001-80022131f5a1"],
    # Photography / brand shoots
    "brand shoot": ["photo-1502982720700-bfff97f2ecac"],
    "photo shoot": ["photo-1502982720700-bfff97f2ecac"],
    "shoot production": ["photo-1502982720700-bfff97f2ecac"],
    "photography": ["photo-1502982720700-bfff97f2ecac", "photo-1452587925148-ce544e77e70d"],
    "camera": ["photo-1502982720700-bfff97f2ecac", "photo-1452587925148-ce544e77e70d"],
    "shoot": ["photo-1502982720700-bfff97f2ecac", "photo-1452587925148-ce544e77e70d"],
    "brand": ["photo-1502982720700-bfff97f2ecac"],
    # Presentation / slides
    "presentation": ["photo-1556761175-5973dc0f32e7", "photo-1552664730-d307ca884978"],
    "slide": ["photo-1556761175-5973dc0f32e7"],
    "deck": ["photo-1556761175-5973dc0f32e7", "photo-1552664730-d307ca884978"],
    # Games / interactive demos
    "game": ["photo-1550745165-9bc0b252726f", "photo-1511512578047-dfb367046420"],
    "arcade": ["photo-1550745165-9bc0b252726f"],
    "puzzle": ["photo-1606092195730-5d7b9af1efc5", "photo-1529699211952-734e80c4d42b"],
    "multiplayer": ["photo-1542751371-adc38448a05e"],
    "browser game": ["photo-1611996575749-79a3a250f948"],
    "interactive": ["photo-1551103782-8ab07afd45c1"],
    "demo": ["photo-1551103782-8ab07afd45c1"],
}

# Tags that should never be presented as product "capabilities".
_CAPABILITY_TAG_BLOCKLIST = {
    "product-hunt",
    "ai-product",
    "open-source",
    "github",
    "trending",
    "arxiv",
    "paper",
    # arXiv categories
    "cs.dc",
    "cs.ai",
    "cs.cl",
    "cs.cv",
    "cs.lg",
    "cs.se",
    "cs.cr",
    "cs.db",
    "cs.hc",
    "cs.ir",
    "cs.ma",
    "cs.mm",
    "cs.ne",
    "cs.os",
    "cs.ro",
    "cs.sd",
    "cs.sy",
    # Generic product categories that are not concrete capabilities
    "design tools",
    "productivity",
    "artificial intelligence",
    "saas",
    "developer tools",
    # Programming languages are not capabilities
    "python",
    "typescript",
    "javascript",
    "go",
    "golang",
    "rust",
    "java",
    "c++",
    "c#",
    "ruby",
    "php",
}


def _unsplash_url(photo_id: str, width: int = 1200) -> str:
    return f"https://images.unsplash.com/{photo_id}?w={width}&q=80"


def _choose_cover_image(tag: str, seed: str = "", summary: str = "", used: set[str] | None = None) -> str:
    """选择封面图，优先按标题+摘要主题匹配，再按 tag 默认池选择，并避开同一批次已使用的图片。"""
    if used is None:
        used = set()

    # 1. Try topic-specific matches based on title + summary for better relevance.
    text = ((seed or "") + " " + (summary or "")).lower().strip()
    topic_ids: list[str] = []
    if text:
        # Sort keywords by length descending so more specific phrases match first.
        for keyword in sorted(_TOPIC_COVER_IMAGES.keys(), key=len, reverse=True):
            if keyword in text:
                topic_ids.extend(_TOPIC_COVER_IMAGES[keyword])
        for photo_id in topic_ids:
            url = _unsplash_url(photo_id)
            if url not in used:
                used.add(url)
                return url

    # 2. Fall back to the tag-level preset pool.
    presets = UNSPLASH_PRESETS.get(tag, UNSPLASH_PRESETS.get("AI Tools", [DEFAULT_UNSPLASH]))
    start = int(hashlib.md5((seed or tag).encode("utf-8")).hexdigest(), 16) % len(presets) if (seed or tag) else 0

    for i in range(len(presets)):
        idx = (start + i) % len(presets)
        url = _unsplash_url(presets[idx])
        if url not in used:
            used.add(url)
            return url

    url = _unsplash_url(presets[start])
    used.add(url)
    return url


def _slugify(text: str) -> str:
    """生成 URL slug，限制 60 字符。"""
    slug = text.lower()
    slug = re.sub(r"<[^>]+>", "", slug)
    slug = re.sub(r"&[a-z]+;", " ", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:60].rstrip("-")


def _truncate(text: str, max_chars: int, suffix: str = "...") -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - len(suffix)].rsplit(" ", 1)[0] + suffix


def _strip_utm_params(url: str) -> str:
    """移除 URL 中的 UTM 等追踪参数。"""
    if not url:
        return url
    parsed = urlparse(str(url))
    if not parsed.query:
        return str(url)
    qs = parse_qs(parsed.query)
    clean = {k: v for k, v in qs.items() if not k.lower().startswith("utm_")}
    new_query = urlencode(clean, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _extract_host(url: str) -> str:
    """从 URL 中提取域名。"""
    try:
        parsed = urlparse(str(url))
        host = parsed.netloc.replace("www.", "")
        return host or "official site"
    except Exception:
        return "official site"


def _item_type(item: TrendItem) -> str:
    """统一读取 type 枚举值。"""
    return item.type.value if hasattr(item.type, "value") else str(item.type)


def _item_tag(item: TrendItem) -> str:
    """把 TrendItem 类型映射到 AIHues Resources 的 tag。"""
    mapping = {
        "ai_product": "AI Tools",
        "open_source": "Development",
        "research_paper": "AI Research",
        "tech_news": "AI Tools",
        "trend": "AI Tools",
        "games": "Games",
    }
    return mapping.get(_item_type(item), "AI Tools")


def _rich_summary(item: TrendItem) -> str:
    """优先使用更完整的原始描述（Product Hunt / GitHub 常有长描述）。"""
    summary = (item.summary or "").strip()
    raw = item.raw_data or {}
    # 支持 Product Hunt / GitHub 等嵌套结构
    candidates = []
    if isinstance(raw, dict):
        if isinstance(raw.get("node"), dict):
            candidates.append(raw["node"].get("description", ""))
        candidates.append(raw.get("description", ""))
    candidates = [c.strip() for c in candidates if c and isinstance(c, str)]

    # 选择最长的、且明显比 summary 更丰富的描述
    for cand in candidates:
        if len(cand) > len(summary) + 40:
            summary = cand
            break

    # 去除重复句（Product Hunt 描述常重复 tagline）
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    seen: set[str] = set()
    deduped: list[str] = []
    for s in sentences:
        norm = re.sub(r"\s+", " ", s.strip()).lower()
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(s.strip())
    return " ".join(deduped).strip() or (item.summary or "")


def _first_sentence(text: str) -> str:
    """提取文本的第一句，保留完整内容（不截断）。"""
    text = text.strip()
    if not text:
        return ""
    # 按句点/感叹号/问号分割，但保留小数点、缩写等
    match = re.match(r"([^\.!?]{4,}[\.!?])", text)
    sentence = match.group(1) if match else text
    return sentence.strip()


def _lcfirst(text: str) -> str:
    """将句子首字母小写，用于嵌入到已有句式中。"""
    text = text.strip()
    if not text:
        return text
    return text[0].lower() + text[1:]


def _filter_capability_tags(tags: list[str]) -> list[str]:
    """过滤掉无意义的标签，返回可作为能力展示的标签。"""
    cleaned: list[str] = []
    for t in tags:
        lower = t.lower().strip()
        if not lower or lower in _CAPABILITY_TAG_BLOCKLIST:
            continue
        if re.match(r"^cs\.[a-z]{1,3}$", lower):
            continue
        cleaned.append(t.strip())
    return cleaned[:6]


def _estimate_read_time(text: str) -> str:
    words = len(text.split())
    minutes = max(4, round(words / 200))
    return f"{minutes} min"


class ArticleGenerator:
    """基于 TrendItem 生成 AIHues Resources 风格的 SEO 文章。"""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        self.config = config or {}
        self.cta_link = self.config.get("aihues_cta_link", "/tools")
        self.games_cta_link = self.config.get("aihues_games_cta_link", "/games")
        self.cta_text = self.config.get("aihues_cta_text", "Browse AI Tools")
        self._used_cover_images: set[str] = set()

        # 标题改写：需要 LLM 配置且显式开启 rewrite_title
        self.llm_config = llm_config or {}
        self.rewrite_title_enabled = bool(
            self.llm_config.get("enabled") and self.llm_config.get("rewrite_title")
        )
        self._llm_client: LLMClient | None = LLMClient(self.llm_config) if self.rewrite_title_enabled else None

    def generate(self, item: TrendItem, date_str: str = "") -> dict[str, Any]:
        if not date_str:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

        item_type = _item_type(item)
        tag = _item_tag(item)
        original_title = item.title
        slug = _slugify(original_title)
        summary = _rich_summary(item)
        clean_url = _strip_utm_params(str(item.url) if item.url else "")
        host = _extract_host(clean_url)
        first_sentence = _first_sentence(summary)

        # 标题改写：用 LLM 生成更吸引人的标题；失败或未启用则回退到原标题
        display_title = original_title
        if self.rewrite_title_enabled and self._llm_client is not None:
            rewritten = self._llm_client.rewrite_title(item)
            if rewritten and rewritten.strip():
                display_title = rewritten.strip()

        # SEO / 页面标题：按类型选择最合适的后缀
        h1 = display_title
        if item_type == "research_paper":
            seo_title = f"{display_title} | AIHues"
            meta = _truncate(
                f"{first_sentence} This paper explores the idea and its practical implications.",
                160,
            )
            banner = _truncate(
                f"{first_sentence} Here is what the research proposes and why it matters.",
                300,
            )
        elif item_type == "open_source":
            seo_title = f"{display_title}: A Practical Guide | AIHues"
            meta = _truncate(
                f"{first_sentence} Learn what it does, who it is for, and how to get started.",
                160,
            )
            banner = _truncate(
                f"{first_sentence} This guide explains what it does, who it serves, and how to start using it.",
                300,
            )
        elif item_type == "games":
            seo_title = f"{display_title}: Play in Browser | AIHues"
            meta = _truncate(
                f"{first_sentence} Play this browser game instantly with no download required.",
                160,
            )
            banner = _truncate(
                f"{first_sentence} It is ready to play in your browser right now.",
                300,
            )
        else:
            seo_title = f"{display_title}: A Practical Guide | AIHues"
            meta = _truncate(
                f"{first_sentence} Learn what {original_title} does, who it is for, and how to get started.",
                160,
            )
            banner = _truncate(
                f"{first_sentence} This guide explains what it does, who it serves, and how to start using it.",
                300,
            )

        article = {
            "slug": slug,
            "tag": tag,
            "title": display_title,
            "original_title": original_title,
            "seo_title": seo_title,
            "meta_description": meta,
            "h1": h1,
            "banner": banner,
            "date": date_str,
            "read_time": _estimate_read_time(summary),
            "cover_image": _choose_cover_image(tag, seed=display_title, summary=summary, used=self._used_cover_images),
            "excerpt": _truncate(first_sentence, 160),
            "description": meta,
            "summary": summary,
            "first_sentence": first_sentence,
            "clean_url": clean_url,
            "host": host,
            "item": item,
            "faq": self._build_faq(item, summary, item_type, host, clean_url),
        }
        return article

    def render_html(self, article: dict[str, Any]) -> str:
        """渲染成 AIHues Resources 兼容的 HTML。"""
        item: TrendItem = article["item"]
        item_type = _item_type(item)
        tag = article["tag"]
        summary = article["summary"]
        first_sentence = article["first_sentence"]
        clean_url = article["clean_url"]
        host = article["host"]

        sections: list[str] = []

        # Intro: 不再重复标题，直接用第一句 + 类型化引导语
        if item_type == "research_paper":
            sections.append(
                f"<p>{first_sentence} This paper explores the proposed approach and its implications for AI systems.</p>"
            )
        elif item_type == "open_source":
            sections.append(
                f"<p>{first_sentence} This guide explains what it does, who it serves, and how to start using it.</p>"
            )
        elif item_type == "games":
            sections.append(
                f"<p>{first_sentence} It is ready to play in your browser, with no download or sign-up required.</p>"
            )
        else:
            sections.append(
                f"<p>{first_sentence} This guide explains what it does, who it serves, and how to start using it.</p>"
            )

        # CTA 1
        sections.append(self._cta_box_for_tag(tag, primary=True))

        # How it works / What it does / Key Idea
        sections.extend(self._build_main_sections(item, item_type, summary))

        # Limitations
        sections.append("<h2>Limitations to Know</h2>")
        if item_type == "research_paper":
            sections.append(
                f"<p>Like any research result, {item.title} has not been validated in every production setting. Reproduce the experiments on your own data and hardware before betting a production pipeline on it.</p>"
            )
        elif item_type == "games":
            sections.append(
                f"<p>Browser games vary in polish and device support. {item.title} may not work well on mobile or may have limited content compared to full releases. Try it on a desktop browser first for the best experience.</p>"
            )
        else:
            sections.append(
                f"<p>No tool fits every scenario. {item.title} may require manual setup for advanced integrations, and output quality depends on how clearly you define the task. Always test with your own data before relying on it for production work.</p>"
            )

        # Getting started
        sections.append("<h2>How to Get Started</h2>")
        sections.append("<ol>")
        if item_type == "research_paper":
            sections.append(f"<li>Read the abstract and introduction on <a href=\"{clean_url}\">{host}</a> to judge relevance.</li>")
            sections.append("<li>Download the PDF and check the method and experiments sections.</li>")
            sections.append("<li>Try reproducing the main result on a small public dataset.</li>")
            sections.append("<li>Adapt the idea to your own model or pipeline if the gains transfer.</li>")
        elif item_type == "games":
            sections.append(f"<li>Open <a href=\"{clean_url}\">{host}</a> in your browser.</li>")
            sections.append("<li>Read the short description or instructions on the project page.</li>")
            sections.append("<li>Click play and try a quick round to see if the mechanics suit you.</li>")
            sections.append("<li>Share feedback with the creator on Hacker News if you enjoy it.</li>")
        else:
            sections.append(f"<li>Visit <a href=\"{clean_url}\">{clean_url}</a> to create an account or view the repository.</li>")
            sections.append("<li>Explore the official documentation or README for setup steps.</li>")
            sections.append("<li>Run a small test project that matches your real use case.</li>")
            sections.append("<li>Iterate based on results before scaling to a full workflow.</li>")
        sections.append("</ol>")

        # FAQ
        faq = article.get("faq") or []
        if faq:
            sections.append("<h2>FAQ</h2>")
            for q in faq:
                sections.append(f"<h3>{q['q']}</h3>")
                sections.append(f"<p>{q['a']}</p>")

        # Conclusion
        sections.append("<h2>Conclusion</h2>")
        if item_type == "research_paper":
            sections.append(
                f"<p>{item.title} offers a practical angle on {first_sentence.rstrip('.')}. If you are building or optimizing AI systems, it is worth reading the full paper and testing whether the results transfer to your setup.</p>"
            )
        elif item_type == "games":
            sections.append(
                f"<p>{first_sentence} It is a nice break from work and a good example of what a small team can ship to the web. Visit <a href=\"{clean_url}\">{host}</a> to play it yourself.</p>"
            )
        else:
            sections.append(
                f"<p>{first_sentence} It works best when you match its strengths to your actual workflow. Visit <a href=\"{clean_url}\">{host}</a> to learn more and try it yourself.</p>"
            )

        # CTA 2
        sections.append(self._cta_box_for_tag(tag, primary=False))

        body = "\n\n".join(sections)
        cover_image = article["cover_image"]

        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{article['seo_title']}</title>
    <meta name="description" content="{article['meta_description']}" />
    <style>
      *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
      :root {{
        --bg: #faf9f6; --surface: #ffffff; --surface-hover: #f5f0e8;
        --border: #e8e2d9; --border-hover: #d4c8b8;
        --text: #1c1917; --text-secondary: #78716c; --text-muted: #a8a29e;
        --accent: #b45309; --accent-light: #d97706;
        --accent-gradient: linear-gradient(135deg, #b45309, #d97706);
        --radius: 14px; --radius-sm: 10px;
        --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.04);
        --shadow-lg: 0 8px 32px rgba(180,83,9,0.18);
      }}
      body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; -webkit-font-smoothing: antialiased; }}
      a {{ color: var(--accent); text-decoration: none; }}
      .article {{ max-width: 720px; margin: 0 auto; padding: 80px 28px 40px; }}
      .article-header {{ text-align: center; margin-bottom: 40px; }}
      .article-cover {{ width: 100%; height: 320px; object-fit: cover; border-radius: var(--radius); margin-bottom: 40px; }}
      .article-tag {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; background: rgba(180,83,9,0.08); color: var(--accent); margin-bottom: 16px; }}
      .article h1 {{ font-size: 32px; font-weight: 800; line-height: 1.15; letter-spacing: -1px; margin-bottom: 12px; }}
      .article-header p {{ color: #3d3d3d; font-size: 15px; }}
      .article-meta {{ display: flex; justify-content: center; gap: 16px; font-size: 13px; color: var(--text-muted); margin-top: 16px; }}
      .article h2 {{ font-size: 28px; font-weight: 700; line-height: 1.2; letter-spacing: -0.5px; margin: 48px 0 16px; padding-bottom: 12px; border-bottom: 1px solid #e5e5e5; color: #1c1917; }}
      .article h3 {{ font-size: 20px; font-weight: 600; line-height: 1.3; letter-spacing: -0.3px; margin: 32px 0 12px; color: #1c1917; }}
      .article p {{ margin-bottom: 16px; color: #3d3d3d; font-size: 16px; line-height: 1.75; }}
      .article ul, .article ol {{ margin: 0 0 16px 24px; color: #3d3d3d; font-size: 15px; }}
      .article li {{ margin-bottom: 8px; line-height: 1.75; }}
      .article strong {{ color: #1c1917; font-weight: 600; }}
      .cta-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 28px; margin: 40px 0; text-align: center; }}
      .cta-box h3 {{ font-size: 20px; font-weight: 700; margin-bottom: 8px; }}
      .cta-box p {{ color: var(--text-secondary); margin-bottom: 16px; }}
      .cta-btn {{ display: inline-block; padding: 12px 24px; border-radius: var(--radius-sm); background: var(--accent-gradient); color: #fff; font-weight: 600; font-size: 14px; transition: transform 0.2s, box-shadow 0.2s; }}
      .cta-btn:hover {{ transform: translateY(-1px); box-shadow: var(--shadow-lg); }}
      .comparison-table {{ width: 100%; border-collapse: collapse; margin: 24px 0; font-size: 14px; }}
      .comparison-table th, .comparison-table td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); }}
      .comparison-table th {{ background: var(--surface); font-weight: 600; color: #1c1917; }}
      .comparison-table tr:hover {{ background: var(--surface-hover); }}
      .footer {{ text-align: center; padding: 40px 28px; font-size: 13px; color: var(--text-muted); border-top: 1px solid var(--border); }}
    </style>
  </head>
  <body>
    <article class="article">
      <div class="article-header">
        <span class="article-tag">{article['tag']}</span>
        <h1>{article['h1']}</h1>
        <p>{article['banner']}</p>
        <div class="article-meta">
          <span>{article['date']}</span><span>{article['read_time']} read</span><span>AIHues Team</span>
        </div>
      </div>
      <img class="article-cover" src="{cover_image}" alt="{article['h1']}" />

      <div class="article-content">
{self._indent(body, 8)}
      </div>
    </article>
    <footer class="footer">© 2026 AIHues · Built with Kimi</footer>
  </body>
</html>
"""

    def _build_main_sections(self, item: TrendItem, item_type: str, summary: str) -> list[str]:
        """生成 How It Works / Key Idea / Key Capabilities / Use Cases 等主体段落。"""
        sections: list[str] = []
        first_sentence = _first_sentence(summary)

        if item_type == "research_paper":
            sections.append("<h2>Key Idea</h2>")
            sections.append(f"<p>{first_sentence}</p>")
            sections.append("<h3>Why It Matters</h3>")
            sections.append("<ul>")
            sections.append("<li>It addresses a concrete bottleneck in current AI systems rather than an abstract improvement.</li>")
            sections.append("<li>It proposes a training-free or lightweight intervention that can plug into existing pipelines.</li>")
            sections.append("<li>It includes reproducible experiments and benchmarks on public datasets.</li>")
            sections.append("<li>The released code and traces make it easier to verify and extend.</li>")
            sections.append("</ul>")
        elif item_type == "games":
            sections.append("<h2>What It Is</h2>")
            sections.append(f"<p>{first_sentence} It runs in the browser and is ready to play without downloads or sign-ups.</p>")
            capability_tags = _filter_capability_tags(item.tags)
            if capability_tags:
                sections.append("<h3>Tags</h3>")
                sections.append("<ul>")
                for tag in capability_tags:
                    sections.append(f"<li>{tag}</li>")
                sections.append("</ul>")
            sections.append("<h3>Why Play It</h3>")
            sections.append("<ul>")
            sections.append("<li>Quick to start — no installation needed</li>")
            sections.append("<li>Built for short, satisfying sessions</li>")
            sections.append("<li>Showcases a creative use of web technology</li>")
            sections.append("<li>Great for a break or a quick challenge</li>")
            sections.append("</ul>")
        elif item_type == "open_source":
            sections.append("<h2>What It Does</h2>")
            sections.append(f"<p>{first_sentence} You can self-host it, inspect the source, and adapt it to your own stack.</p>")
            capability_tags = _filter_capability_tags(item.tags)
            if capability_tags:
                sections.append("<h3>Key Capabilities</h3>")
                sections.append("<ul>")
                for tag in capability_tags:
                    sections.append(f"<li>{tag}</li>")
                sections.append("</ul>")
            sections.append("<h3>Common Use Cases</h3>")
            sections.append("<ul>")
            sections.append("<li>Self-hosting services without vendor lock-in</li>")
            sections.append("<li>Customizing behavior through source code</li>")
            sections.append("<li>Learning from community contributions</li>")
            sections.append("<li>Integrating into existing DevOps pipelines</li>")
            sections.append("</ul>")
        else:
            sections.append("<h2>How It Works</h2>")
            sections.append(f"<p>{first_sentence} It turns your input into a useful result, and most users can start without writing code or configuring complex settings.</p>")
            capability_tags = _filter_capability_tags(item.tags)
            if capability_tags:
                sections.append("<h3>Key Capabilities</h3>")
                sections.append("<ul>")
                for tag in capability_tags:
                    sections.append(f"<li>{tag}</li>")
                sections.append("</ul>")
            sections.append("<h3>Common Use Cases</h3>")
            sections.append("<ul>")
            sections.append("<li>Creating internal tools or client portals</li>")
            sections.append("<li>Automating form-based workflows</li>")
            sections.append("<li>Generating content or design drafts</li>")
            sections.append("<li>Connecting with existing SaaS stacks</li>")
            sections.append("</ul>")

        return sections

    def _build_faq(
        self,
        item: TrendItem,
        summary: str,
        item_type: str,
        host: str,
        clean_url: str,
    ) -> list[dict[str, str]]:
        first_sentence = _first_sentence(summary)
        if item_type == "research_paper":
            return [
                {"q": f"What problem does {item.title} solve?", "a": first_sentence},
                {"q": f"Who is {item.title} most relevant for?", "a": f"Researchers and engineers working on related AI problems who want a reproducible, training-free angle on {_lcfirst(first_sentence.rstrip('.'))}."},
                {"q": "Where can I read the full paper?", "a": f"You can find the paper on <a href=\"{clean_url}\">{host}</a>."},
            ]
        if item_type == "games":
            return [
                {"q": f"What is {item.title}?", "a": first_sentence},
                {"q": f"Do I need to install anything to play {item.title}?", "a": f"No. You can play it directly in your browser at <a href=\"{clean_url}\">{host}</a>."},
                {"q": f"Is {item.title} free to play?", "a": "Most Show HN browser games are free to play. Check the project page for any premium features or donations."},
            ]
        if item_type == "open_source":
            return [
                {"q": f"What license does {item.title} use?", "a": f"Check the repository on <a href=\"{clean_url}\">{host}</a> for the exact open-source license."},
                {"q": f"How do I install {item.title}?", "a": f"Installation steps are usually in the README on <a href=\"{clean_url}\">{host}</a>. Most projects support package managers or Docker."},
                {"q": f"Is {item.title} production-ready?", "a": "Review recent releases, issues, and community activity on the repository to assess maturity."},
            ]
        return [
            {"q": f"What is {item.title}?", "a": first_sentence},
            {"q": f"Who is {item.title} best for?", "a": f"It suits teams and individuals looking for {_lcfirst(first_sentence.rstrip('.'))} without building from scratch."},
            {"q": f"Do I need coding skills to use {item.title}?", "a": f"Most products in this category target non-technical users, but check the official docs on <a href=\"{clean_url}\">{host}</a> for advanced customizations."},
        ]

    def _cta_box_for_tag(self, tag: str, primary: bool = True) -> str:
        """根据文章 tag 选择更贴切的 CTA 文案。"""
        if tag == "AI Research":
            if primary:
                return self._cta_box(
                    "Explore AI Research",
                    "Discover recent papers and ideas shaping AI systems.",
                    button_text="Browse AI Research",
                )
            return self._cta_box(
                "Browse AI Research",
                "Find more research summaries relevant to your work.",
                button_text="Browse AI Research",
            )
        if tag == "Development":
            if primary:
                return self._cta_box(
                    "Explore Open Source",
                    "Discover dev tools and libraries you can self-host.",
                    button_text="Browse Dev Tools",
                )
            return self._cta_box(
                "Browse Dev Tools",
                "Find more open-source projects for your stack.",
                button_text="Browse Dev Tools",
            )
        if tag == "Games":
            if primary:
                return self._cta_box(
                    "Play Mini Games",
                    "Take a break with browser games that need no install.",
                    button_text="Browse Games",
                    link=self.games_cta_link,
                )
            return self._cta_box(
                "Browse Games",
                "Find more quick browser games to play.",
                button_text="Browse Games",
                link=self.games_cta_link,
            )
        if primary:
            return self._cta_box(
                "Find More AI Tools",
                "Discover AI-powered tools and resources that match your workflow.",
                button_text="Browse AI Tools",
            )
        return self._cta_box(
            "Browse AI Tools",
            "Find the right AI tool for your next project.",
            button_text="Browse AI Tools",
        )

    def _cta_box(
        self,
        heading: str,
        subtext: str,
        button_text: str = "",
        link: str = "",
    ) -> str:
        if not button_text:
            button_text = self.cta_text
        if not link:
            link = self.cta_link
        return f"""<div class="cta-box">
          <h3>{heading}</h3>
          <p>{subtext}</p>
          <a href="{link}" class="cta-btn">{button_text} →</a>
        </div>"""

    @staticmethod
    def _indent(text: str, spaces: int) -> str:
        prefix = " " * spaces
        return "\n".join(prefix + line for line in text.split("\n"))

    def to_posts_json_entry(self, article: dict[str, Any]) -> dict[str, Any]:
        return {
            "slug": article["slug"],
            "tag": article["tag"],
            "title": article["title"],
            "excerpt": article["excerpt"],
            "date": article["date"],
            "readTime": article["read_time"],
            "coverImage": article["cover_image"],
            "description": article["description"],
        }
