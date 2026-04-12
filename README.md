# A股投研助手

交互式 A 股投研 CLI Copilot，面向中短线事件驱动研究。

从高噪声信息中形成**可追踪、可解释的投资观点**——输入股票代码或名称，输出带证据链的双层观点卡。

---

## 功能特性

- **统一 MainAgent**：意图路由与数据分析合为一体，LLM 自主决定调用哪些工具，节省一次模型调用，延迟降低约 30%
- **12 个工具全挂载**：resolve_stock、行情、财务因子、公告、新闻、热门榜单、网络搜索，全部交给模型自主决策
- **歧义主动追问**：多候选或意图模糊时调用 commit_clarification，而非盲目分析
- **双层观点卡**：极简卡展示方向+价位+置信度，展开卡含证据链、多空分歧、观察项
- **全链路 Trace**：分析过程 JSONL 记录，支持审计复盘

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
CLAUDE_API_KEY=sk-ant-...
CLAUDE_BASE_URL=https://your-proxy.com
TUSHARE_TOKEN=your_tushare_token
```

> **注意**：项目故意不使用 `ANTHROPIC_API_KEY` 这个变量名。Claude Code CLI 会扫描当前目录的 `.env`，如果发现 `ANTHROPIC_API_KEY` 会切换为 API Key 模式并覆盖全局 OAuth 登录。

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
| `CLAUDE_API_KEY` | Claude API 密钥（避免与 Claude Code CLI 冲突，不用标准名） | — | 必须 |
| `CLAUDE_BASE_URL` | 自定义 API 端点（中转） | — | 可选 |
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
[MainAgent]  ← 意图路由 + Agentic Loop 合一，12个工具全挂，LLM自主决策
  │  resolve_stock / get_stock_profile / get_price_snapshot
  │  get_daily_bars / get_financial_factors
  │  search_announcements / search_news
  │  get_hot_list / search_web
  └─ commit_opinion / commit_answer / commit_clarification
  ↓
[Trace Store]    ← 记录全过程
  ↓
[CLI Renderer]   ← 双层观点卡渲染
```

### 意图决策

MainAgent 根据用户输入自主判断：

| 场景 | 工具调用路径 |
|------|-------------|
| 股票名称/代码 | resolve_stock → 数据工具 → commit_opinion |
| 大盘/宏观/事件 | search_web / get_hot_list → commit_opinion |
| 概念/术语/问候 | commit_answer（直接回答） |
| 多候选/意图模糊 | commit_clarification（追问） |

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
