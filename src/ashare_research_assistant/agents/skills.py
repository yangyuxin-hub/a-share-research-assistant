"""Skill 定义层 + 注册。

每个 Skill 是一个完整的分析任务单元，包含：
- name          : 唯一标识
- tool_names    : 该 Skill 可用的工具名称列表（从 tool_registry 取 schema）
- system_prompt : LLM 的角色、任务边界、分析框架、风格要求
- max_iterations: agentic loop 最大轮数

架构变化（v2）：
- Skill.tool_names 替代原来的 Skill.tools（list[dict]），解耦 schema 嵌入
- Skill.tools / Skill.tools_with_commit 变为属性，从 tool_registry 懒取
- 所有 Skill 通过 skill_registry.register() 自注册
- 新增 Skill = 实例化 + 调 skill_registry.register()，不改已有代码

新增 Skill 示例：
    MY_SKILL = Skill(
        name="my_skill",
        tool_names=["get_stock_profile", "search_web"],
        system_prompt="你是...",
        max_iterations=3,
    )
    skill_registry.register(MY_SKILL, intents=["my_intent"])
"""

from dataclasses import dataclass, field

from ashare_research_assistant.agents.skill_registry import skill_registry
from ashare_research_assistant.agents.tools import (
    TOOLS_FULL_RESEARCH_NAMES,
    TOOLS_MARKET_OVERVIEW_NAMES,
    TOOLS_QUICK_CHECK_NAMES,
)
from ashare_research_assistant.core.models import IntentType


@dataclass
class Skill:
    name: str
    tool_names: list[str]          # 工具名称列表，schema 从 tool_registry 懒取
    system_prompt: str
    max_iterations: int = 10

    @property
    def tools(self) -> list[dict]:
        """当前 Skill 可用的工具 schema 列表（不含 commit_opinion）。"""
        from ashare_research_assistant.agents.tool_registry import tool_registry
        return tool_registry.get_schemas(self.tool_names)

    @property
    def tools_with_commit(self) -> list[dict]:
        """含 commit_opinion 的完整工具列表（供 agentic loop 使用）。"""
        from ashare_research_assistant.agents.tool_registry import tool_registry
        return tool_registry.get_schemas(self.tool_names + ["commit_opinion"])


# ── Skill: 单股深度研究 ───────────────────────────────────────────────────────

SKILL_SINGLE_STOCK = Skill(
    name="single_stock_deep_dive",
    max_iterations=4,
    tool_names=TOOLS_FULL_RESEARCH_NAMES,
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
    tool_names=TOOLS_QUICK_CHECK_NAMES,
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
    tool_names=TOOLS_MARKET_OVERVIEW_NAMES,
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
    tool_names=TOOLS_FULL_RESEARCH_NAMES,
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


# ── Skill 注册 ────────────────────────────────────────────────────────────────
# 意图 → skill 的映射在这里统一声明。
# 新增 Skill：实例化后调 skill_registry.register()，无需改 select_skill()。

skill_registry.register(
    SKILL_SINGLE_STOCK,
    intents=["single_stock_analysis", "theme_or_topic_exploration"],
)

skill_registry.register(
    SKILL_QUICK_CHECK,
    is_quick_check=True,  # 单股意图 + 快速关键词时自动路由到此
)

skill_registry.register(
    SKILL_MARKET_OVERVIEW,
    intents=["hot_candidate_discovery", "general_market_question", "clarification_required"],
    is_default=True,  # 无匹配意图时的兜底
)

skill_registry.register(
    SKILL_COMPARE,
    intents=["stock_compare_or_followup"],
)


# ── select_skill（向后兼容）───────────────────────────────────────────────────

def select_skill(
    intent_type: IntentType,
    user_input: str = "",
    entity_count: int = 1,
) -> Skill:
    """根据意图类型和上下文选择合适的 Skill。

    委托给 skill_registry.select()，保持接口不变。
    """
    return skill_registry.select(intent_type, user_input, entity_count)
