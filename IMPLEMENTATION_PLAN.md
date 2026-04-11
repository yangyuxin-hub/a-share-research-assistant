# A 股投研助手实现计划

## 1. 目标

这份文档把当前已经确定的产品定义、数据源规划和系统设计，进一步映射成：

- 第一版技术栈建议
- 目录结构建议
- 核心模块拆分
- MVP 开发顺序
- 每阶段完成标准

目标是让项目可以直接进入实现，而不是继续停留在抽象设计层。

## 2. 第一版实现原则

第一版优先级：

- 先把单票分析闭环做通
- 先让 CLI 交互会话成立
- 先让 Clarification Gate 和双层观点卡成立
- 先用真实数据源打通最小可用闭环
- 所有外部数据都必须经过 Provider 抽象层

非目标：

- 不追求一开始就做全量前端界面
- 不追求一开始就做所有 intent
- 不追求一开始就做全市场复杂热股扫描
- 不追求一开始就引入过多供应商 SDK

## 3. 第一版技术栈建议

建议第一版使用 Python。

原因：

- 对接 Tushare Pro、AKShare 更顺手
- 做 CLI、数据处理、原型验证的效率高
- 便于后续接 LLM 编排和多 Agent 流程

建议技术组合：

- `Python 3.11+`
- `uv` 或 `poetry` 管理依赖
- `pydantic` 做 schema 与配置校验
- `typer` 或 `prompt_toolkit` 做 CLI 交互
- `httpx` 做网络请求
- `rich` 做 CLI 卡片和状态展示
- `pytest` 做基础测试

如果追求第一版 CLI 体验，建议：

- `rich` 负责输出卡片和轻量状态
- `prompt_toolkit` 负责连续会话输入

## 4. 目录结构建议

建议第一版先按以下结构组织：

```text
src/
  ashare_research_assistant/
    __init__.py
    app.py
    cli/
      __init__.py
      main.py
      session.py
      renderer.py
    config/
      __init__.py
      settings.py
    core/
      __init__.py
      models/
        __init__.py
        session.py
        provider.py
        evidence.py
        clarification.py
        research.py
        opinion.py
        trace.py
        memory.py
      enums.py
      errors.py
    providers/
      __init__.py
      base/
        __init__.py
        market_data.py
        announcement.py
        news.py
        hotlist.py
      tushare/
        __init__.py
        market_data_provider.py
      cninfo/
        __init__.py
        announcement_provider.py
      akshare/
        __init__.py
        hotlist_provider.py
      fallback/
        __init__.py
        news_provider.py
    agents/
      __init__.py
      router.py
      orchestrator.py
      search.py
      stock_research.py
      hotlist.py
      synthesis.py
      evaluator.py
    memory/
      __init__.py
      profile_store.py
      working_memory.py
    services/
      __init__.py
      symbol_resolver.py
      price_target_engine.py
      evidence_builder.py
      trace_store.py
      clarification_engine.py
    pipelines/
      __init__.py
      single_stock_pipeline.py
    tests/
      __init__.py
      unit/
      integration/
```

## 5. 核心模块拆分

## 5.1 `core/models`

职责：

- 定义系统级 schema
- 对齐 `SYSTEM_DESIGN.md`

首批必须包含：

- `SessionState`
- `StockIdentifier`
- `EvidenceItem`
- `ClarificationQuestion`
- `StockResearchDraft`
- `PriceTarget`
- `EvaluationResult`
- `OpinionCard`
- `TraceEvent`
- `UserMemoryProfile`

建议：

- 第一版统一使用 `pydantic` model
- 所有 agent 与 provider 的输入输出都尽量类型化

## 5.2 `providers/base`

职责：

- 定义统一 provider interface

首批必须包含：

- `MarketDataProvider`
- `AnnouncementProvider`
- `NewsProvider`
- `HotlistProvider`

要求：

- Agent 不允许直接 import 第三方 SDK
- 所有 provider 必须返回统一 schema

## 5.3 `providers/tushare`

职责：

- 实现第一版主市场数据 provider

第一批能力：

