"""Synthesis Agent.

负责：将 StockResearchDraft + EvaluationResult 合成结论优先的双层观点卡。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import anthropic

from ashare_research_assistant.core.models import (
    EvaluationResult,
    ExpandedOpinionCard,
    EvidenceBundle,
    EvidenceChainItem,
    OpinionCard,
    StockResearchDraft,
)

logger = logging.getLogger(__name__)

_STANCE_MAP = {"bullish": "看多", "neutral": "中性", "bearish": "看空"}
_CONF_MAP = {"low": "低", "medium": "中", "high": "高"}

_SYNTHESIS_TOOL = {
    "name": "synthesize_opinion",
    "description": "生成结论优先的观点卡文本",
    "input_schema": {
        "type": "object",
        "properties": {
            "one_liner": {
                "type": "string",
                "description": "一句话判断，20字以内，结论优先",
            },
            "expected_price_text": {
                "type": "string",
                "description": "预期价位描述，如 '短期目标 52-55 元（1-2周）'",
            },
            "horizon_text": {
                "type": "string",
                "description": "判断期限文字，如 '1-2 周'",
            },
            "anchor_summary": {
                "type": "string",
                "description": "价位锚定依据摘要，50字以内",
            },
            "evidence_chain": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "interpretation": {"type": "string"},
                        "direction": {
                            "type": "string",
                            "enum": ["support", "oppose", "mixed"],
                        },
                    },
                    "required": ["title", "interpretation", "direction"],
                },
                "description": "证据链，最多5条",
            },
        },
        "required": ["one_liner", "expected_price_text", "horizon_text", "anchor_summary"],
    },
}


class SynthesisAgent:
    def __init__(
        self,
        anthropic_client: anthropic.Anthropic,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._client = anthropic_client
        self._model = model

    def synthesize(
        self,
        draft: StockResearchDraft,
        evaluation: EvaluationResult,
        evidence: EvidenceBundle,
    ) -> tuple[OpinionCard, ExpandedOpinionCard]:
        now = datetime.now(timezone.utc).isoformat()
        result = self._call_llm(draft, evaluation)

        stance_label = _STANCE_MAP.get(draft.stance, "中性")
        confidence_label = _CONF_MAP.get(evaluation.confidence, "低")
        current_price = draft.price_target.current_price

        one_liner = result.get("one_liner", draft.thesis[:30]) if result else draft.thesis[:30]
        expected_price_text = (
            result.get("expected_price_text")
            if result
            else f"参考区间 {draft.price_target.expected_price_low:.2f}-{draft.price_target.expected_price_high:.2f} 元"
        )
        horizon_text = result.get("horizon_text", draft.price_target.horizon) if result else draft.price_target.horizon
        anchor_summary = result.get("anchor_summary", draft.price_target.pricing_logic_summary) if result else draft.price_target.pricing_logic_summary

        card = OpinionCard(
            symbol=draft.symbol,
            company_name=draft.company_name,
            stance_label=stance_label,
            confidence_label=confidence_label,
            one_liner=one_liner,
            current_price=current_price,
            expected_price_text=expected_price_text,
            horizon_text=horizon_text,
            market_narrative=draft.market_narrative,
            core_drivers=draft.core_drivers,
            key_risks=draft.key_risks,
            watch_points=draft.watch_points,
            generated_at=now,
        )

        evidence_chain: list[EvidenceChainItem] = []
        if result and result.get("evidence_chain"):
            for ec in result["evidence_chain"][:5]:
                evidence_chain.append(
                    EvidenceChainItem(
                        title=ec["title"],
                        interpretation=ec["interpretation"],
                        direction=ec["direction"],
                    )
                )

        expanded = ExpandedOpinionCard(
            **card.model_dump(),
            debate_points=draft.debate_points,
            evidence_chain=evidence_chain,
            information_changes=[],
            anchor_summary=anchor_summary,
        )

        return card, expanded

    def _call_llm(self, draft: StockResearchDraft, evaluation: EvaluationResult) -> Optional[dict]:
        context = self._build_context(draft, evaluation)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=(
                    "你是 A 股投研助手的观点卡撰写模块。"
                    "风格要求：结论优先、语言精练、克制，不用夸张词汇，不说'强烈推荐'之类的话。"
                    "输出语言：中文。"
                ),
                tools=[_SYNTHESIS_TOOL],
                tool_choice={"type": "tool", "name": "synthesize_opinion"},
                messages=[{"role": "user", "content": context}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "synthesize_opinion":
                    return block.input
        except Exception as e:
            logger.error(f"SynthesisAgent LLM 失败: {e}")
        return None

    def _build_context(self, draft: StockResearchDraft, evaluation: EvaluationResult) -> str:
        pt = draft.price_target
        lines = [
            f"## {draft.company_name}（{draft.symbol}）研究草案",
            f"立场：{_STANCE_MAP.get(draft.stance, '中性')}",
            f"置信度：{_CONF_MAP.get(evaluation.confidence, '低')}",
            f"当前价：{pt.current_price:.2f}",
            f"预期区间：{pt.expected_price_low:.2f} - {pt.expected_price_high:.2f}",
            f"建议期限：{pt.horizon}",
            f"\n核心逻辑：{draft.thesis}",
            f"\n市场叙事：{draft.market_narrative}",
            f"\n驱动因素：{'; '.join(draft.core_drivers)}",
            f"主要风险：{'; '.join(draft.key_risks)}",
        ]
        if draft.debate_points:
            lines.append(f"分歧点：{'; '.join(draft.debate_points)}")
        if evaluation.warnings:
            lines.append(f"\n注意事项：{'; '.join(evaluation.warnings)}")
        return "\n".join(lines)
