from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.models import TrendItem


# Unsplash preset photo IDs mapped by AIHues article tag.
# Reuses the same high-quality IDs from AIHues generate-blogs-v3.cjs.
UNSPLASH_PRESETS: dict[str, list[str]] = {
    "AI Tools": [
        "photo-1485827404703-89b55fcc595e",
        "photo-1518770660439-4636190af475",
        "photo-1555949963-ff9fe0c870eb",
        "photo-1526374965328-7f61d4dc18c5",
        "photo-1504639725590-34d0984388bd",
    ],
    "Growth": [
        "photo-1552664730-d307ca884978",
        "photo-1460925895917-afdab827c52f",
        "photo-1553877522-43269d4ea984",
    ],
    "Indie Dev": [
        "photo-1507003211169-0a1dd7228f2d",
        "photo-1517694712202-14dd9538aa97",
        "photo-1455390582262-044cdead277a",
    ],
    "Productivity": [
        "photo-1484480974693-6ca0a78fb36b",
        "photo-1506784365847-bbad939e9335",
        "photo-1456324504439-367cee3b3c32",
    ],
    "SEO": [
        "photo-1432888498266-38ffec3eaf0a",
        "photo-1563986768609-322da13575f3",
    ],
    "Development": [
        "photo-1461749280684-dccba630e2f6",
        "photo-1555949963-ff9fe0c870eb",
        "photo-1516321318423-f06f85e504b3",
    ],
}

DEFAULT_UNSPLASH = "photo-1485827404703-89b55fcc595e"


def _unsplash_url(photo_id: str, width: int = 1200) -> str:
    return f"https://images.unsplash.com/{photo_id}?w={width}&q=80"


def _choose_cover_image(tag: str, seed: str = "") -> str:
    presets = UNSPLASH_PRESETS.get(tag, [DEFAULT_UNSPLASH])
    idx = sum(ord(c) for c in seed) % len(presets) if seed else 0
    return _unsplash_url(presets[idx])


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