- `resolve_stock`
- `get_stock_profile`
- `get_price_snapshot`
- `get_daily_bars`
- `get_daily_factors`

第一阶段只做单票分析闭环需要的能力，不要一开始追求全量接口。

## 5.4 `providers/cninfo`

职责：

- 实现公告检索与公告正文获取

第一批能力：

- `search_announcements`
- `get_announcement_detail`
- `get_announcement_content`

注意：

- 第一版先确保公告列表和摘要级证据能工作
- 正文解析可以先做轻量版本，再逐步增强

## 5.5 `providers/akshare`

职责：

- 实现热门与异动补充能力

第一批能力：

- `get_market_hotspots`
- `get_hot_stocks`

这一层可以稍后接入，不要阻塞单票分析主线。

## 5.6 `agents/router.py`

职责：

- 识别 intent
- 做股票代码/名称解析
- 识别是否需要 clarification

第一版范围：

- 重点支持 `single_stock_analysis`
- 能识别 follow-up
- 其他 intent 可以先降级处理

## 5.7 `agents/orchestrator.py`

职责：

- 驱动核心循环
- 决定下一步动作

第一版不要做成“超级智能黑盒”，建议先做：

- 规则驱动 + LLM 判定辅助

第一版最少支持这些决策：

- 直接进入分析
- 触发 clarification
- 调 Search Agent
- 调 Stock Research Agent
- 调 Evaluator
- 调 Synthesis

## 5.8 `agents/search.py`

职责：

- 拉取公告和新闻
- 统一组织成 `EvidenceBundle`

第一版重点：

- 先把公告证据做好
- 新闻层可以先轻量

## 5.9 `agents/stock_research.py`

职责：

- 对单票做结构化分析

第一版重点输出：

- 市场主叙事
- 核心驱动
- 主要风险
- 观察点
- 预期价位草案
- 看多 / 中性 / 看空

## 5.10 `services/price_target_engine.py`

职责：

- 专门负责预期价位逻辑

原因：

- 这是项目辨识度最高的能力之一
- 不建议全部塞进 agent prompt

第一版输入：

- 当前价位
- 近阶段走势
- 事件驱动信息
- 若干技术锚点

第一版输出：

- 预期价位区间
- 期限
- 锚定依据
- 上下行空间

## 5.11 `agents/evaluator.py`

职责：

- 评估证据完整度
- 输出低 / 中 / 高置信度
- 区分事实与推断

## 5.12 `agents/synthesis.py`

职责：

- 把 research draft 和 evaluation 变成结论优先的观点卡

第一版必须支持：

- 默认极简卡
- 展开完整卡

## 5.13 `services/trace_store.py`

职责：

- 记录完整 trace

第一版建议：

- 先存本地 JSONL 或 SQLite
- 不要一开始就上复杂 observability 平台

## 5.14 `memory/`

职责：

- 管长期偏好和工作记忆

第一版建议：

- `UserMemoryProfile` 先用本地 JSON 文件
- `WorkingMemory` 跟随 session runtime 内存态

## 5.15 `cli/`

职责：

- 提供连续会话式 CLI

第一版必须支持：

- 连续输入
- 轻量状态提示
- 结构化追问显示
- 观点卡显示
- `展开` 或类似命令查看完整卡

## 6. MVP 开发顺序

## 阶段 1：项目骨架与 schema

目标：

- 项目能跑起来
- 核心类型先固定

任务：

- 初始化项目
- 建立目录结构
- 实现 `core/models`
- 实现基础配置和日志

完成标准：

- 能 import 所有核心 schema
- 基础测试通过

## 阶段 2：Provider Interface + Tushare 接入

目标：

- 打通真实市场数据底座

任务：

- 定义 provider base interface
- 接入 Tushare
- 实现股票解析、价格快照、日线、基础因子

完成标准：

- 能通过股票代码/名称拿到统一格式的价格与基础数据

## 阶段 3：Router + Session Runtime

目标：

- 用户可以在 CLI 中连续输入并完成标的识别

任务：

- 实现 CLI 会话循环
- 实现 Router
- 接入轻量状态展示

