"""Skill Registry — Skill 的注册与意图路由。

核心思想：
- 每个 Skill 通过 skill_registry.register(skill, intents=[...]) 声明自己接管哪些意图
- select() 统一处理路由逻辑（多股比较、快速查询关键词等），不散落在各处
- 新增 Skill = 实例化 Skill 对象 + 一行 register()，不改已有代码

示例 — 新增 Skill：
    from agents.skill_registry import skill_registry
    from agents.skills import Skill

    SKILL_EARNINGS = Skill(
        name="earnings_analysis",
        tool_names=["get_stock_profile", "get_daily_bars", "search_announcements"],
        system_prompt="你是财报季专项分析师...",
        max_iterations=4,
    )

    skill_registry.register(
        SKILL_EARNINGS,
        intents=["earnings_season_question"],
    )
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 快速查询关键词 — 触发时走 quick_price_check 而不是 single_stock_deep_dive
_QUICK_KEYWORDS = ("价格", "现价", "多少钱", "涨跌", "今天", "现在", "当前")


class SkillRegistry:
    """Skill 注册表与意图路由器。

    - register(skill, intents) → 注册 skill 及其负责的意图类型
    - select(intent, user_input, entity_count) → 返回最合适的 Skill
    - get(name) → 按 skill 名查询
    """

    def __init__(self) -> None:
        self._skills: dict[str, object] = {}           # name -> Skill
        self._intent_map: dict[str, str] = {}          # intent -> skill_name
        self._quick_check_name: Optional[str] = None   # 快速查询兜底
        self._default_name: Optional[str] = None       # 无匹配时的兜底

    # ── 注册 ──────────────────────────────────────────────────────────────────

    def register(
        self,
        skill,
        intents: list[str] | None = None,
        *,
        is_quick_check: bool = False,
        is_default: bool = False,
    ) -> None:
        """注册一个 Skill。

        Args:
            skill       : Skill 实例
            intents     : 该 skill 负责的意图类型列表
            is_quick_check: 标记为"快速查询"兜底（单股意图 + 快速关键词时使用）
            is_default  : 标记为全局兜底（无意图匹配时使用）
        """
        name = skill.name
        if name in self._skills:
            logger.warning(f"Skill '{name}' 已注册，将被覆盖")
        self._skills[name] = skill
        if intents:
            for intent in intents:
                if intent in self._intent_map:
                    logger.warning(
                        f"意图 '{intent}' 原映射 '{self._intent_map[intent]}'，"
                        f"现改为 '{name}'"
                    )
                self._intent_map[intent] = name
        if is_quick_check:
            self._quick_check_name = name
        if is_default:
            self._default_name = name

    # ── 路由 ──────────────────────────────────────────────────────────────────

    def select(
        self,
        intent: str,
        user_input: str = "",
        entity_count: int = 1,
    ):
        """根据意图、用户输入、实体数量选择最合适的 Skill。

        路由优先级：
        1. 多实体比较 → compare_stocks
        2. 单股 + 快速关键词 → quick_price_check
        3. 意图直接映射 → _intent_map
        4. 全局兜底 → _default_name
        """
        # 1. 多股比较
        if intent == "stock_compare_or_followup" and entity_count >= 2:
            skill = self._skills.get("compare_stocks")
            if skill:
                return skill

        # 2. 单股 + 快速关键词 → 不走深度研究
        if intent == "single_stock_analysis" and self._quick_check_name:
            if any(kw in user_input for kw in _QUICK_KEYWORDS):
                skill = self._skills.get(self._quick_check_name)
                if skill:
                    return skill

        # 3. 意图直接映射
        skill_name = self._intent_map.get(intent)
        if skill_name:
            skill = self._skills.get(skill_name)
            if skill:
                return skill

        # 4. 全局兜底
        if self._default_name:
            return self._skills.get(self._default_name)

        # 最后兜底：返回第一个注册的 skill
        if self._skills:
            return next(iter(self._skills.values()))

        raise RuntimeError("SkillRegistry 为空，请先注册 Skill")

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def get(self, name: str):
        """按名称查询 Skill，未注册返回 None。"""
        return self._skills.get(name)

    def all_skills(self) -> list:
        return list(self._skills.values())

    def intent_map(self) -> dict[str, str]:
        return dict(self._intent_map)

    def __len__(self) -> int:
        return len(self._skills)

    def __repr__(self) -> str:
        return f"SkillRegistry({list(self._skills.keys())})"


# ── 全局单例 ──────────────────────────────────────────────────────────────────
# skills.py 导入后通过 skill_registry.register(...) 注册所有 Skill
skill_registry = SkillRegistry()
