"""Evaluator / Trace Agent.

负责：评估证据完整度、输出置信度、区分事实与推断。
"""

import logging
from typing import Optional

import anthropic

from ashare_research_assistant.core.models import (
    EvaluationResult,
    EvidenceBundle,
    StockResearchDraft,
)

logger = logging.getLogger(__name__)

_EVAL_TOOL = {
    "name": "evaluate_research",
    "description": "评估研究草案的置信度和证据完整度",
    "input_schema": {
        "type": "object",
        "properties": {
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "整体置信度",
            },
            "evidence_coverage": {
                "type": "string",
                "enum": ["insufficient", "partial", "good"],
                "description": "证据覆盖程度",
            },
            "conclusion_stability": {
                "type": "string",
                "enum": ["fragile", "moderate", "stable"],
                "description": "结论稳定性（对新信息的敏感程度）",
            },
            "major_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "主要证据缺口",
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "需要用户注意的警示信息",
            },
            "factual_evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "被判定为事实的证据 ID",
            },
            "inferred_evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "被判定为推断的证据 ID",
            },
        },
        "required": ["confidence", "evidence_coverage", "conclusion_stability"],
    },
}


class EvaluatorAgent:
    def __init__(
        self,
        anthropic_client: anthropic.Anthropic,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._client = anthropic_client
        self._model = model

    def evaluate(
        self,
        draft: StockResearchDraft,
        evidence: EvidenceBundle,
    ) -> EvaluationResult:
        context = self._build_context(draft, evidence)
        result = self._call_llm(context)
        if result:
            return EvaluationResult(
                confidence=result.get("confidence", "low"),
                evidence_coverage=result.get("evidence_coverage", "insufficient"),
                conclusion_stability=result.get("conclusion_stability", "fragile"),
                major_gaps=result.get("major_gaps", []),
                warnings=result.get("warnings", []),
                factual_evidence_ids=result.get("factual_evidence_ids", []),
                inferred_evidence_ids=result.get("inferred_evidence_ids", []),
            )
        return self._fallback_evaluation(evidence)

    def _build_context(self, draft: StockResearchDraft, evidence: EvidenceBundle) -> str:
        lines = [
            f"## 研究草案：{draft.company_name}（{draft.symbol}）",
            f"立场：{draft.stance}",
            f"核心逻辑：{draft.thesis}",
            f"\n驱动因素：",
        ]
        for d in draft.core_drivers:
            lines.append(f"- {d}")
        lines.append(f"\n风险：")
        for r in draft.key_risks:
            lines.append(f"- {r}")
        if draft.unresolved_questions:
            lines.append(f"\n未解决问题：")
            for q in draft.unresolved_questions:
                lines.append(f"- {q}")

        lines.append(f"\n## 证据清单（{len(evidence.items)}条）")
        fact_count = sum(1 for i in evidence.items if i.factuality == "fact")
        inf_count = sum(1 for i in evidence.items if i.factuality == "inference")
        lines.append(f"事实性证据：{fact_count}条，推断性证据：{inf_count}条")
        if evidence.gaps:
            lines.append(f"数据缺口：{', '.join(evidence.gaps)}")
        if evidence.contradictory_signals:
            lines.append(f"矛盾信号：{', '.join(evidence.contradictory_signals)}")

        return "\n".join(lines)

    def _call_llm(self, context: str) -> Optional[dict]:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system="你是一个严谨的 A 股投研质检官，负责评估研究草案的置信度和证据完整度。要求客观，不偏袒多空任何一方。",
                tools=[_EVAL_TOOL],
                tool_choice={"type": "tool", "name": "evaluate_research"},
                messages=[{"role": "user", "content": context}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "evaluate_research":
                    return block.input
        except Exception as e:
            logger.error(f"EvaluatorAgent LLM 失败: {e}")
        return None

    def _fallback_evaluation(self, evidence: EvidenceBundle) -> EvaluationResult:
        item_count = len(evidence.items)
        if item_count >= 5:
            coverage = "partial"
        elif item_count >= 2:
            coverage = "insufficient"
        else:
            coverage = "insufficient"
        return EvaluationResult(
            confidence="low",
            evidence_coverage=coverage,
            conclusion_stability="fragile",
            major_gaps=evidence.gaps,
            warnings=["评估模块异常，置信度仅供参考"],
        )