完成标准：

- 用户输入股票代码/名称后，系统能识别为单票分析入口

## 阶段 4：Clarification Gate

目标：

- 系统能在必要时发起结构化追问

任务：

- 实现 `ClarificationQuestion` 渲染
- 实现 `ClarificationState` 更新
- 实现基础追问策略

完成标准：

- 标的歧义或目标不清时，系统能稳定追问并继续流程

## 阶段 5：公告 Search + Evidence Bundle

目标：

- 形成“价格 + 公告”最小证据链

任务：

- 接入公告 provider
- 实现 Search Agent
- 输出统一 `EvidenceBundle`

完成标准：

- 单票分析时，系统能拿到真实公告证据

## 阶段 6：Stock Research + Price Target

目标：

- 形成单票研究草案

任务：

- 实现 `StockResearchDraft`
- 实现 `PriceTargetEngine`
- 生成看多 / 中性 / 看空与价位区间

完成标准：

- 能从真实价格和证据生成结构化研究草案

## 阶段 7：Evaluator + Opinion Card

目标：

- 输出可读结果

任务：

- 实现 `EvaluationResult`
- 实现 `OpinionCard`
- 实现默认卡与展开卡渲染

完成标准：

- CLI 能输出一张完整的单票观点卡

## 阶段 8：Trace + Memory

目标：

- 让过程可追踪，可复盘

任务：

- 实现 trace 存储
- 实现工作记忆和用户记忆

完成标准：

- 一次分析结束后，能完整回放关键过程

## 阶段 9：Hotlist 能力补充

目标：

- 为第二入口铺路

任务：

- 接入 AKShare 热门与异动
- 实现 Hotlist Discovery Agent 初版

完成标准：

- 用户没有明确股票时，系统能给出初版热门候选

## 7. 建议的里程碑

## Milestone 1

范围：

- 阶段 1-3

交付结果：

- 可以启动 CLI
- 可以识别股票并进入单票分析流程

## Milestone 2

范围：

- 阶段 4-7

交付结果：

- 完整单票分析闭环可用
- 能追问
- 能出观点卡

这是第一版最重要的里程碑。

## Milestone 3

范围：

- 阶段 8-9

交付结果：

- 有 trace、有记忆
- 开始支持热门候选能力

## 8. 建议的配置管理

建议用环境变量管理第三方密钥和开关。

示例：

```env
TUSHARE_TOKEN=
USE_AKSHARE_HOTLIST=true
USE_CNINFO_PROVIDER=true
TRACE_STORE_PATH=.local/trace.jsonl
USER_MEMORY_PATH=.local/user_memory.json
```

建议增加：

- `APP_ENV`
- `LOG_LEVEL`
- `DEFAULT_ANALYSIS_MODE`

## 9. 测试建议

第一版不要把测试做得过重，但这几类必须有：

- schema 单元测试
- provider 适配层测试
- Router 意图识别测试
- Clarification Gate 流程测试
- 单票分析集成测试

重点不是追求超高覆盖率，而是守住：

- 输入解析
- 状态流转
- 价格目标输出
- 观点卡字段完整性

## 10. 当前最推荐的下一步

如果现在开始真正写代码，最自然的下一步是：

1. 初始化 Python 项目结构
2. 先把 `core/models` 和 `providers/base` 建起来
3. 接入 `TushareMarketDataProvider`
4. 做一个最小 CLI，会输入股票代码并返回统一 `PriceSnapshot`

这个顺序最稳，因为它能最快验证：

- 技术栈是否顺手
- Provider 抽象是否合理
- 单票分析主线是否真的能跑起来

## 11. 当前结论

到现在为止，项目已经具备四层明确文档：

- 产品定义：[PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md)
- 数据规划：[DATA_SOURCE_PLAN.md](./DATA_SOURCE_PLAN.md)
- 系统设计：[SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md)
- 实现计划：当前这份文档

如果继续推进，下一步就不该再停留在文档层，而应该开始：

- 建项目骨架
- 定类型
- 接第一个真实 provider
