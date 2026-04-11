"""Stock Research Agent.

负责：基于价格数据和证据，生成结构化 StockResearchDraft。
"""

import logging
from typing import Optional

import anthropic

from ashare_research_assistant.core.models import (
    AnalysisWindow,
    DailyBar,
    DailyFactor,
    EvidenceBundle,
    PriceSnapshot,
    StockIdentifier,
    StockProfile,
    StockResearchDraft,
)
from ashare_research_assistant.services.price_target_engine import PriceTargetEngine

logger = logging.getLogger(__name__)

_RESEARCH_TOOL = {
    "name": "generate_research_draft",
    "description": "生成单票结构化研究草案",
    "input_schema": {
        "type": "object",
        "properties": {
            "market_narrative": {
                "type": "string",
                "description": "市场当前对该股的主叙事，1-2句话",
            },
            "thesis": {
                "type": "string",
                "description": "核心投资逻辑，2-3句话",
            },
            "core_drivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "核心驱动因素，3-5条",
            },
            "key_risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "主要风险，2-4条",
            },
            "debate_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "多空分歧点，1-3条",
            },
            "watch_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "后续观察点，1-3条",
            },
            "stance": {
                "type": "string",
                "enum": ["bullish", "neutral", "bearish"],
                "description": "多空倾向",
            },
            "horizon_label": {
                "type": "string",
                "enum": ["1-3d", "1w", "2w", "custom"],
                "description": "分析时间窗口",
            },
            "unresolved_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "尚未解决的关键问题",
            },
        },
        "required": [
            "market_narrative", "thesis", "core_drivers",
            "key_risks", "stance", "horizon_label",
        ],
    },
}

_SYSTEM_PROMPT = """你是一个专注 A 股中短线事件驱动的投研分析师。

分析框架：
1. 交易视角：市场为什么此刻在交易它？
2. 投研视角：这个逻辑本身是否成立？

重点关注：事件驱动、催化剂、预期差、拥挤度。
输出语言：中文。
要求：结论优先，避免废话，每条观点须有数据或事件支撑。"""


class StockResearchAgent:
    def __init__(
        self,
        anthropic_client: anthropic.Anthropic,
        price_target_engine: PriceTargetEngine,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._client = anthropic_client
        self._price_target_engine = price_target_engine
        self._model = model

    def analyze(
        self,
        symbol: StockIdentifier,
        profile: Optional[StockProfile],
        price_snapshot: PriceSnapshot,
        daily_bars: list[DailyBar],
        daily_factors: list[DailyFactor],
        evidence_bundle: EvidenceBundle,
    ) -> StockResearchDraft:
        context = self._build_context(symbol, profile, price_snapshot, daily_bars, daily_factors, evidence_bundle)

        draft_result = self._call_llm(context)

        price_target = self._price_target_engine.generate(
            company_name=symbol.name,
            price_snapshot=price_snapshot,
            daily_bars=daily_bars,
            daily_factors=daily_factors,
            evidence_bundle=evidence_bundle,
        )

        if draft_result:
            window = AnalysisWindow(
                mode="auto",
                horizon_label=draft_result.get("horizon_label", "1w"),
            )
            return StockResearchDraft(
                symbol=symbol.symbol,
                company_name=symbol.name,
                market_narrative=draft_result.get("market_narrative", ""),
                thesis=draft_result.get("thesis", ""),
                core_drivers=draft_result.get("core_drivers", []),
                key_risks=draft_result.get("key_risks", []),
                debate_points=draft_result.get("debate_points", []),
                watch_points=draft_result.get("watch_points", []),
                unresolved_questions=draft_result.get("unresolved_questions", []),
                supporting_evidence_ids=[
                    i.id for i in evidence_bundle.items
                    if i.support_direction == "bullish"
                ],
                opposing_evidence_ids=[
                    i.id for i in evidence_bundle.items
                    if i.support_direction == "bearish"
                ],
                price_target=price_target,
                stance=draft_result.get("stance", "neutral"),
                reasoning_window=window,
            )

        # LLM 失败降级
        return StockResearchDraft(
            symbol=symbol.symbol,
            company_name=symbol.name,
            market_narrative="数据获取受限，无法生成完整叙事",
            thesis="数据不足，置信度低",
            core_drivers=[],
            key_risks=["数据获取受限"],
            price_target=price_target,
            stance="neutral",
            reasoning_window=AnalysisWindow(mode="auto", horizon_label="1w"),
        )

    def _build_context(
        self,
        symbol: StockIdentifier,
        profile: Optional[StockProfile],
        snapshot: PriceSnapshot,
        bars: list[DailyBar],
        factors: list[DailyFactor],
        evidence: EvidenceBundle,
    ) -> str:
        lines = [f"## 分析标的：{symbol.name}（{symbol.symbol}）"]

        if profile:
            if profile.identifier.industry:
                lines.append(f"行业：{profile.identifier.industry}")
            if profile.market:
                lines.append(f"市场：{profile.market}")

        lines.append(f"\n### 价格数据")
        lines.append(f"当前价：{snapshot.current_price:.2f}")
        if snapshot.pct_change is not None:
            lines.append(f"今日涨跌：{snapshot.pct_change:+.2f}%")
        if snapshot.turnover_rate is not None:
            lines.append(f"换手率：{snapshot.turnover_rate:.2f}%")

        if bars:
            recent = bars[-15:]
            lines.append(f"\n近{len(recent)}交易日行情：")
            for b in recent[-5:]:
                pct = f"{b.pct_change:+.2f}%" if b.pct_change is not None else "N/A"
                lines.append(f"  {b.trade_date}: 收{b.close:.2f} 涨跌{pct}")

        if factors:
            lf = factors[-1]
            lines.append(f"\n最新估值因子：")
            if lf.pe_ttm:
                lines.append(f"  PE(TTM): {lf.pe_ttm:.1f}")
            if lf.pb:
                lines.append(f"  PB: {lf.pb:.2f}")
            if lf.total_market_value:
                lines.append(f"  总市值: {lf.total_market_value/10000:.1f}亿")

        if evidence.items:
            lines.append(f"\n### 近期关键事件（{len(evidence.items)}条）")
            for item in evidence.items[:8]:
                lines.append(f"- [{item.kind}][{item.event_time or ''}] {item.title}")
                if item.summary and item.summary != item.title:
                    lines.append(f"  摘要：{item.summary[:100]}")

        if evidence.gaps:
            lines.append(f"\n数据缺口：{', '.join(evidence.gaps)}")

        return "\n".join(lines)

    def _call_llm(self, context: str) -> Optional[dict]:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                tools=[_RESEARCH_TOOL],
                tool_choice={"type": "tool", "name": "generate_research_draft"},
                messages=[{"role": "user", "content": context}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "generate_research_draft":
                    return block.input
        except Exception as e:
            logger.error(f"StockResearchAgent LLM 调用失败: {e}")
        return None
