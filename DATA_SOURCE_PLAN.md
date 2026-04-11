# A 股投研助手数据源接入规划

## 1. 目标

第一版不使用纯模拟数据，直接接入真实行情与资讯源。

但为了控制复杂度，采用：

- `真实数据源 + Provider 抽象`
- 先做可落地的 MVP 组合
- 保证后续可以从免费源平滑切换到专业付费源

核心原则：

- 单票分析闭环优先
- 公告和权威信披优先于二手转述
- 热门候选发现需要行情热度与资讯解释双链路
- 数据接入层必须可替换，不能把 Agent 逻辑写死在某个供应商 SDK 上

## 2. 数据源分层

建议把第一版数据能力拆成四类 Provider：

- `market_data_provider`
- `announcement_provider`
- `news_provider`
- `hotlist_provider`

这四层已经足够支撑当前 MVP：

- `single_stock_analysis`
- `stock_compare_or_followup`
- `hot_candidate_discovery`
- `theme_or_topic_exploration`

## 3. 推荐数据源组合

### 3.1 第一优先组合

建议第一版按以下组合接入：

- `Tushare Pro`
  - 用于股票基础信息、交易日历、日线行情、日度基础指标、部分事件/资讯补充
- `巨潮资讯 / 交易所公告入口`
  - 用于上市公司公告、定期报告、临时公告等权威信披
- `AKShare`
  - 用于补充榜单、异动、热点、抓取型资讯和市场热度能力

### 3.2 升级组合

如果后续有授权或预算，可以切换或增加：

- `同花顺 iFinD QuantAPI`
- `Wind API`
- `东方财富 Choice`

这些更适合做：

- 更稳定的专业数据接入
- 更强的实时行情与终端级数据能力
- 更适合简历中的“金融数据工程化”叙事

## 4. 各数据源定位

## 4.1 Tushare Pro

定位：

- 第一版主行情和基础资料底座
- 适合 Python 原型和数据分析流程

适合承接的数据：

- 股票基础信息
- A 股日线行情
- 每日基础指标
- 交易日历
- 行业/板块辅助数据
- 部分资讯与社区整理数据

适合作为这些 Agent 的核心底层：

- `Intent Router Agent`
  - 用于股票代码/名称映射和标的确认
- `Stock Research Agent`
  - 用于价格、估值、换手、量比等分析底层
- `Hotlist Discovery Agent`
  - 用于部分板块、涨停、异动、概念辅助

优点：

- Python 生态友好
- A 股常用分析接口较全
- 比纯抓取源更适合作为系统底座

注意点：

- 不是专业终端级别的全量实时底座
- 部分数据存在更新频率和权限差异
- 资讯能力存在上限，不能单靠它完成“事件解释”

参考官方文档：

- 平台总览：https://tushare.pro/document/2
- A 股日线行情：https://www.tushare.pro/document/2?doc_id=27
- 每日基础指标：https://tushare.pro/document/2?doc_id=32
- 平台与资讯入口：https://tushare.pro/

## 4.2 巨潮资讯 / 交易所公告入口

定位：

- 单票分析中的“硬证据层”
- 优先用于公告、财报、临时事项、问询回复等信披材料

适合承接的数据：

- 公司公告
- 定期报告
- 临时公告
- 交易所公开披露文件

适合作为这些 Agent 的核心底层：

- `Search Agent`
  - 公告检索、公告正文抓取、时间排序
- `Stock Research Agent`
  - 用于验证事件驱动是否真实存在
- `Evaluator / Trace Agent`
  - 用于标记“事实依据来自权威信披”

优点：

- 权威性最高
- 适合作为观点卡中的证据链核心来源
- 能有效压制新闻二次转述的噪声

注意点：

- 接口形态和可用性需要单独验证
- 第一版要预留抓取、搜索和解析失败的降级路径
- 公告 PDF/HTML 解析链路需要单独设计

参考官方入口：

- 上交所数据服务：https://one.sse.com.cn/list/ssgssjfw/
- 上交所公告披露入口：https://www.sse.com.cn/disclosure/diclosure/StarMarketMaker/announcement/
- 深交所数据接口：https://www.szse.cn/marketServices/technicalservice/interface/
- 巨潮资讯官网：https://www.cninfo.com.cn/

## 4.3 AKShare

定位：

- 第一版补充型抓取源
- 适合快速补齐热度、榜单、异动和部分资讯抓取

适合承接的数据：

