# 非密钥配置，用户常改的就是这个文件。密钥一律走 .env。

# —— 用户常改区 ——

# 每个源取最新几条。
# 调到 10 是为了让 AIHOT 精选（实测有 50 条）独力兜底：
# 36Kr / 少数派都压在 RSSHub 镜像上，挂掉是常态，挂了也不能让日报塌一半。
TOP_N = 10

# 只保留 N 天内发布的条目（接定时的前置，不加会推陈货）
PUBDATE_DAYS = 2

# 重要性评分门槛：只保留 >= MIN_STARS 的条目进推送（4 = 只要 4-5 星）
MIN_STARS = 4

# 两区各自最多推几条（用户定的 5 + 5）。按星级降序取前 N，多的不入库（下次还能选中）。
MAX_NEWS = 5
MAX_TOOLS = 5

# —— 要闻源（只用中文：AIHOT 已把国外新闻转译成中文收录，不需要英文原文源）——
# kind: "news" 进「今日要闻」区；top_n 不填则用全局 TOP_N。
# 2026-10-10 全部实测 HTTP 200 + feedparser 解析成功 + 自带摘要。
#
# 「微信」项走 decemberpei.cyou 的公众号 RSS 桥（第三方，长期可用性需关注）。
# 它的价值：官方 feed 已死的机器之心、只有公众号的新智元，都从这里拿得到，且带摘要。
RSS_FEEDS = [
    # AIHOT 精选：跨源中文编辑稿（168 信源 + LLM 筛选打分 + 中文转译），主力源，独力兜底
    {"name": "AIHOT 精选", "url": "https://aihot.news/feed.xml", "kind": "news", "top_n": 8},
    # 以下为纯 AI 中文媒体（微信桥）。只挑 AI 向的，泛科技（36氪/虎嗅）会带噪音，不加。
    {"name": "机器之心", "url": "https://decemberpei.cyou/rssbox/wechat-jiqizhixin.xml", "kind": "news", "top_n": 3},
    {"name": "新智元", "url": "https://decemberpei.cyou/rssbox/wechat-xinzhiyuan.xml", "kind": "news", "top_n": 3},
    {"name": "量子位", "url": "https://decemberpei.cyou/rssbox/wechat-liangziwei.xml", "kind": "news", "top_n": 3},
    {"name": "AI前线", "url": "https://decemberpei.cyou/rssbox/wechat-aiqianxian.xml", "kind": "news", "top_n": 2},
    {"name": "夕小瑶科技说", "url": "https://decemberpei.cyou/rssbox/wechat-xixiaoyaokejishuo.xml", "kind": "news", "top_n": 2},
    {"name": "PaperWeekly", "url": "https://decemberpei.cyou/rssbox/wechat-paperweekly.xml", "kind": "news", "top_n": 2},
    # 36Kr AI / 少数派 AI 必须走 RSSHub（官方 feed 是 HTML）；镜像偶发 503，已有重试
    {"name": "36Kr AI", "url": "https://rsshub.rssforever.com/36kr/information/AI", "kind": "news", "top_n": 5},
    {"name": "少数派 AI", "url": "https://rsshub.rssforever.com/sspai/tag/AI", "kind": "news", "top_n": 3},
]

# SuYxh/ai-news-aggregator —— 80+ AI/科技源聚合，每 2 小时更新
# 纯 JSON 快照（**没有 RSS feed**，实测 feed.xml 等全 404），带中英双语标题。
# ⚠️ 没有摘要字段，只有标题+链接 —— 当「捞头条」用，深度加工靠 AIHOT/36Kr 这类带摘要的源。
# 不要拉 archive.json（41.7MB / 10 万条历史）。
AGGREGATOR_URL = "https://suyxh.github.io/ai-news-aggregator/data/latest-24h.json"
AGGREGATOR_LIMIT = 12      # 候选条数上限（24h 窗口实测 821 条，必须截断）
# kind: "tool" 进「工具与 Skill」区。agent-skills-hub 的 RSS 无质量评分字段（用户已选 RSS 出口）。
TOOL_FEEDS = [
    # zhuyansen/agent-skills-hub 周 star 增速 Top20
    {"name": "SkillsHub 热门", "url": "https://agentskillshub.top/feed-trending.xml", "kind": "tool"},
    # 同上，新收录 30 条
    {"name": "SkillsHub 新收录", "url": "https://agentskillshub.top/feed.xml", "kind": "tool"},
]

