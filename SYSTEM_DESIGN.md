# A 股投研助手系统设计

## 1. 设计目标

这份文档用于把已经确认的产品定义和数据源规划，进一步收敛成可编码的系统结构。

目标不是一次性定义所有实现细节，而是先固定第一版 MVP 最关键的系统骨架：

- Agent 职责边界
- Provider 抽象边界
- 统一状态模型
- 统一证据模型
- 统一追问模型
- 统一观点卡模型
- Trace 与记忆模型

## 2. 系统总览

第一版系统是一个交互式 CLI Research Copilot。

输入：

- 股票代码
- 股票名称
- 与股票相关的自然语言请求

输出：

- 结论优先的双层观点卡
- 必要时发起结构化问询
- 后台记录完整 trace

核心执行循环：

`Observe -> Think -> Act -> Update State -> Decide Next`

顶层组件：

- `CLI Session Runtime`
- `Intent Router Agent`
- `Orchestrator Agent`
- `Stock Research Agent`
- `Search Agent`
- `Hotlist Discovery Agent`
- `Synthesis Agent`
- `Evaluator / Trace Agent`
- `Memory Manager`
- `Provider Layer`

## 3. 架构分层

建议按以下五层实现。

### 3.1 Interface Layer

负责 CLI 交互和用户输入输出。

包括：

- 会话循环
- 轻量状态提示
- 结构化追问渲染
- 双层观点卡渲染

### 3.2 Orchestration Layer

负责意图判断、状态驱动和多 Agent 调度。

包括：

- `Intent Router Agent`
- `Orchestrator Agent`

### 3.3 Agent Capability Layer

负责各类研究、检索、发现和合成能力。

包括：

- `Stock Research Agent`
- `Search Agent`
- `Hotlist Discovery Agent`
- `Synthesis Agent`
- `Evaluator / Trace Agent`

### 3.4 Memory & Trace Layer

负责会话状态、长期记忆、证据链和过程记录。

包括：

- `Session Working Memory`
- `User Memory Profile`
- `Trace Store`

### 3.5 Provider Layer

负责对接真实行情与资讯源，并输出统一 schema。

包括：

- `market_data_provider`
- `announcement_provider`
- `news_provider`
- `hotlist_provider`

## 4. Agent 职责边界

## 4.1 Intent Router Agent

输入：

- 当前用户消息
- 最近会话摘要
- 用户长期偏好摘要

输出：

- `intent_type`
- `resolved_entities`
- `confidence`
- `clarification_needed`
- `clarification_reason`

职责：

- 判断当前输入是否有明确标的
- 股票代码/名称映射
- 判断是单票分析、追问、热门发现还是普通问题
- 识别是否需要先进入 Clarification Gate

不负责：

- 深度分析
- 最终观点生成

## 4.2 Orchestrator Agent

输入：

- `SessionState`
- `RouterResult`
- 当前已收集的 evidence

输出：

- 下一步动作决策
- 任务分发
- 状态更新
- 是否继续循环

职责：

- 驱动 Observe -> Think -> Act -> Update State -> Decide Next
- 根据当前状态决定调用哪个 agent
- 决定是继续补证据、触发追问、降级输出还是结束
- 决定何时进入 Synthesizer

不负责：

- 直接碰第三方数据源
- 直接生成最终观点卡文本

## 4.3 Search Agent

输入：

- 检索目标
- 时间范围
- 股票或主题上下文

输出：

- `EvidenceBundle`

职责：

- 搜公告
- 搜新闻
- 搜背景资料
- 返回结构化证据，不直接输出最终结论

## 4.4 Stock Research Agent

输入：

- 股票标的
- 时间窗口
- 已有 evidence

输出：

- `StockResearchDraft`

职责：

- 识别市场主叙事
- 提炼核心驱动与主要风险
- 基于事件驱动和交易锚点形成预期价位草案
- 输出支持、反对和待验证项

## 4.5 Hotlist Discovery Agent

输入：

- 日期或时间窗口
- 可选主题或市场范围约束

输出：

- `HotlistDraft`

职责：

- 扫描市场热点
- 从最热中筛出值得研究的候选
- 解释为什么热、属于哪条主线

## 4.6 Synthesis Agent

输入：

- `StockResearchDraft`
- `EvidenceBundle`
- `EvaluationResult`

输出：

- `OpinionCard`
- `ExpandedOpinionCard`