- 热门榜单
- 市场异动
- 题材或板块抓取数据
- 一些网页型资讯或市场辅助信息

适合作为这些 Agent 的补充底层：

- `Hotlist Discovery Agent`
  - 用于补齐“市场正在交易什么”的高频信号
- `Search Agent`
  - 用于补充网页抓取型资料

优点：

- 上手快
- Python 友好
- 原型阶段很高效

注意点：

- 官方明确说明主要用于学术研究，不可做商业用途
- 部分接口依赖第三方网页结构，稳定性有限
- 不应作为系统唯一核心数据底座

参考官方说明：

- AKShare 特别说明：https://akshare.akfamily.xyz/special.html

## 4.4 同花顺 iFinD QuantAPI

定位：

- 更专业的升级型供应商
- 适合后续替换或补充 MVP 的数据底座

适合承接的数据：

- 实时行情
- 历史行情
- 快照
- 基本面数据

适合作为后续升级 Provider：

- `market_data_provider`
- `hotlist_provider`
- `news_provider` 的部分增强能力

优点：

- 更接近专业终端和机构使用体验
- 官方提供 Python/HTTP 等接入方式
- 权限说明和部署说明较清晰

注意点：

- 账号、权限和正式使用成本需要提前确认
- 第一版不建议强依赖，以免阻塞开发

参考官方文档：

- 使用流程：https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/help-center/deploy.html
- 权限说明：https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/help-center/permission.html
- 常见问题：https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/help-center/faq.html

## 4.5 Wind API

定位：

- 专业级升级路线
- 更适合后续做“机构级数据接入”的项目叙事

适合承接的数据：

- 实时行情
- 历史行情
- 宏观和多资产扩展数据

注意点：

- 适合作为后期增强，不建议卡在第一版
- 通常需要正式授权和更高接入成本

参考官方文档：

- API 数据服务：https://www.wind.com.cn/mobile/WDS/sapi/zh.html
- 实时行情服务：https://www.wind.com.cn/mobile/WDS/marketdata/zh.html

## 4.6 东方财富 Choice

定位：

- 专业终端型升级路线
- 适合有条件时补强终端体验和研报/数据能力

参考官方文档：

- Choice 终端指南：https://choice.eastmoney.com/FileDownLoad/CFTG20221115.pdf

## 5. 第一版推荐接入顺序

为保证单票分析闭环尽快成型，推荐按下面顺序接入：

### 阶段 1

- `Tushare Pro`
  - 股票基础信息
  - 交易日历
  - A 股日线行情
  - 每日基础指标

阶段目标：

- 能完成标的识别
- 能得到当前价位、近阶段表现、量价和基础交易指标

### 阶段 2

- `巨潮资讯 / 交易所公告入口`
  - 公告列表检索
  - 公告正文获取
  - 定期报告与临时公告分类

阶段目标：

- 能给观点卡提供权威证据链
- 能判断催化是否有正式信披支持

### 阶段 3

- `AKShare`
  - 热门榜单
  - 异动
  - 板块和市场热度辅助

阶段目标：

- 支撑热门候选与事件热度解释
- 提高“为什么现在热”的解释能力

### 阶段 4

- `iFinD / Wind / Choice`

阶段目标：

- 用专业源替换部分免费或抓取型源
- 提升稳定性、时效性和简历叙事质量

## 6. Provider 设计建议

第一版就要做 Provider 抽象，不建议让 Agent 直接碰第三方 SDK。

建议接口边界如下。

## 6.1 market_data_provider

建议能力：

- `resolve_stock(query)`
- `get_stock_profile(symbol)`
- `get_price_snapshot(symbol)`
- `get_daily_bars(symbol, start, end)`
- `get_daily_factors(symbol, start, end)`
- `get_trading_calendar(start, end)`
- `get_sector_context(symbol, date_range)`

主要服务 Agent：

- `Intent Router Agent`
- `Stock Research Agent`
- `Hotlist Discovery Agent`

## 6.2 announcement_provider

建议能力：

- `search_announcements(symbol, start, end, keywords)`
- `get_announcement_detail(announcement_id)`
- `get_announcement_content(url_or_id)`
- `classify_announcement(document)`

主要服务 Agent：

- `Search Agent`
- `Stock Research Agent`
- `Evaluator / Trace Agent`

## 6.3 news_provider

建议能力：

- `search_news(query, start, end)`
- `search_company_news(symbol, start, end)`
- `cluster_news(items)`
- `score_news_relevance(items, target)`