# GitHub Search API —— 「新仓库 + star 排序」当 trending 用
# （官方无 trending API；OSSInsight 的 trending 2026-03 起已死）
# 多 topic 不支持 OR，必须逐 topic 循环。
GITHUB_TOPICS = [
    "artificial-intelligence",
    "llm",
    "mcp-server",
    "ai-agents",
    "claude-skills",
    "generative-ai",
]
GITHUB_CREATED_DAYS = 7    # 只看近 N 天新建的仓库（要「冒头的」不是「成名的」）
GITHUB_PER_TOPIC = 10      # 每个 topic 取多少条参与合并
GITHUB_LIMIT = 5           # 合并去重后最终取多少条

# Show HN（Hacker News 的产品发布帖）—— 走 Algolia，别走 hnrss（偶发 502）
# 坑：多关键词 OR 组合 numericFilters 会返回 0 条，必须逐词请求后按 objectID 合并。
SHOWHN_KEYWORDS = ["AI", "LLM", "GPT", "agent", "MCP"]
SHOWHN_MIN_POINTS = 20     # 低于此热度的不看
SHOWHN_PER_KEYWORD = 15
SHOWHN_LIMIT = 5

# 每个源最多贡献几条候选。防止单一源霸榜（曾出现 5 条工具全来自 SkillsHub 热门）。
# 3 时候选池偏薄（去重 + 已推滤掉后常只剩 2-3 条，再过 4 星线容易归零），提到 5。
PER_SOURCE_LIMIT = 5

# 每日 AI 处理预算上限（篇）。超出则只抓取不加工，并告警。
# 防止某天 TOP_N 调大或源变多导致成本悄无声息翻倍。
MAX_AI_ITEMS = 100

# LLM 调用重试。单次抖动不该让整天日报报废。
LLM_RETRIES = 3
LLM_BACKOFF_BASE = 2      # 第 1/2 次失败分别等 2s / 4s

# AI 生成内容质量门槛：低于此分的条目不推送
MIN_QUALITY = 3

# ★ 三个定制问题：改这里的描述文字即可，不用动其他文件。
#   注意：JSON 的 key 名（普通人影响 / 自媒体选题 / 快速上手）是数据契约，
#   改 key 名 = 要同时改 feishu.py 的渲染，不只是改这里。
THREE_QUESTIONS = [
    "普通人影响：用 2-3 句话说明对非技术人群的实际价值。必须给出实质判断，不许用「原文未提及」这类话推脱。",
    "自媒体选题：给出 1 个具体可执行的创作角度，并说明为什么有热度。要具体到能直接开写。",
    "快速上手：如果是工具类内容，给出 3 步以内的上手建议；如果是新闻类，简要说明如何用 Codex 跟进。",
]

# —— 稳定常量区 ——

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 飞书自定义机器人请求体上限 20KB（超报 9499），留 2KB 给签名/转义余量
CARD_MAX_BYTES = 18 * 1024
# 卡间发送间隔（秒）。限速 5 次/秒、100 次/分钟
CARD_SEND_INTERVAL = 1.2


