from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM 提供商选择："anthropic" 或 "codex"
    llm_provider: str = "anthropic"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # ChatGPT Codex（通过 ChatGPT Plus/Pro OAuth 订阅使用）
    codex_model: str = "codex-mini-latest"
    chatgpt_token_path: str = ".local/chatgpt_tokens.json"

    # 数据源
    tushare_token: str = ""

    # 功能开关
    use_akshare_hotlist: bool = True
    use_cninfo_provider: bool = True

    # 存储路径
    trace_store_path: str = ".local/trace.jsonl"
    user_memory_path: str = ".local/user_memory.json"

    # 运行环境
    app_env: str = "development"
    log_level: str = "INFO"
    default_analysis_mode: str = "single_stock"

    def ensure_local_dirs(self) -> None:
        Path(self.trace_store_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.user_memory_path).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
