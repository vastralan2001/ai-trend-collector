# AIHues Resources 热点文章流水线

> 一句话：每天自动抓取 AI/开源/小游戏热点，按热度+相关性排序，生成 SEO 文章并发布到 `https://aihues.com/resources`。

---

## 数据源

| 来源 | 类型 | 抓取内容 |
|---|---|---|
| Product Hunt | AI 产品 | 每日 Featured + Ranking 产品 |
| GitHub Trending | 开源项目 | 各语言每日热门仓库 |
| Hacker News Show HN | 小游戏/Demo | 标题命中游戏关键词、分数 ≥20 的 Show HN 帖子 |
| arXiv AI | 论文 | cs.AI / cs.CL / cs.CV / cs.LG / cs.IR 最新论文 |
| Hugging Face Daily Papers | 论文 | HF 每日推荐论文 |

---

## 热点排序标准

最终分数 =

- **40% 来源热度**（真实平台指标）
  - Product Hunt：`votes + comments × 2`
  - GitHub：`today_stars` 为主，total stars 兜底
  - HN Show：`score + comments × 3`
  - arXiv / HF：以新鲜度兜底
- **35% 业务相关性**（AIHues/Kimi 关键词匹配）
  - AI agent、multimodal、reasoning、SaaS、SEO、marketing、automation、open source 等
- **15% 时效性**
  - 7 天内线性衰减，越新越高
- **10% 内容质量**
  - 标题/摘要过短、缺少 URL 会降权

同时保留分类多样性控制，避免同一类源占满。

---

## 生成与发布流程

1. `python -m src.main --all` 抓取所有来源
2. `scripts/generate-aihues-articles.py --date YYYY-MM-DD --limit 7`
   - 按分数排序
   - 遇到已发布 slug 自动跳过并继续补位
   - 输出 HTML 到 `apps/aihues-web/public/resources/{slug}.html`
   - 追加元数据到 `apps/aihues-web/content/resources/posts.json`
3. `scripts/validate-unsplash-covers.py` 校验封面图 URL 无 404
4. `pnpm check` + `pnpm moon run aihues-web:build`

---

## 质量保障

- 封面图会先用 `curl` 批量校验 `HTTP 200` 且为 `image/jpeg/png`
- 新文章先 `dry-run` 到 `staging/aihues-articles/`，人工检查后再真实写入
- 已存在 slug 不覆盖，自动向后补位
- 每篇文章生成前都会过 `pnpm check` 和 production build

---

## 今日跑通结果

- 已修复 4 个失效 Unsplash 封面图 ID
- 新增封面校验脚本 `scripts/validate-unsplash-covers.py`
- 抓取 Product Hunt/GitHub/HN 后成功生成 5 篇新文章
- `pnpm check` 与 `pnpm moon run aihues-web:build` 均通过

---

## 常用命令

```bash
cd ai-trend-collector
source .venv/bin/activate

# 1. 抓取
python -m src.main --all

# 2. dry-run 生成
python scripts/generate-aihues-articles.py --date $(date +%Y-%m-%d) --limit 7 --dry-run

# 3. 真实生成
python scripts/generate-aihues-articles.py --date $(date +%Y-%m-%d) --limit 7

# 4. 校验封面
./scripts/validate-unsplash-covers.py ../apps/aihues-web/content/resources/posts.json

# 5. AIHues 检查
cd ..
pnpm check
pnpm moon run aihues-web:build
```