职责：

- 生成结论优先输出
- 控制措辞强度
- 保证字段完整
- 生成默认卡和展开卡两层结构

## 4.7 Evaluator / Trace Agent

输入：

- 当前 evidence
- research draft
- state transitions

输出：

- `EvaluationResult`
- `TraceEvents`

职责：

- 区分事实、推断和待验证项
- 评估证据是否足够
- 输出低 / 中 / 高置信度参考
- 记录完整过程

## 5. 核心状态模型

第一版建议把所有运行时状态集中到 `SessionState`。

## 5.1 SessionState

建议字段：

```ts
type SessionState = {
  sessionId: string;
  turnId: string;
  userInput: string;
  normalizedInput?: string;
  intent?: IntentType;
  intentConfidence?: number;
  stage: SessionStage;
  activeSymbol?: StockIdentifier;
  candidateSymbols: StockIdentifier[];
  activeTopic?: string;
  analysisWindow?: AnalysisWindow;
  clarification?: ClarificationState;
  evidenceBundle: EvidenceBundle;
  researchDraft?: StockResearchDraft;
  evaluation?: EvaluationResult;
  outputDraft?: OpinionCard;
  workingMemory: WorkingMemory;
  userMemorySnapshot?: UserMemoryProfile;
  trace: TraceEvent[];
  createdAt: string;
  updatedAt: string;
};
```

## 5.2 SessionStage

```ts
type SessionStage =
  | "observing"
  | "routing"
  | "clarifying"
  | "researching"
  | "searching"
  | "evaluating"
  | "synthesizing"
  | "completed"
  | "degraded";
```

## 5.3 AnalysisWindow

```ts
type AnalysisWindow = {
  mode: "auto" | "manual";
  startDate?: string;
  endDate?: string;
  horizonLabel?: "1-3d" | "1w" | "2w" | "custom";
  rationale?: string;
};
```

## 6. Provider Schema

Provider 层不应该把上游 SDK 原样暴露给 Agent。

第一版必须统一输出结构。

## 6.1 StockIdentifier

```ts
type StockIdentifier = {
  symbol: string;
  tsCode?: string;
  exchange?: "SSE" | "SZSE" | "BSE" | "UNKNOWN";
  name: string;
  aliases?: string[];
  industry?: string;
};
```

## 6.2 StockProfile

```ts
type StockProfile = {
  identifier: StockIdentifier;
  listDate?: string;
  area?: string;
  market?: string;
  conceptTags?: string[];
  businessSummary?: string;
  source: SourceMeta;
};
```

## 6.3 PriceSnapshot

```ts
type PriceSnapshot = {
  symbol: string;
  tradeDate: string;
  currentPrice: number;
  prevClose?: number;
  change?: number;
  pctChange?: number;
  high?: number;
  low?: number;
  open?: number;
  volume?: number;
  amount?: number;
  turnoverRate?: number;
  amplitude?: number;
  dataTimestamp: string;
  source: SourceMeta;
};
```

## 6.4 DailyBar

```ts
type DailyBar = {
  symbol: string;
  tradeDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  amount?: number;
  pctChange?: number;
  source: SourceMeta;
};
```

## 6.5 DailyFactor

```ts
type DailyFactor = {
  symbol: string;
  tradeDate: string;
  turnoverRate?: number;
  volumeRatio?: number;
  peTtm?: number;
  pb?: number;
  floatMarketValue?: number;
  totalMarketValue?: number;
  source: SourceMeta;
};
```

## 6.6 AnnouncementItem

```ts
type AnnouncementItem = {
  id: string;
  symbol: string;
  title: string;
  publishTime: string;
  category?: string;
  url?: string;
  summary?: string;
  exchange?: string;
  source: SourceMeta;
};
```

## 6.7 AnnouncementDocument

```ts
type AnnouncementDocument = {
  id: string;
  item: AnnouncementItem;
  rawText?: string;
  extractedSummary?: string;
  keyPoints?: string[];
  source: SourceMeta;
};
```

## 6.8 NewsItem

```ts
type NewsItem = {
  id: string;
  title: string;
  publishTime: string;
  outlet?: string;
  url?: string;
  summary?: string;
  relatedSymbols?: string[];
  topicTags?: string[];
  source: SourceMeta;
};
```

## 6.9 HotStockItem

