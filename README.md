# AI Trend Collector

一个专注于 **AI 热点趋势、AI 产品、开源项目、学术论文** 的轻量级爬虫系统，支持将结果推送到**飞书机器人**。

> 本项目参考了 [comm-collector](https://dev.msh.team/search-engine/crawlers/comm-collector) 的架构思路，但做了大幅精简，只保留与 AI 趋势相关的能力。

## ✨ 核心能力

| 数据源 | 类型 | 说明 |
|--------|------|------|
| GitHub Trends | 开源项目 | 抓取每日/每周热门仓库 |
| Product Hunt | AI 产品 | 通过 API v2 获取热门产品 |
| arXiv AI | 学术论文 | 按 cs.AI / cs.LG / cs.CL / cs.CV 等分类抓取 |
| Hugging Face Daily Papers | 学术论文 | 抓取 HF 每日推荐论文 |

- **统一数据模型**：所有爬虫输出 `TrendItem`，便于统一存储和推送
- **去重机制**：基于 `id` 自动去重，避免重复推送
- **存储后端**：支持 JSON 文件（默认）和 SQLite
- **飞书推送**：支持 Webhook 群机器人和企业自建应用机器人
- **知识库归档**：每日日报写入飞书文档，主索引自动汇总
- **LLM 增强**：对精选条目自动生成中文一句话概述和产品影响分析
- **定时任务**：可配置定时运行，适合接入 cron

## 📁 项目结构

```text
ai-trend-collector/
├── config/
│   └── config.example.yaml    # 配置模板
├── src/
│   ├── core/
│   │   ├── base_spider.py     # 爬虫基类
│   │   ├── config.py          # 配置加载
│   │   ├── models.py          # TrendItem 数据模型
│   │   ├── ranker.py          # 相关度排序与日报生成
│   │   ├── llm.py             # LLM 中文概述/产品影响生成
│   │   └── storage.py         # JSON/SQLite 存储
│   ├── spiders/
│   │   ├── github_trends.py
│   │   ├── product_hunt.py
│   │   ├── arxiv_ai.py
│   │   └── huggingface_papers.py
│   ├── bots/
│   │   └── feishu.py          # 飞书 Webhook 机器人
│   └── main.py                # 命令行入口
├── scripts/
│   └── run.sh                 # 启动脚本
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 🚀 快速开始

### 1. 安装依赖

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config/config.example.yaml config/config.yaml
# 编辑 config/config.yaml，填写飞书 webhook_url 等
```

### 3. 运行

```bash
# 列出可用爬虫
python -m src.main --list

# 运行单个爬虫
python -m src.main --spider github_trends

# 运行所有爬虫
python -m src.main --all

# 运行并推送到飞书
python -m src.main --all --push
```

或使用脚本：

```bash
./scripts/run.sh --all --push
```

## ⚙️ 配置说明

关键配置项：

```yaml
feishu:
  mode: "webhook"  # webhook | app
  webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
  secret: ""       # 可选，安全设置里的签名密钥
  # app 模式还需配置 app_id / app_secret / chat_id / folder_token

llm:
  enabled: true
  provider: "kimi"  # kimi / deepseek / openai
  api_key: ""       # 或环境变量 KIMI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY

storage:
  type: json        # 或 sqlite
  output_dir: ./data

sources:
  github_trends:
    enabled: true
    languages: [python, typescript, go]
    period: daily   # daily / weekly / monthly
    max_items: 30

  product_hunt:
    enabled: true
    api_token: "YOUR_PRODUCT_HUNT_TOKEN"  # 需申请
    max_items: 30

  arxiv_ai:
    enabled: true
    categories: [cs.AI, cs.LG]
    keywords: ["large language model", "agent"]
    max_items: 30
```

## 🛠️ 添加新爬虫

1. 在 `src/spiders/` 下新建文件，继承 `BaseSpider`
2. 实现 `fetch()` 方法，返回 `list[TrendItem]`
3. 在 `src/main.py` 的 `SPIDER_REGISTRY` 中注册

示例：

```python
from src.core.base_spider import BaseSpider
from src.core.models import TrendItem, TrendType

class MySpider(BaseSpider):
    name = "my_spider"
    source_type = TrendType.TECH_NEWS

    def fetch(self, **kwargs):
        # 抓取逻辑
        return [TrendItem(...)]
```

## 📝 定时任务

使用 cron 每日早上 9 点运行：

```cron
0 9 * * * cd /path/to/ai-trend-collector && ./scripts/run.sh --all --push >> ./logs/cron.log 2>&1
```

## 📄 许可证

MIT
