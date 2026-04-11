"""Price Target Engine.

基于价格数据、证据和 LLM 判断，生成预期价位区间。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import anthropic

from ashare_research_assistant.core.models import (
    AnchorBasis,
    DailyBar,
    DailyFactor,
    EvidenceBundle,
    PriceSnapshot,
    PriceTarget,
)

logger = logging.getLogger(__name__)

_PRICE_TARGET_TOOL = {
    "name": "generate_price_target",
    "description": "基于价格和证据生成预期价位区间",
    "input_schema": {
        "type": "object",
        "properties": {
            "stance": {
                "type": "string",
                "enum": ["bullish", "neutral", "bearish"],
                "description": "多空倾向",
            },
            "expected_price_low": {
                "type": "number",
                "description": "预期价格下沿",
            },
            "expected_price_high": {
                "type": "number",
                "description": "预期价格上沿",
            },
            "target_label": {
                "type": "string",
                "description": "价位目标简述，如 '突破前高区间' 或 '维持震荡'",
            },
            "horizon": {
                "type": "string",
                "description": "判断期限，如 '1-2周'、'3-5交易日'",
            },
            "pricing_logic_summary": {
                "type": "string",
                "description": "定价逻辑摘要，100字以内",
            },
            "anchor_basis": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "event_repricing",
                                "narrative_strength",
                                "technical_resistance",
                                "technical_support",
                                "relative_strength",
                                "volume_structure",
                            ],
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["type", "description"],
                },
                "description": "锚定依据列表",
            },
        },
        "required": [
            "stance",
            "expected_price_low",
            "expected_price_high",
            "target_label",
            "horizon",
            "pricing_logic_summary",
            "anchor_basis",
        ],
    },
}


class PriceTargetEngine:
    def __init__(
        self,
        anthropic_client: anthropic.Anthropic,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._client = anthropic_client
        self._model = model

    def generate(
        self,
        company_name: str,
        price_snapshot: PriceSnapshot,
        daily_bars: list[DailyBar],
        daily_factors: list[DailyFactor],
        evidence_bundle: EvidenceBundle,
    ) -> PriceTarget:
        current_price = price_snapshot.current_price

        # 组织上下文摘要
        context = self._build_context(
            company_name, price_snapshot, daily_bars, daily_factors, evidence_bundle
        )

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=(
                    "你是一个专注 A 股中短线事件驱动研究的分析师。"
                    "基于提供的价格数据和证据，生成合理的预期价位区间。"
                    "预期价位必须有明确锚定依据，不能凭空给出。"
                    "期限以自然交易节奏为准（3-5天到2-3周）。"
                ),
                tools=[_PRICE_TARGET_TOOL],
                tool_choice={"type": "tool", "name": "generate_price_target"},
                messages=[{"role": "user", "content": context}],
            )
            result = self._extract_tool_result(response)
            if result:
                return self._build_price_target(current_price, result)
        except Exception as e:
            logger.error(f"PriceTargetEngine LLM 调用失败: {e}")

        return self._neutral_fallback(current_price)

    def _build_context(
        self,
        company_name: str,
        snapshot: PriceSnapshot,
        bars: list[DailyBar],
        factors: list[DailyFactor],
        evidence: EvidenceBundle,
    ) -> str:
        lines = [f"## 分析标的：{company_name}"]
        lines.append(f"当前价格：{snapshot.current_price:.2f}")
        if snapshot.pct_change is not None:
            lines.append(f"今日涨跌幅：{snapshot.pct_change:.2f}%")

        if bars:
            recent = bars[-10:]
            closes = [b.close for b in recent]
            lines.append(f"\n近{len(recent)}日收盘价：{[f'{c:.2f}' for c in closes]}")
            pct_changes = [b.pct_change for b in recent if b.pct_change is not None]
            if pct_changes:
                lines.append(f"近{len(pct_changes)}日涨跌幅：{[f'{p:.2f}%' for p in pct_changes]}")

        if factors:
            latest = factors[-1]
            if latest.turnover_rate:
                lines.append(f"最新换手率：{latest.turnover_rate:.2f}%")
            if latest.pe_ttm:
                lines.append(f"PE(TTM)：{latest.pe_ttm:.1f}")

        if evidence.items:
            lines.append(f"\n近期关键事件（共{len(evidence.items)}条）：")
            for item in evidence.items[:5]:
                lines.append(f"- [{item.kind}] {item.title}")

        return "\n".join(lines)

    def _extract_tool_result(self, response) -> Optional[dict]:
        for block in response.content:
            if block.type == "tool_use" and block.name == "generate_price_target":
                return block.input
        return None

    def _build_price_target(self, current_price: float, result: dict) -> PriceTarget:
        now = datetime.now(timezone.utc).isoformat()
        low = float(result["expected_price_low"])
        high = float(result["expected_price_high"])
        upside = (high - current_price) / current_price * 100 if current_price else None
        downside = (low - current_price) / current_price * 100 if current_price else None

        anchor_basis = [
            AnchorBasis(type=a["type"], description=a["description"])
            for a in result.get("anchor_basis", [])
        ]
        return PriceTarget(
            current_price=current_price,
            expected_price_low=low,
            expected_price_high=high,
            target_label=result["target_label"],
            horizon=result["horizon"],
            stance=result["stance"],
            anchor_basis=anchor_basis,
            pricing_logic_summary=result["pricing_logic_summary"],
            upside_pct=round(upside, 1) if upside is not None else None,
            downside_pct=round(downside, 1) if downside is not None else None,
            generated_at=now,
        )

    def _neutral_fallback(self, current_price: float) -> PriceTarget:
        now = datetime.now(timezone.utc).isoformat()
        return PriceTarget(
            current_price=current_price,
            expected_price_low=round(current_price * 0.95, 2),
            expected_price_high=round(current_price * 1.05, 2),
            target_label="数据不足，维持中性区间",
            horizon="1-2周",
            stance="neutral",
            anchor_basis=[],
            pricing_logic_summary="数据获取受限，以当前价±5%作为参考区间，置信度低。",
            upside_pct=5.0,
            downside_pct=-5.0,
            generated_at=now,
        )
