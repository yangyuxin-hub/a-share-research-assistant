import logging
import sys

import typer
from rich.console import Console

app = typer.Typer(help="A 股投研助手 CLI")
console = Console()


def _setup_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # 压制第三方库噪声
    for noisy in ("httpx", "httpcore", "tushare", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def chat(
    log_level: str = typer.Option("WARNING", "--log-level", help="日志级别"),
) -> None:
    """启动交互式投研会话。"""
    _setup_logging(log_level)

    from ashare_research_assistant.config.settings import settings
    from ashare_research_assistant.cli.session import CLISession

    if not settings.anthropic_api_key:
        console.print("[bold red]错误：请在 .env 中配置 ASHARE_API_KEY[/bold red]")
        raise typer.Exit(1)

    if not settings.tushare_token and not settings.use_akshare_hotlist:
        console.print("[bold red]错误：请配置 TUSHARE_TOKEN 或启用 USE_AKSHARE_HOTLIST=true[/bold red]")
        raise typer.Exit(1)

    try:
        session = CLISession()
        session.run()
    except Exception as e:
        console.print(f"[bold red]启动失败：{e}[/bold red]")
        if log_level.upper() == "DEBUG":
            raise
        raise typer.Exit(1)


@app.command()
def web(
    port: int = typer.Option(7860, "--port", help="本地监听端口"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址，0.0.0.0 可局域网访问"),
    log_level: str = typer.Option("WARNING", "--log-level", help="日志级别"),
    reload: bool = typer.Option(False, "--reload", help="开发模式：代码改动自动重载", hidden=True),
) -> None:
    """启动 Web 浏览器界面。"""
    _setup_logging(log_level)

    from ashare_research_assistant.config.settings import settings

    if not settings.anthropic_api_key:
        console.print("[bold red]错误：请在 .env 中配置 ASHARE_API_KEY[/bold red]")
        raise typer.Exit(1)

    try:
        import uvicorn
    except ImportError:
        console.print("[bold red]错误：缺少依赖，请运行：uv sync[/bold red]")
        raise typer.Exit(1)

    settings.ensure_local_dirs()

    url = f"http://{'localhost' if host == '127.0.0.1' else host}:{port}"
    console.print(f"  启动中… 请在浏览器打开 [bold cyan]{url}[/bold cyan]")
    console.print("  Ctrl+C 退出\n")

    from ashare_research_assistant.web.server import create_app
    uvicorn.run(
        create_app() if not reload else
            "ashare_research_assistant.web.server:create_app",
        host=host,
        port=port,
        log_level="warning",
        factory=reload,
        reload=reload,
    )


@app.command()
def check() -> None:
    """检查配置和依赖是否正常。"""
    from ashare_research_assistant.config.settings import settings

    console.print("[bold]配置检查[/bold]")
    console.print(f"  ASHARE_API_KEY:    {'[green]OK 已配置[/green]' if settings.anthropic_api_key else '[red]NO 未配置[/red]'}")
    console.print(f"  TUSHARE_TOKEN:     {'[green]OK 已配置[/green]' if settings.tushare_token else '[red]NO 未配置[/red]'}")
    console.print(f"  APP_ENV:           {settings.app_env}")
    console.print(f"  MODEL:             {settings.anthropic_model}")
    console.print()

    # 测试 Tushare 连接
    if settings.tushare_token:
        try:
            console.print("测试 Tushare 连接...", end=" ")
            from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
            provider = TushareMarketDataProvider(token=settings.tushare_token)
            results = provider.resolve_stock("贵州茅台")
            if results:
                console.print(f"[green]OK 成功（找到 {len(results)} 条结果）[/green]")
            else:
                console.print("[yellow]连接正常但无返回数据[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ 失败：{e}[/red]")
