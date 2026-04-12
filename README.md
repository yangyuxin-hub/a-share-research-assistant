# A股投研助手

交互式 A 股投研 CLI Copilot，面向中短线事件驱动研究。

从高噪声信息中形成**可追踪、可解释的投资观点**——输入股票代码或名称，输出带证据链的双层观点卡。

---

## 功能特性

- **意图路由**：自动识别单票分析、主题探索、热股发现等意图，标的歧义时主动追问而非盲目分析
- **多工具 Agentic Loop**：LLM 自主决定调用数据工具的顺序和深度，支持公告、新闻、行情、估值等多维度数据
- **双层观点卡**：极简卡展示核心判断（方向 + 价位 + 期限 + 置信度），完整卡包含证据链、分歧点、后续观察项
- **持续会话**：多轮对话，支持追问、比较、策略调整
- **本地 Trace**：完整分析过程记录为 JSONL，可审计可复盘

---

## 快速开始

### 前置要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Anthropic API Key（必须）
- Tushare Token（推荐，用于行情和公告数据）

### 安装

```bash
git clone <repo-url>
cd a股投研助手
uv sync
```

### 配置

复制环境变量模板并填写：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
ANTHROPIC_API_KEY=sk-ant-...
TUSHARE_TOKEN=your_tushare_token
```

完整配置项见下方[配置说明](#配置说明)。

### 验证配置

```bash
uv run ashare check
```

### 启动

```bash
uv run ashare chat
```

---

## 使用示例

```
你 > 600519
你 > 贵州茅台最近值得买吗
你 > 帮我看看半导体板块最近有什么机会
你 > 对比一下宁德时代和比亚迪
```

退出：`Ctrl+C` 或 `Ctrl+D`

---

## 配置说明

| 变量 | 说明 | 默认值 | 必需 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API 密钥 | — | 必须 |
| `ANTHROPIC_BASE_URL` | 自定义 API 端点（中转） | — | 可选 |
| `ANTHROPIC_MODEL` | 使用的模型 | `claude-sonnet-4-6` | 可选 |
| `TUSHARE_TOKEN` | Tushare 行情数据 token | — | 推荐 |
| `USE_AKSHARE_HOTLIST` | 启用 AKShare 热股发现 | `true` | 可选 |
| `USE_CNINFO_PROVIDER` | 启用 CNINFO 公告数据源 | `true` | 可选 |
| `LOG_LEVEL` | 日志级别 | `INFO` | 可选 |
| `TRACE_STORE_PATH` | Trace 日志路径 | `.local/trace.jsonl` | 可选 |
| `USER_MEMORY_PATH` | 用户记忆文件路径 | `.local/user_memory.json` | 可选 |

---

## 架构概览

```
用户输入
  ↓
[Intent Router]  ← agentic loop，含 resolve_stock / commit_intent 工具
  ↓
[Orchestrator]   ← 判断是否追问，选择技能，委托执行
  ↓
[LLM Agentic Loop]  ← 自主调用数据工具，迭代探索
  │  get_stock_profile / get_price_snapshot / get_daily_bars
  │  get_financial_factors / search_announcements / search_news
  └─ commit_opinion  ← 提交最终观点
  ↓
[Trace Store]    ← 记录全过程
  ↓
[CLI Renderer]   ← 双层观点卡渲染
```

### 技能（Skill）

| 技能 | 触发场景 | 迭代轮次 |
|---|---|---|
| `single_stock_deep_dive` | 单票深度研究 | 最多 12 轮 |
| `quick_price_check` | 快速价格查询 | 最多 5 轮 |
| `general_market_overview` | 市场概览 / 热股发现 | — |

### 数据源

| 数据源 | 提供内容 |
|---|---|
| Tushare Pro | 日线行情、基础资料、估值因子、公司公告 |
| AKShare | 财经新闻、热股榜单 |
| DuckDuckGo Search | 补充网络信息 |

---

## 项目结构

```
src/ashare_research_assistant/
├── cli/            # CLI 入口、会话管理、输出渲染
├── config/         # 配置管理（Pydantic Settings）
├── agents/         # Router、Orchestrator、工具定义、技能
├── core/models/    # 统一 Pydantic Schema（观点卡、证据、追踪等）
├── providers/      # 数据源抽象层（tushare / cninfo / akshare）
├── services/       # 澄清引擎、Trace 存储、用户记忆
└── memory/         # 用户长期偏好持久化
```

---

## 开发

```bash
# 运行测试
uv run pytest

# 查看 trace 日志
cat .local/trace.jsonl | python -m json.tool | less
```

---

## 免责声明

本工具仅供个人学习和研究使用，输出内容不构成任何投资建议。市场有风险，投资需谨慎。
