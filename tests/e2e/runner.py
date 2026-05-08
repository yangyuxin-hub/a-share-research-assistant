"""E2E 场景运行器。

用法：
    uv run python tests/run_e2e.py
    uv run python tests/run_e2e.py --scenarios greeting,knowledge_pe
    uv run python tests/run_e2e.py --output .local/my_run
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 确保 src 在路径中
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))  # 让 tests.e2e.* 可被导入

from ashare_research_assistant.agents.main_agent import MainAgent
from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.core.models import SessionState
from ashare_research_assistant.services.trace_store import TraceStore

from tests.e2e.checks import check_data_freshness, check_hallucination
from tests.e2e.scenarios import SCENARIOS, Scenario


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _NoOpTraceStore(TraceStore):
    def __init__(self): pass
    def append(self, e): pass
    def append_many(self, es): pass
    def read_by_turn(self, t): return []


def _make_agent(event_cb) -> MainAgent:
    """用真实 Provider 构建 Agent，注入诊断回调。"""
    import anthropic

    from ashare_research_assistant.providers.container import ProviderContainer

    if not settings.tushare_token:
        print("⚠  TUSHARE_TOKEN 未配置，行情/财务数据将受限")

    container = ProviderContainer(settings)
    bundle = container.bundle()

    client_kwargs: dict = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_base_url:
        client_kwargs["base_url"] = settings.anthropic_base_url

    return MainAgent(
        market_data_provider=bundle.market,
        announcement_provider=bundle.announcement,
        news_provider=bundle.news,
        hotlist_provider=bundle.hotlist,
        web_search=bundle.web_search,
        anthropic_client=anthropic.Anthropic(**client_kwargs),
        model=settings.anthropic_model,
        trace_store=_NoOpTraceStore(),
        event_cb=event_cb,
    )


def run_scenario(scenario: Scenario, agent: MainAgent, run_dir: Path) -> dict:
    """运行单个场景，写 JSONL，返回摘要 dict。"""
    events: list[dict] = []

    def _cb(event: dict):
        event.setdefault("ts", _now_iso())
        events.append(event)

    # 注入回调（同步安全）
    agent._event_cb = _cb

    state = SessionState(
        user_input=scenario.query,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )

    events.append({
        "event": "scenario_start",
        "id": scenario.id,
        "query": scenario.query,
        "expected_stage": scenario.expected_stage,
        "ts": _now_iso(),
    })

    t0 = time.perf_counter()
    result_state: Optional[SessionState] = None
    try:
        result_state = agent.run(state)
    except Exception as exc:
        events.append({"event": "agent_crash", "error": str(exc), "ts": _now_iso()})
    finally:
        agent._event_cb = None

    total_ms = int((time.perf_counter() - t0) * 1000)
    stage = result_state.stage if result_state else "crash"

    # 收集工具输出供检测用
    tool_results: dict[str, str] = {}
    for e in events:
        if e.get("event") == "tool_result":
            tool_results[e["name"]] = e.get("output", "")

    # 提取 commit_opinion 数据
    commit_ev = next((e for e in events if e.get("event") == "commit"), None)
    opinion = (
        commit_ev["data"]
        if commit_ev and commit_ev.get("type") == "commit_opinion"
        else None
    )

    freshness = check_data_freshness(events)
    hallucination_warnings = check_hallucination(tool_results, opinion)

    stage_ok = stage == scenario.expected_stage
    overall_ok = stage_ok and freshness["ok"] and len(hallucination_warnings) == 0

    events.append({
        "event": "scenario_end",
        "stage": stage,
        "expected_stage": scenario.expected_stage,
        "stage_ok": stage_ok,
        "total_duration_ms": total_ms,
        "data_freshness": freshness,
        "hallucination_warnings": hallucination_warnings,
        "ts": _now_iso(),
    })

    # 写 JSONL
    out_path = run_dir / f"{scenario.id}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    return {
        "id": scenario.id,
        "query": scenario.query,
        "description": scenario.description,
        "stage": stage,
        "expected_stage": scenario.expected_stage,
        "ok": overall_ok,
        "stage_ok": stage_ok,
        "total_duration_ms": total_ms,
        "data_freshness": freshness,
        "hallucination_warnings": hallucination_warnings,
        "jsonl": str(out_path),
    }


def run_all(
    scenario_ids: Optional[list[str]] = None,
    output_base: str = ".local/e2e_runs",
) -> list[dict]:
    """运行全部（或指定）场景，输出到 .local/e2e_runs/<timestamp>/。"""

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(output_base) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    selected = (
        [s for s in SCENARIOS if s.id in scenario_ids]
        if scenario_ids
        else SCENARIOS
    )
    if not selected:
        print(f"未找到场景: {scenario_ids}")
        return []

    print(f"运行目录: {run_dir}")
    print(f"场景数量: {len(selected)}\n")

    # 创建一个共享 agent（providers session 级复用）
    dummy_events: list = []
    agent = _make_agent(lambda e: dummy_events.append(e))
    agent._event_cb = None  # 先清空，run_scenario 里会按需注入

    summary: list[dict] = []

    for scenario in selected:
        print(f"▶ [{scenario.id}] {scenario.query}")
        result = run_scenario(scenario, agent, run_dir)

        icon = "✓" if result["ok"] else "✗"
        flag = "" if result["stage_ok"] else f" (预期 {result['expected_stage']}，实际 {result['stage']})"
        print(f"  {icon} stage={result['stage']}{flag}  {result['total_duration_ms']}ms")

        for w in result["hallucination_warnings"]:
            print(f"  ⚠ 幻觉: {w}")
        for issue in result["data_freshness"].get("issues", []):
            print(f"  ⚠ 时效: {issue['issue']}")

        # 打印工具调用序列（便于快速确认决策路径）
        jsonl_path = Path(result["jsonl"])
        tool_seq = []
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                if e.get("event") == "tool_result":
                    tool_seq.append(f"{e['name']}({e.get('duration_ms', '?')}ms)")
        if tool_seq:
            print(f"  工具链: {' → '.join(tool_seq)}")
        print()

        summary.append(result)

    # 写汇总
    summary_path = run_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    passed = sum(1 for s in summary if s["ok"])
    total = len(summary)
    print(f"结果: {passed}/{total} 通过")
    print(f"汇总: {summary_path}")

    return summary