```ts
type HotStockItem = {
  symbol: string;
  name: string;
  heatScore: number;
  momentumScore?: number;
  eventScore?: number;
  narrative?: string;
  reasons: string[];
  relatedThemes?: string[];
  source: SourceMeta;
};
```

## 6.10 SourceMeta

```ts
type SourceMeta = {
  provider: string;
  endpoint?: string;
  fetchedAt: string;
  dataTimestamp?: string;
  reliability: "official" | "licensed" | "aggregated" | "scraped";
};
```

## 7. Unified Evidence Schema

所有 agent 返回给 Orchestrator 的证据都应落成统一结构，避免每个 agent 各说各话。

## 7.1 EvidenceItem

```ts
type EvidenceItem = {
  id: string;
  kind:
    | "price"
    | "factor"
    | "announcement"
    | "news"
    | "company_profile"
    | "hotspot"
    | "inference"
    | "risk_signal";
  title: string;
  summary: string;
  symbol?: string;
  topic?: string;
  eventTime?: string;
  supportDirection?: "bullish" | "neutral" | "bearish" | "mixed";
  strength?: "low" | "medium" | "high";
  factuality: "fact" | "derived" | "inference";
  citations: Citation[];
  rawRef?: string;
};
```

## 7.2 Citation

```ts
type Citation = {
  sourceName: string;
  url?: string;
  documentId?: string;
  publishedAt?: string;
};
```

## 7.3 EvidenceBundle

```ts
type EvidenceBundle = {
  symbol?: string;
  query?: string;
  items: EvidenceItem[];
  gaps: string[];
  contradictorySignals: string[];
  lastUpdatedAt: string;
};
```

## 8. Clarification Schema

Clarification Gate 不是自由聊天，而是结构化交互。

## 8.1 ClarificationQuestion

```ts
type ClarificationQuestion = {
  id: string;
  reason:
    | "ambiguous_symbol"
    | "unclear_goal"
    | "missing_context"
    | "too_many_candidates";
  prompt: string;
  helpText?: string;
  options: ClarificationOption[];
  allowFreeText: boolean;
  recommendedOptionId?: string;
};
```

## 8.2 ClarificationOption

```ts
type ClarificationOption = {
  id: string;
  label: string;
  description: string;
  effect: string;
};
```

## 8.3 ClarificationState

```ts
type ClarificationState = {
  status: "idle" | "pending" | "answered" | "skipped";
  question?: ClarificationQuestion;
  answerText?: string;
  selectedOptionId?: string;
  askedAt?: string;
  answeredAt?: string;
};
```

## 9. Research Draft Schema

`StockResearchDraft` 是 Stock Research Agent 给 Synthesizer 的结构化中间结果。

```ts
type StockResearchDraft = {
  symbol: string;
  companyName: string;
  marketNarrative: string;
  thesis: string;
  coreDrivers: string[];
  keyRisks: string[];
  debatePoints: string[];
  watchPoints: string[];
  supportingEvidenceIds: string[];
  opposingEvidenceIds: string[];
  unresolvedQuestions: string[];
  priceTarget: PriceTarget;
  stance: "bullish" | "neutral" | "bearish";
  reasoningWindow: AnalysisWindow;
};
```

## 10. Price Target Schema

`PriceTarget` 是单票闭环最关键的 schema 之一。

```ts
type PriceTarget = {
  currentPrice: number;
  expectedPriceLow?: number;
  expectedPriceHigh?: number;
  targetLabel: string;
  horizon: string;
  stance: "bullish" | "neutral" | "bearish";
  anchorBasis: AnchorBasis[];
  pricingLogicSummary: string;
  upsidePct?: number;
  downsidePct?: number;
  generatedAt: string;
};
```

```ts
type AnchorBasis = {
  type:
    | "event_repricing"
    | "narrative_strength"
    | "technical_resistance"
    | "technical_support"
    | "relative_strength"
    | "volume_structure";
  description: string;
  weight?: number;
};
```

设计原则：

- 预期价位不是拍脑袋给单点
- 第一版优先支持区间和理由
- 必须显式输出期限
- 必须能解释锚定依据

## 11. Evaluation Schema

```ts
type EvaluationResult = {
  confidence: "low" | "medium" | "high";
  evidenceCoverage: "insufficient" | "partial" | "good";
  conclusionStability: "fragile" | "moderate" | "stable";
  majorGaps: string[];
  warnings: string[];
  factualEvidenceIds: string[];
  inferredEvidenceIds: string[];
};
```

