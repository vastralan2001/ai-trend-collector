# 热点 → SEO 文章工作流

> 基于 `Kimi-SEO-Writing` Skill 简化适配，用于把 `ai-trend-collector` 每日抓取的热点产品/项目/论文转化为 SEO 文章。

---

## 适用场景

- 每日 Product Hunt / GitHub / arXiv 热点中出现值得写成文章的产品或技术
- 想快速把趋势变成可发布的博客/Resources 内容
- 需要保持 SEO 结构、反 AI 味、可追踪关键词部署

---

## 工作流概览

```
TrendItem（热点）
    ↓
Step 1: 提取关键词组
    ↓
Step 2: SERP 调研（Top15 + People Also Ask）
    ↓
Step 3: 竞品分析（读 3-5 篇头部文章）
    ↓
Step 4: 生成大纲（SEO 信息 + H1/H2/H3 + FAQ + CTA）
    ↓  用户审核
Step 5: 写正文（严格遵循反 AI 规则）
    ↓
Step 6: 内部 Review（检查清单循环 1-2 轮）
    ↓
Step 7: 关键词统计 + 飞书文档交付 + 本地备份
```

---

## Step 1: 提取关键词组

从热点条目推断目标关键词：

| 来源字段 | 用法 |
|----------|------|
| `title` | 产品名，作为主关键词或核心修饰词 |
| `summary` | 提炼场景词、功能词 |
| `tags` | 分类词，用于 LSI/长尾词 |
| `category` | 决定文章类型（AI产品 → Review/How-to，论文 → 解读/教程） |

### 示例：Jotform AI App Builder

- 主关键词：`ai app builder`
- 次要关键词：`no-code ai app builder`, `free ai app builder`, `jotform ai app builder`
- 长尾词：`how to build an app with ai without coding`
- FAQ 词：`is jotform ai app builder free`, `can ai build a mobile app`

---

## Step 2: SERP 调研

### 2.1 使用 SERP API

```bash
curl --location 'https://nlp.mse.msh.work/serp/run' \
--header 'Content-Type: application/json' \
--data '{
    "query": "ai app builder",
    "skip_cache": true,
    "engine": "mazhu_google_i18n_for_seo"
}'
```

- 英文关键词：`mazhu_google_i18n_for_seo`
- 中文关键词：`mazhu_google_cn_for_seo`

### 2.2 调研内容

对每个关键词：
- 收集前 15 条自然结果（排除广告）
- 记录标题模式、字数、结构
- 记录 People Also Ask 问题

### 2.3 SERP 相似度验证

如果多个关键词共享相似结果（Jaccard ≥ 20%），可以放在同一篇文章；否则拆分。

---

## Step 3: 竞品分析

读 3-5 篇头部文章，分析：
- 文章结构和标题层级
- 内容深度和独特角度
- 用户痛点
- 写作风格
- 可填补的空缺

---

## Step 4: 生成大纲

大纲必须包含：

```markdown
# SEO Information

| Information | | |
|---|---|---|
| **URL** | /resources/xxx-xxx | |
| **SEO title** | ... | XX chars |
| **Meta description** | ... | XX chars |
| **H1** | ... | XX chars |
| **Main keyword** | ... | |
| **Secondary keywords** | ... | |
| **Banner** | ... | XX chars |

---

# [H1 Title]

[Banner text]

CTA
Text: ...
Link: ...

---

[Introduction < 100 words]

## [H2]
### [H3]
...

## FAQ
...

## Conclusion
...

CTA
Text: ...
Link: ...

Keyword Deployment Statistics
| Keyword | Search Volume | Deploy Count |
|---|---|---|
```

### FAQ 要求

- 必须基于真实调研（People Also Ask、Reddit、Quora、竞品 FAQ）
- 每个问题标注来源
- 第一句直接回答，40-50 词
- 不引用前文，独立成段

---

## Step 5: 写正文

### 5.1 反 AI 写作规则

- **短句**：一句一个意思
- **不用破折号（—）**：改用逗号、句号、冒号
- **不用括号藏信息**：融入正文
- **避免连续句子以相同词开头**（This / It / If）
- **列表只用于**：步骤、功能列表、系统要求
- **不用 hype 词**：game-changing, revolutionary, amazing

### 5.2 产品规则

- 不夸竞品（不用 best/fastest/easiest）
- 推荐自家产品时立场明确
- 技术事实必须可验证，不确定标 `[VERIFY]`

### 5.3 SEO 硬规则

| 元素 | 规则 |
|------|------|
| Meta Title | ≤60 字符，含主关键词，与 H1 不同 |
| Meta Description | 140-160 字符，含主关键词，特征与好处分组 |
| H1 | ≤65 字符，含主关键词，与 Meta Title 不同 |
| Banner | 170-280 字符，含价值主张，不以 "Try it now!" 结尾 |
| 主关键词密度 | 0.5%-1%，至少出现 5 次 |

---

## Step 6: 内部 Review

用子代理或人工检查：

### Critical Issues
- [ ] SEO 字符限制
- [ ] 破折号、括号、连续同开头句子
- [ ]  intro > 100 词
- [ ] 竞品 superlatives
- [ ] 技术命令/版本号/URL 可验证
- [ ] 缺少 Hero Banner / Keyword Statistics

### Warnings
- [ ] 过渡句是否自然
- [ ] CTA 是否上下文相关
- [ ] 图片占位符格式是否正确

最多 2 轮 Review。

---

## Step 7: 交付

### 飞书文档

使用 `feishu_doc` 工具创建文档。

### 本地备份

保存到 `~/Desktop/SEO Draft/<article-slug>/`：

```
~/Desktop/SEO Draft/
└── jotform-ai-app-builder/
    ├── outline.md
    ├── article-v1.md
    ├── article-v2.md
    └── review-report.md
```

---

## 快速检查清单

交付前确认：

- [ ] SERP 相似度已验证
- [ ] 关键词角色已分配（Main/H2/Body/FAQ/Skip）
- [ ] 大纲已获用户批准
- [ ] Meta Title / Description / H1 / Banner 长度合规
- [ ] 无破折号、无括号藏信息、无连续同开头句子
- [ ]  intro < 100 词
- [ ] Conclusion 一段，Value Summary → CTA
- [ ] FAQ 基于真实调研，第一句直接回答
- [ ] 关键词统计表完整
- [ ] CTA 至少 3 处：Hero、产品段后、Conclusion 后