# {n} / {items_block} / {pushed_block} 由 llm.score_and_dedup 注入
SCORE_PROMPT = """你是「AI 信息情报官」的内容筛选员。以下是今天从 RSS 收集的 {n} 条资讯：

{items_block}

以下是**最近已推送过**的条目，不要再推同一件事：

{pushed_block}

请对每条输出四项判断：

1. relevant：是否与 AI 领域相关（true/false）。产品发布会、模型/工具发布、融资并购、政策监管、开源项目、行业人事变动都算相关；与 AI 无关的硬广、地方新闻、纯娱乐八卦算 false。
2. stars：重要性 1-5 星。**按「最高符合项」打分，不要在相邻两档之间犹豫**：
   5 = 全行业重大事件：大厂战略级发布、超大额融资并购、重大政策监管、突破性研究成果
   4 = 有实质进展，值得转发：新产品/新模型/新榜单成绩、带具体数据的落地案例、重要人事变动
   3 = 一般动态：常规版本更新、观点访谈、行业评论、无新信息的综述
   2 = 软文、老生常谈、纯宣传
   1 = 噪音
3. duplicate_of：若本条与**前面某条**属于**同一件事**，填那条的编号；否则填 null。
   「同一件事」包括：同一事件的不同侧面、后续进展、公司回应、外界评论解读。
   **同一件事的多篇报道必须聚成一条**，只留信息最全的那篇作为主条目，其余全部标为重复。
   注意判的是「同一件事」不是「文字相似」，也不是「同一来源」——同源也可能在写不同的事。
   例：「Anthropic 承认模型自述不可作动机证据」「Anthropic 向白宫通报智能体失控」「Anthropic 承认难控智能体并切断内部评测联网」
       —— 三篇都围绕同一波 Anthropic 智能体失控事件（共同背景是向费城警方提交虚构凶案线索），
       属同一件事，后两篇应填 duplicate_of 指向第一篇。
4. already_pushed：若本条与**已推送清单**中的某条属于**同一件事**，填 true；否则填 false。
   判的同样是「同一件事」不是「文字相似」——不同来源、不同措辞报道同一事件也算重复。
   例：已推过「OpenAI 攻克千禧年难题」，候选出现「MIT 教授绝望：OpenAI 攻克的千禧年难题」
       —— 同一件事，already_pushed 填 true。
   若清单为空，一律填 false。

只输出 JSON 数组，不要任何其他文字、不要代码围栏：
[{{"id": 1, "relevant": true, "stars": 5, "duplicate_of": null, "already_pushed": false}}, ...]"""


# 工具/Skill 条目评分。{n} / {items_block} 由 llm.score_tools 注入。
# 与新闻评分不同：工具条目天然唯一（不同仓库/产品），不需要判重。
TOOL_SCORE_PROMPT = """你是「AI 信息情报官」的工具筛选员。以下是今天收集到的 {n} 条 AI 工具 / 开源 Skill / MCP Server：

{items_block}

请对每条输出两项判断：

1. relevant：是否是可实际使用的 AI 工具、框架、Skill 或 MCP Server（true/false）。纯文章、纯教程、与 AI 无关的通用工具算 false。
2. stars：作为「值得推荐给用户的工具」的重要性 1-5 星。**按「最高符合项」打分，不要在相邻两档之间犹豫**：
   5 = 值得立刻试用：高热度新工具、官方/大厂出品、解决明确痛点
   4 = 值得关注：有特色的新项目、活跃维护、star 增速快
   3 = 一般：常规工具、同质化、文档不全
   2 = 噪音：刷 star、纯包装、无实质
   1 = 无关

只输出 JSON 数组，不要任何其他文字、不要代码围栏：
[{{"id": 1, "relevant": true, "stars": 5}}, ...]"""


# {title} / {source} / {link} / {summary} / {questions_block} 由 llm.enrich 注入
ENRICH_PROMPT = """你是资深 AI 领域分析师。请基于下面这条资讯，输出一份结构化分析。

标题：{title}
来源：{source}
原文链接：{link}
RSS 摘要：{summary}

需要回答的问题：
{questions_block}

**严格按以下 JSON 格式输出，只输出 JSON 本身，不要任何其他文字、不要代码围栏、不要解释**：

若这条素材足够支撑一份合格分析：
{{
  "skip": false,
  "质量": 1 到 5 的整数，给你刚生成的这份分析打分（5=扎实有料，3=勉强可用，1=空洞拼凑）,
  "摘要": "5-8 句、250-400 字的完整摘要。讲清事情本身、背景、关键数字与影响，让人不读原文也能了解全貌",
  "普通人影响": "…",
  "自媒体选题": "…",
  "快速上手": "…"
}}

若这条素材过薄（例如只有标题没有实质内容）、与 AI 无关、或你无法给出有依据的分析：
{{"skip": true, "原因": "一句话说明为什么跳过"}}

要求：
1. 用中文
2. 可以动用你的背景知识补充上下文，让回答有实质内容；但**不得编造**具体数据、引文或原文没有的事实
3. 「摘要」是四个字段里最长的，务必到 250-400 字，不要写成两三句的短摘要
4. 「普通人影响」「自媒体选题」「快速上手」**每段不超过 120 字**，要精炼，不要写成小论文
5. 「自媒体选题」必须具体到能直接开写，不要「可以聊聊 XX」这种空话
6. 不要输出表格
7. **宁可 skip，也不要硬编** —— 素材不足时编出来的分析是负价值"""
