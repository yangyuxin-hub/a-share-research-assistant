"""Clarification Engine.

负责：生成结构化追问，帮助收敛问题。
"""

from ashare_research_assistant.core.models import (
    ClarificationOption,
    ClarificationQuestion,
    StockIdentifier,
)


class ClarificationEngine:
    def build_symbol_disambiguation(
        self, candidates: list[StockIdentifier]
    ) -> ClarificationQuestion:
        options = [
            ClarificationOption(
                label=f"{c.name}（{c.symbol}）",
                description=f"交易所：{c.exchange or 'N/A'}，行业：{c.industry or 'N/A'}",
                effect=f"分析 {c.name}",
            )
            for c in candidates[:4]
        ]
        options.append(
            ClarificationOption(
                label="换个标的 / 换主题词",
                description="上述都不是，请提供股票名称、代码，或换一个主题",
                effect="进入目标澄清",
            )
        )
        return ClarificationQuestion(
            reason="ambiguous_symbol",
            prompt="找到多个候选股票，请确认您想分析的是哪一只？",
            options=options,
            allow_free_text=True,
            recommended_option_id=options[0].id if options else None,
        )

    def build_theme_exploration(
        self,
        candidates: list[StockIdentifier],
        theme: str,
    ) -> ClarificationQuestion:
        """为主题探索创建澄清问题。"""
        options = [
            ClarificationOption(
                label=f"{c.name}（{c.symbol}）",
                description=f"交易所：{c.exchange or 'N/A'}",
                effect=f"分析 {c.name}",
            )
            for c in candidates[:6]
        ]
        options.append(ClarificationOption(
            label=f"换个主题词（当前：{theme}）",
            description="以上都不是，请换一个主题词，如：关税受益、AI算力、医药等",
            effect="切换到其他主题探索",
        ))
        return ClarificationQuestion(
            reason="theme_selection",
            prompt=f"「{theme}」相关股票如下，请选择您想深入分析的标的：",
            help_text=f"共找到 {len(candidates)} 只相关股票，显示前 {min(6, len(candidates))} 只",
            options=options,
            allow_free_text=True,
            recommended_option_id=options[0].id if options else None,
        )

    def build_goal_clarification(self, user_input: str) -> ClarificationQuestion:
        options = [
            ClarificationOption(
                label="单票深度分析",
                description="对该股票做完整的事件驱动分析，输出观点卡",
                effect="进入单票分析流程",
            ),
            ClarificationOption(
                label="发现热门候选",
                description="从当前市场热点中筛选值得研究的标的",
                effect="进入热股发现流程",
            ),
            ClarificationOption(
                label="快速行情查询",
                description="查看当前价格和近期走势",
                effect="仅查询价格数据",
            ),
        ]
        return ClarificationQuestion(
            reason="unclear_goal",
            prompt="请告诉我您想做什么？",
            help_text=f"您的输入：「{user_input[:50]}」",
            options=options,
            allow_free_text=True,
        )

    def resolve_answer(
        self,
        question: ClarificationQuestion,
        answer_text: str,
        candidates: list[StockIdentifier],
    ) -> StockIdentifier | None:
        """尝试从用户回答中解析出明确标的。"""
        text = answer_text.strip()

        # 按选项序号匹配（1/2/3/4），但排除超出 candidates 范围的兜底选项
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
            # 序号指向兜底选项（如"换个标的"），返回 None 触发目标澄清
            return None

        # 按名称或代码匹配
        for c in candidates:
            if c.symbol in text or c.name in text:
                return c

        return None
