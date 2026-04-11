"""CLI Session 运行时。

管理：会话状态、输入循环、Agent 调度委托。
"""

import logging
from datetime import datetime, timezone

import anthropic
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.styles import Style

from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.core.models import ExpandedOpinionCard, SessionState
from ashare_research_assistant.agents.router import RouterAgent
from ashare_research_assistant.agents.orchestrator import Orchestrator
from ashare_research_assistant.memory.profile_store import ProfileStore
from ashare_research_assistant.providers.base.market_data import MarketDataProvider
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
from ashare_research_assistant.providers.cninfo import CninfoAnnouncementProvider
from ashare_research_assistant.providers.akshare import AKShareNewsProvider
from ashare_research_assistant.providers.web_search_provider import WebSearchProvider
from ashare_research_assistant.services.clarification_engine import ClarificationEngine
from ashare_research_assistant.services.trace_store import TraceStore
from ashare_research_assistant.cli import renderer

logger = logging.getLogger(__name__)

_PROMPT_STYLE = Style.from_dict({
    "prompt": "cyan bold",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CLISession:
    def __init__(self) -> None:
        settings.ensure_local_dirs()

        # LLM 客户端
        client_kwargs = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            client_kwargs["base_url"] = settings.anthropic_base_url
        self._anthropic = anthropic.Anthropic(**client_kwargs)

        # Providers
        self._market: MarketDataProvider
        if settings.tushare_token:
            self._market = TushareMarketDataProvider(token=settings.tushare_token)
        elif settings.use_akshare_hotlist:
            # 使用 TushareProvider（无 token），功能受限但不影响 akshare 新闻/cninfo 公告
            self._market = TushareMarketDataProvider(token=None)
            logger.warning("未配置 TUSHARE_TOKEN，市场数据功能受限")
        else:
            self._market = TushareMarketDataProvider(token=None)
            logger.warning("未配置任何市场数据源，功能将受限")
        self._announcement = CninfoAnnouncementProvider(token=settings.tushare_token or None)
        self._news = AKShareNewsProvider()
        self._web_search = WebSearchProvider()

        # Services
        self._trace_store = TraceStore(path=settings.trace_store_path)
        self._profile_store = ProfileStore(path=settings.user_memory_path)
        self._clarification_engine = ClarificationEngine()

        # Agents
        self._router = RouterAgent(
            market_data_provider=self._market,
            anthropic_client=self._anthropic,
        )
        self._orchestrator = Orchestrator(
            market_data_provider=self._market,
            announcement_provider=self._announcement,
            news_provider=self._news,
            anthropic_client=self._anthropic,
            clarification_engine=self._clarification_engine,
            trace_store=self._trace_store,
            web_search=self._web_search,
        )

        # 会话状态
        self._state = SessionState(created_at=_now_iso(), updated_at=_now_iso())
        self._prompt_session: PromptSession = PromptSession(style=_PROMPT_STYLE)

    def run(self) -> None:
        renderer.print_welcome()

        while True:
            try:
                user_input = self._prompt_session.prompt("你 > ").strip()
            except (KeyboardInterrupt, EOFError):
                renderer.console.print("\n[dim]再见。[/dim]")
                break

            if not user_input:
                continue

            # 内置命令
            if user_input in ("退出", "exit", "quit"):
                renderer.console.print("[dim]再见。[/dim]")
                break
            if user_input in ("帮助", "help"):
                self._print_help()
                continue
            if user_input in ("展开", "expand"):
                self._handle_expand()
                continue

            self._handle_input(user_input)

    def _handle_input(self, user_input: str) -> None:
        self._state = self._state.new_turn(user_input)

        # 如果处于 clarifying 状态，直接处理追问回答
        if self._state.clarification.status == "pending":
            renderer.print_status("处理您的回答...")
            self._state = self._orchestrator.handle_clarification_answer(
                self._state, user_input
            )
        else:
            renderer.print_status("正在分析意图...")
            router_result = self._router.route(user_input)

            renderer.print_status(f"意图：{router_result.intent_type}（置信 {router_result.confidence:.0%}）")
            self._state = self._orchestrator.run(self._state, router_result)

        self._render_state()

    def _render_state(self) -> None:
        stage = self._state.stage

        if stage == "clarifying":
            question = self._state.clarification.question
            if question:
                renderer.print_clarification(question)

        elif stage == "completed":
            card = self._state.output_draft
            if card:
                renderer.print_opinion_card(card)

        elif stage == "degraded":
            renderer.print_degraded(self._state)

    def _handle_expand(self) -> None:
        if not self._state.working_memory.active_task:
            renderer.console.print("[dim]暂无可展开的分析结果。[/dim]")
            return
        try:
            expanded = ExpandedOpinionCard.model_validate_json(
                self._state.working_memory.active_task
            )
            renderer.print_expanded_card(expanded)
        except Exception as e:
            logger.error(f"展开失败: {e}")
            renderer.print_error("展开失败，数据异常。")

    def _print_help(self) -> None:
        from rich.panel import Panel
        renderer.console.print(Panel(
            "输入股票代码或名称进行分析\n"
            "  [cyan]展开[/cyan] — 查看完整分析\n"
            "  [cyan]退出[/cyan] — 退出程序",
            title="帮助",
            border_style="blue",
        ))
