"""用户长期记忆 Profile 持久化（本地 JSON 文件）。"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ashare_research_assistant.core.models import UserMemoryProfile

logger = logging.getLogger(__name__)


class ProfileStore:
    def __init__(self, path: str = ".local/user_memory.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> UserMemoryProfile:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return UserMemoryProfile.model_validate(data)
            except Exception as e:
                logger.warning(f"加载用户记忆失败，使用默认值: {e}")
        return UserMemoryProfile(updated_at=datetime.now(timezone.utc).isoformat())

    def save(self, profile: UserMemoryProfile) -> None:
        try:
            self._path.write_text(
                profile.model_dump_json(indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"保存用户记忆失败: {e}")

    def add_to_watchlist(self, symbol: str) -> None:
        profile = self.load()
        if symbol not in profile.watchlist_symbols:
            profile.watchlist_symbols.append(symbol)
            profile.updated_at = datetime.now(timezone.utc).isoformat()
            self.save(profile)