## 12. 观点卡 Schema

## 12.1 OpinionCard

```ts
type OpinionCard = {
  symbol: string;
  companyName: string;
  stanceLabel: "看多" | "中性" | "看空";
  confidenceLabel: "低" | "中" | "高";
  oneLiner: string;
  currentPrice: number;
  expectedPriceText: string;
  horizonText: string;
  marketNarrative: string;
  coreDrivers: string[];
  keyRisks: string[];
  watchPoints: string[];
  generatedAt: string;
};
```

## 12.2 ExpandedOpinionCard

```ts
type ExpandedOpinionCard = OpinionCard & {
  debatePoints: string[];
  evidenceChain: EvidenceChainItem[];
  informationChanges: InformationChangeItem[];
  anchorSummary: string;
};
```

```ts
type EvidenceChainItem = {
  title: string;
  interpretation: string;
  direction: "support" | "oppose" | "mixed";
  citation?: Citation;
};
```

```ts
type InformationChangeItem = {
  time: string;
  change: string;
  implication: string;
};
```

## 13. Trace Event Schema

后台需要完整记录过程，但前台只展示轻量状态。

```ts
type TraceEvent = {
  id: string;
  turnId: string;
  stage: SessionStage;
  actor:
    | "router"
    | "orchestrator"
    | "search_agent"
    | "research_agent"
    | "hotlist_agent"
    | "synthesis_agent"
    | "evaluator";
  action: string;
  summary: string;
  inputRef?: string;
  outputRef?: string;
  rationale?: string;
  createdAt: string;
};
```

建议至少记录这些事件：

- intent 识别
- 标的解析
- clarification 触发
- provider 调用
- evidence 收集
- 研究草案生成
- 评估结果生成
- 最终观点卡输出

## 14. Memory Schema

## 14.1 UserMemoryProfile

```ts
type UserMemoryProfile = {
  userId: string;
  stylePreference?: string;
  riskPreference?: "aggressive" | "balanced" | "conservative";
  preferredFrameworks: string[];
  watchlistSymbols: string[];
  favoriteThemes: string[];
  dislikedPatterns: string[];
  outputPreference?: "brief_first" | "evidence_first" | "balanced";
  longTermHypotheses: string[];
  updatedAt: string;
};
```

## 14.2 WorkingMemory

```ts
type WorkingMemory = {
  activeTask?: string;
  confirmedConstraints: string[];
  recentSymbols: string[];
  recentTopics: string[];
  openQuestions: string[];
  provisionalConclusions: string[];
  memoryVersion: number;
};
```

## 15. CLI 会话流

第一版建议的运行流：

1. 用户输入消息
2. 系统更新 `SessionState.userInput`
3. Router 判断 intent 与标的解析
4. Orchestrator 判断：
   - 是否要进入 Clarification Gate
   - 是否直接进入单票研究
5. 若需追问，渲染 `ClarificationQuestion`
6. 用户回答后更新 `ClarificationState`
7. Orchestrator 调度 Search / Stock Research
8. Evaluator 评估证据完整度与置信度
9. Synthesis 生成 `OpinionCard`
10. CLI 渲染默认卡
11. 若用户继续追问，再渲染 `ExpandedOpinionCard`

## 16. 第一版落地建议

如果下一步进入代码实现，建议先按以下顺序搭建：

1. `types/schema`
   - 把本文档里的核心 schema 固化成代码类型

2. `providers/interfaces`
   - 定义 market / announcement / news / hotlist provider 抽象接口

3. `session_state`
   - 先把 CLI 会话状态机搭起来

4. `router + clarification`
   - 先实现单票分析闭环的入口收敛

5. `stock_research pipeline`
   - 先串起价格、公告、观点卡

6. `trace + memory`
   - 让每一步都可追踪

## 17. 当前结论

到这一步，项目已经有三层稳定定义：

- 产品层：[PRODUCT_BRIEF.md](./PRODUCT_BRIEF.md)
- 数据层：[DATA_SOURCE_PLAN.md](./DATA_SOURCE_PLAN.md)
- 系统层：当前这份文档

接下来如果继续推进，最自然的下一步是：

- 产出 `IMPLEMENTATION_PLAN.md`
- 把 schema 映射成目录结构
- 开始搭第一版 CLI 与 provider interface