def _extract_host(url: str) -> str:
    """从 URL 中提取域名。"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(str(url))
        host = parsed.netloc.replace("www.", "")
        return host or "official site"
    except Exception:
        return "official site"


def _category_to_tag(category: str, source: str) -> str:
    """把 TrendItem 分类映射到 AIHues Resources 的 tag。"""
    mapping = {
        "AI产品": "AI Tools",
        "开源项目": "Development",
        "论文": "AI Tools",
        "竞对资讯": "Growth",
        "资讯": "AI Tools",
    }
    return mapping.get(category, "AI Tools")


def _build_comparison_table(item: TrendItem) -> list[dict[str, str]] | None:
    """根据产品类型返回竞品对比行。"""
    if item.category == "AI产品":
        return [
            {"tool": item.title, "best_for": "Focus of this article", "price": "See official site", "difference": "AI-powered workflow from prompts"},
            {"tool": "Bubble", "best_for": "Complex web and mobile SaaS", "price": "$29/mo", "difference": "Full visual programming"},
            {"tool": "Zapier", "best_for": "Workflow automation", "price": "$19.99/mo", "difference": "Connects apps without building UI"},
            {"tool": "Airtable", "best_for": "Database-powered apps", "price": "$20/mo", "difference": "Spreadsheet-style backend + interfaces"},
        ]
    if item.category == "开源项目":
        return [
            {"tool": item.title, "best_for": "Focus of this article", "price": "Open source", "difference": "Community-driven, self-hostable"},
            {"tool": "Vercel", "best_for": "Frontend deployments", "price": "Free tier", "difference": "Managed hosting for frameworks"},
            {"tool": "Docker", "best_for": "Containerized apps", "price": "Free tier", "difference": "Standard container runtime"},
            {"tool": "GitHub Actions", "best_for": "CI/CD", "price": "Free tier", "difference": "Built into GitHub repositories"},
        ]
    return None


def _build_faq(item: TrendItem) -> list[dict[str, str]]:
    """基于条目信息生成通用 FAQ。"""
    title = item.title
    host = _extract_host(item.url or "")
    if item.category == "AI产品":
        return [
            {"q": f"Is {title} free to use?", "a": f"Pricing varies by plan. Visit {host} for current free-tier limits and paid options."},
            {"q": f"Who is {title} best for?", "a": f"It suits teams and individuals looking for {item.summary.lower()} without building from scratch."},
            {"q": f"Do I need coding skills to use {title}?", "a": "Most AI app builders target non-technical users, but check the official docs for advanced customizations."},
        ]
    if item.category == "开源项目":
        return [
            {"q": f"What license does {title} use?", "a": f"Check the repository on {host} for the exact open-source license."},
            {"q": f"How do I install {title}?", "a": f"Installation steps are usually in the README on {host}. Most projects support package managers or Docker."},
            {"q": f"Is {title} production-ready?", "a": "Review recent releases, issues, and community activity on the repository to assess maturity."},
        ]
    return [
        {"q": f"What is {title}?", "a": f"{item.summary}" if item.summary else f"{title} is a trending topic in the AI space."},
        {"q": f"Where can I learn more about {title}?", "a": f"Visit {host} for official details and updates."},
    ]


class ArticleGenerator:
    """基于 TrendItem 生成 AIHues Resources 风格的 SEO 文章。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.cta_link = self.config.get("aihues_cta_link", "/tools")
        self.cta_text = self.config.get("aihues_cta_text", "Browse AI Tools")

    def generate(self, item: TrendItem, date_str: str = "") -> dict[str, Any]:
        if not date_str:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

        tag = _category_to_tag(item.category, item.source)
        slug = _slugify(item.title)
        host = _extract_host(item.url or "")
        summary = item.summary or f"{item.title} is a trending topic in the AI space."

        # 把 summary 整理成通顺的名词短语，方便嵌入正文（保留原始大小写）
        clean_summary = summary.strip().rstrip(".")
        lower = clean_summary.lower()
        if lower.startswith("a ") or lower.startswith("an ") or lower.startswith("the "):
            noun_phrase = clean_summary
        elif lower[0:1] in "aeiou":
            noun_phrase = f"an {clean_summary}"
        else:
            noun_phrase = f"a {clean_summary}"

        # SEO 元信息：标题多样化，避免每篇都是 "What Is ..."
        h1_templates = {
            "AI产品": [
                "{title}: A Practical Guide for 2026",
                "What Is {title} and How Does It Work?",
                "How {title} Fits Into Your Workflow",
                "Getting Started with {title}",
            ],
            "开源项目": [
                "Getting Started with {title}",
                "{title}: An Open-Source Guide",
                "What Is {title} and Why It Matters",
            ],
            "论文": [
                "{title}: Key Takeaways",
                "What {title} Means for AI Builders",
                "{title} Explained",
            ],
        }
        default_templates = [
            "{title}: A Practical Guide for 2026",
            "What Is {title} and How Does It Work?",
            "Getting Started with {title}",
        ]
        templates = h1_templates.get(item.category, default_templates)
        # 用 title 长度做稳定选择，确保同一产品每次生成相同标题
        h1_template = templates[len(item.title) % len(templates)]
        h1 = _truncate(h1_template.format(title=item.title), 65)

        # SEO title 必须与 H1 不同
        seo_templates = [
            "{title}: A Practical Guide",
            "{title} Review and Guide",
            "{title} for Beginners",
            "Introduction to {title}",
        ]
        seo_title = _truncate(seo_templates[len(item.title) % len(seo_templates)].format(title=item.title), 60)

        meta = _truncate(f"{summary} Learn what {item.title} does, who it is for, and how to get started.", 160)
        banner = _truncate(
            f"{item.title} is {noun_phrase}. This guide covers how it works, key features, and where it fits in your workflow.",
            280,
        )

        article = {
            "slug": slug,
            "tag": tag,
            "title": h1,
            "seo_title": seo_title,
            "meta_description": meta,
            "h1": h1,
            "banner": banner,
            "date": date_str,
            "read_time": "6 min",
            "cover_image": _choose_cover_image(tag, seed=item.title),
            "excerpt": _truncate(summary, 160),
            "description": meta,
            "noun_phrase": noun_phrase,
            "item": item,
            "comparison_table": _build_comparison_table(item),
            "faq": _build_faq(item),
        }
        return article

    def render_html(self, article: dict[str, Any]) -> str:
        """渲染成 AIHues Resources 兼容的 HTML。"""
        item: TrendItem = article["item"]
        url = str(item.url) if item.url else ""

        sections: list[str] = []
        noun_phrase = article.get("noun_phrase", f"a tool for {article['excerpt'].lower()}")

        # Intro
        sections.append(f"<p>{item.title} is {noun_phrase}. This guide explains what it does, who it serves, and how to start using it.</p>")

        # CTA 1
        sections.append(self._cta_box(
            "Find More AI Tools",
            "Discover AI-powered tools that match your workflow.",
        ))

        # How it works / What it does
        sections.append("<h2>How It Works</h2>")
        sections.append(f"<p>{item.title} turns a user goal into a working result. You describe what you need, and the tool handles the structure, content, or automation behind the scenes. Most users can get started without writing code or configuring complex settings.</p>")

        display_tags = [t for t in item.tags if t not in ("product-hunt", "ai-product", "open-source", "github")][:6]
        if display_tags:
            sections.append("<h3>Key Capabilities</h3>")
            sections.append("<ul>")
            for tag in display_tags:
                sections.append(f"<li>{tag}</li>")
            sections.append("</ul>")

        # Use cases
        sections.append("<h2>Common Use Cases</h2>")
        sections.append("<ul>")
        use_cases = [
            "Automating repetitive tasks",
            "Building prototypes without code",
            "Connecting data across tools",
            "Speeding up content or code workflows",
        ]
        if item.category == "AI产品":
            use_cases = [
                "Creating internal tools or client portals",
                "Automating form-based workflows",
                "Generating content or design drafts",
                "Connecting with existing SaaS stacks",
            ]
        elif item.category == "开源项目":
            use_cases = [
                "Self-hosting services without vendor lock-in",
                "Customizing behavior through source code",
                "Learning from community contributions",
                "Integrating into existing devops pipelines",
            ]
        for case in use_cases:
            sections.append(f"<li>{case}</li>")
        sections.append("</ul>")

        # Limitations
        sections.append("<h2>Limitations to Know</h2>")
        sections.append(f"<p>No tool fits every scenario. {item.title} may require manual setup for advanced integrations, and output quality depends on how clearly you define the task. Always test with your own data before relying on it for production work.</p>")

        # Comparison table
        table = article.get("comparison_table")
        if table:
            sections.append("<h2>How It Compares</h2>")
            sections.append(self._render_table(table))
            sections.append("<p>Choose the option that matches your technical comfort level and long-term needs.</p>")

        # Getting started
        sections.append("<h2>How to Get Started</h2>")
        sections.append("<ol>")
        sections.append(f"<li>Visit <a href=\"{url}\">{url}</a> to create an account or view the repository.</li>")
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
        sections.append(f"<p>{item.title} is {noun_phrase}. It works best when you match its strengths to your actual workflow. Browse more AI tools on AIHues to find alternatives for different needs.</p>")

        # CTA 2
        sections.append(self._cta_box(
            "Browse AI Tools",
            "Find the right AI tool for your next project.",
        ))

        body = "\n\n".join(sections)

        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{article['seo_title']} | AIHues</title>
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

      <div class="article-content">
{self._indent(body, 8)}
      </div>
    </article>
    <footer class="footer">© 2026 AIHues · Built with Kimi</footer>
  </body>
</html>
"""

    def _cta_box(self, heading: str, subtext: str) -> str:
        return f"""<div class="cta-box">
          <h3>{heading}</h3>
          <p>{subtext}</p>
          <a href="{self.cta_link}" class="cta-btn">{self.cta_text} →</a>
        </div>"""

    def _render_table(self, rows: list[dict[str, str]]) -> str:
        html = ['<table class="comparison-table">']
        html.append("<thead><tr><th>Tool</th><th>Best For</th><th>Starting Price</th><th>Key Difference</th></tr></thead>")
        html.append("<tbody>")
        for row in rows:
            html.append(f"<tr><td>{row['tool']}</td><td>{row['best_for']}</td><td>{row['price']}</td><td>{row['difference']}</td></tr>")
        html.append("</tbody></table>")
        return "\n".join(html)

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