主要服务 Agent：

- `Search Agent`
- `Stock Research Agent`
- `Synthesis Agent`

## 6.4 hotlist_provider

建议能力：

- `get_market_hotspots(date)`
- `get_hot_stocks(date, filters)`
- `get_limit_up_pool(date)`
- `get_abnormal_movers(date, window)`
- `get_theme_leaders(date, theme)`

主要服务 Agent：

- `Hotlist Discovery Agent`
- `Orchestrator Agent`

## 7. 各 Agent 与数据源映射

## 7.1 Intent Router Agent

依赖：

- `market_data_provider`

主要用途：

- 股票代码/名称解析
- 判断输入是否包含明确标的
- 判断是否需要进入 clarification

## 7.2 Orchestrator Agent

依赖：

- 不直接依赖具体数据源
- 只依赖统一的 provider 抽象

主要用途：

- 决定下一步该调用哪个 agent
- 判断是否继续补检索、补证据或降级输出

## 7.3 Stock Research Agent

依赖：

- `market_data_provider`
- `announcement_provider`
- `news_provider`

主要用途：

- 判断当前价位、预期价位、时间窗口
- 验证事件驱动是否成立
- 识别主叙事、驱动、风险和分歧

## 7.4 Search Agent

依赖：

- `announcement_provider`
- `news_provider`

主要用途：

- 搜公告
- 搜新闻
- 搜辅助背景资料
- 返回结构化证据而不是原始网页堆砌

## 7.5 Hotlist Discovery Agent

依赖：

- `market_data_provider`
- `hotlist_provider`
- `news_provider`

主要用途：

- 扫描市场热度
- 解释热度
- 形成候选池

## 7.6 Synthesis Agent

依赖：

- 上游 agent 的结构化结果

主要用途：

- 生成结论优先的双层观点卡
- 控制措辞、结论粒度和字段完整性

## 7.7 Evaluator / Trace Agent

依赖：

- 所有上游结构化 evidence

主要用途：

- 区分事实、推断和待验证项
- 评估证据完整度
- 记录 trace
- 输出低 / 中 / 高置信度参考

## 8. 第一版最低可用数据闭环

如果只为了先把 `single_stock_analysis` 做通，第一版最低可用闭环建议是：

- `Tushare Pro`
  - 股票基础信息
  - 日线行情
  - 每日基础指标
- `巨潮资讯 / 交易所公告`
  - 公告检索
  - 公告正文

这套组合已经能支撑：

- 标的识别
- 当前价位判断
- 近 1-2 周表现分析
- 公告驱动验证
- 初版观点卡生成

AKShare 可以稍后补上，用于增强：

- 热门发现
- 热点解释
- 板块/异动辅助

## 9. 风险与约束

## 9.1 商业与授权风险

- `AKShare` 官方明确声明数据接口和数据仅用于学术研究，不可做商业用途
- `iFinD / Wind / Choice` 通常涉及账号权限和商业授权
- 如果未来项目要公开演示、上线或商用，必须单独复核许可边界

## 9.2 稳定性风险

- 抓取型源更容易受网页结构变动影响
- 公告正文解析可能受 PDF/HTML 结构差异影响
- 不同源之间时间戳、代码格式、字段命名可能不一致

## 9.3 时效性风险

- 第一版不要默认自己拥有毫秒级或终端级实时能力
- 对于“当前价位”“当下热门”这类结论，必须在系统中记录数据时间戳

## 9.4 工程风险

- 不要在 agent 中直接拼接源站字段
- 必须先做 schema 标准化
- 必须在 provider 层统一代码格式、时区、日期与缺失值语义

## 10. 当前建议

当前最推荐的第一版落地方案是：

### 方案 A

- `Tushare Pro` 作为主市场数据底座
- `巨潮资讯 / 交易所公告` 作为权威信披证据层
- `AKShare` 作为热门和异动补充层

这是当前最平衡、最适合你这个项目定位的方案。

原因：

- 能尽快做出单票分析闭环
- 既有真实行情，也有真实信披
- 能支撑后续热门候选扩展
- 工程复杂度仍然可控

## 11. 下一步设计建议

如果继续往下推进，建议下一份文档直接进入系统设计层，重点定义：

- `Provider Schema`
- `Unified Evidence Schema`
- `Price Target Schema`
- `Trace Event Schema`
- `CLI Session State Schema`

这样后面就能从“产品定义”自然进入“可编码的系统结构”。
