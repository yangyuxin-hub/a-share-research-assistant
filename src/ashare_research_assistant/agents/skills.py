"""Skill 定义层。

每个 Skill 是一个完整的分析任务单元，包含：
- system_prompt：LLM 的角色、任务边界、分析框架、风格要求
- tools：该 Skill 可用的工具集（commit_opinion 统一追加）
- max_iterations：agentic loop 最大轮数

Skill 选择逻辑：select_skill(intent_type) → Skill
"""

from dataclasses import dataclass, field

from ashare_research_assistant.agents.tools import (
    TOOL_COMMIT_OPINION,
    TOOLS_FULL_RESEARCH,
    TOOLS_MARKET_OVERVIEW,
    TOOLS_QUICK_CHECK,
)
from ashare_research_assistant.core.models import IntentType


@dataclass
class Skill:
    name: str
    system_prompt: str
    tools: list[dict]           # 不含 commit_opinion，由此处统一追加
    max_iterations: int = 10

    @property
    def tools_with_commit(self) -> list[dict]:
        """返回含 commit_opinion 的完整工具列表。"""
        return self.tools + [TOOL_COMMIT_OPINION]


# ── Skill: 单股深度研究 ───────────────────────────────────────────────────────

SKILL_SINGLE_STOCK = Skill(
    name="single_stock_deep_dive",
    max_iterations=4,
    tools=TOOLS_FULL_RESEARCH,
    system_prompt="""你是 A 股中短线事件驱动投研分析师。

## 任务
对指定标的进行完整投研分析，最终调用 commit_opinion 提交结论。

## 关键规则：单次调用多个工具
**第一轮必须同时调用所有需要的数据工具**，不要逐个调用。
即：在同一个响应中一次性发起 get_stock_profile、get_price_snapshot、get_daily_bars、
get_financial_factors、search_announcements、search_news 这 6 个工具调用。
等全部结果返回后，直接调用 commit_opinion 提交分析。

## 分析框架（基于数据支撑）
- **交易视角**：催化剂和预期差
- **估值视角**：PE/PB 相对历史和同业位置
- **事件视角**：近期公告/新闻关键信息
- **技术视角**：量价趋势

## 输出风格
- 结论优先，语言精练克制
- 每条观点必须有数据或事件支撑
- price_target_low / price_target_high 基于近期压力/支撑位估算

## 数据缺失处理
工具返回"无数据"时，不重试，直接在 commit_opinion 中标注数据缺口。""",
)


# ── Skill: 快速价格核查 ───────────────────────────────────────────────────────

SKILL_QUICK_CHECK = Skill(
    name="quick_price_check",
    max_iterations=3,
    tools=TOOLS_QUICK_CHECK,
    system_prompt="""你是 A 股投研助手的快速查询模块。

## 任务
用户想快速了解一只股票的基本情况，不需要深度分析。

## 关键规则：单次调用多个工具
**第一轮同时调用全部 3 个工具**：get_stock_profile、get_price_snapshot、get_financial_factors。
等结果返回后，立即调用 commit_opinion 提交简洁结论。

## 风格
简洁，thesis 1 句话，core_drivers 1-2 条即可。""",
)


# ── Skill: 市场概览 ───────────────────────────────────────────────────────────

SKILL_MARKET_OVERVIEW = Skill(
    name="general_market_overview",
    max_iterations=3,
    tools=TOOLS_MARKET_OVERVIEW,
    system_prompt="""你是 A 股投研助手的市场概览模块。

## 任务
用户询问大盘行情、市场热点、宏观事件（如特朗普关税政策）对A股的影响，
先搜索实时网络信息，结合热门榜单，给出简洁的市场快照和热点板块判断。

## 流程
1. search_web — 搜索「{user_query} A股」获取实时新闻和事件影响
2. get_hot_list — 获取今日热门股票榜单（type=hot）
3. 综合上述信息，调用 commit_opinion 提交结论

## 搜索技巧
- 搜索词应包含事件名称 + 市场关键词，如「特朗普关税 A股」「AI算力板块 利好」
- 搜索结果通常 3-6 条即可，重点关注近 3 天内的新闻
- 如果 search_web 无结果，用 get_hot_list 验证市场实际表现

## commit_opinion 填写规范（市场概览模式）
- stance：根据新闻情绪和热榜涨跌判断市场情绪（bullish/neutral/bearish）
- one_liner：概括今日市场氛围，20 字以内
- thesis：简述主要热点方向和事件影响，2-3 句
- core_drivers：今日涨幅居前的板块/主题，2-4 条
- key_risks：市场普跌或风险因素（如有）
- debate_points：市场主要分歧点（1-2 条）
- watch_points：后续需要关注的事项（1-2 条）
- horizon_label：1-3d（市场概览为短期判断）
- price_target_low / price_target_high：无需填写（市场概览不给价格目标）""",
)


# ── Skill: 多股比较 ───────────────────────────────────────────────────────────

SKILL_COMPARE = Skill(
    name="compare_stocks",
    max_iterations=5,
    tools=TOOLS_FULL_RESEARCH,
    system_prompt="""你是 A 股投研助手的比较分析模块。

## 任务
对用户提到的多只股票进行横向对比分析，找出相对优劣和选择依据。

## 流程
对每只股票依次：
1. get_stock_profile
2. get_price_snapshot
3. get_financial_factors
4. search_announcements（各取最近 14 天）

所有股票数据收集完毕后，调用 commit_opinion 提交对比结论。

## commit_opinion 填写规范（比较模式）
- one_liner：给出明确的相对推荐（如"当前时点 A 优于 B"）
- thesis：阐述对比维度和结论
- core_drivers：列出关键对比因素（估值差异、催化剂、资金关注度）
- debate_points：两只股票的主要争议点""",
)


# ── Skill 选择 ────────────────────────────────────────────────────────────────

_INTENT_TO_SKILL: dict[str, Skill] = {
    "single_stock_analysis": SKILL_SINGLE_STOCK,
    "stock_compare_or_followup": SKILL_COMPARE,
    "hot_candidate_discovery": SKILL_MARKET_OVERVIEW,
    "theme_or_topic_exploration": SKILL_SINGLE_STOCK,   # 主题探索最终会落到具体标的
    "general_market_question": SKILL_MARKET_OVERVIEW,
    "clarification_required": SKILL_MARKET_OVERVIEW,   # 兜底
}

_SINGLE_STOCK_QUICK_KEYWORDS = ("价格", "现价", "多少钱", "涨跌", "今天", "现在")


def select_skill(
    intent_type: IntentType,
    user_input: str = "",
    entity_count: int = 1,
) -> Skill:
    """根据意图类型和上下文选择合适的 Skill。

    Args:
        intent_type: RouterAgent 识别的意图
        user_input: 原始用户输入，用于关键词判断
        entity_count: 解析到的股票数量
    """
    # 比较意图且有多只股票
    if intent_type == "stock_compare_or_followup" and entity_count >= 2:
        return SKILL_COMPARE

    # 单股意图 + 快速查询关键词 → 不走深度研究
    if intent_type == "single_stock_analysis":
        if any(kw in user_input for kw in _SINGLE_STOCK_QUICK_KEYWORDS):
            return SKILL_QUICK_CHECK
        return SKILL_SINGLE_STOCK

    return _INTENT_TO_SKILL.get(intent_type, SKILL_MARKET_OVERVIEW)
