"""Pytest 配置：共享 fixture"""

import os
import sys
from pathlib import Path

import pytest

# src 目录加入路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 加载 .env
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(str(env_path), override=False)
except ImportError:
    pass


@pytest.fixture(scope="session")
def api_key() -> str:
    from ashare_research_assistant.config.settings import settings

    key = settings.anthropic_api_key
    if not key:
        pytest.skip("CLAUDE_API_KEY 未配置")
    return key


@pytest.fixture(scope="session")
def anthropic_client(api_key):
    import anthropic

    from ashare_research_assistant.config.settings import settings

    kwargs = {"api_key": api_key}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return anthropic.Anthropic(**kwargs)


@pytest.fixture
def session_state():
    from datetime import datetime, timezone
    from ashare_research_assistant.core.models import SessionState

    now = datetime.now(timezone.utc).isoformat()
    return SessionState(created_at=now, updated_at=now)
