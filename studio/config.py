"""Settings from the environment, plus London-time helpers.

Secrets are never read from files. Locally, ``bin/studio`` exports them from the
macOS Keychain; in CI they come from GitHub secrets. Anything unset (or set to an
empty string) is ``None``.
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

LONDON = ZoneInfo("Europe/London")


class Settings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    database_url: str | None = None
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    postiz_api_key: str | None = None
    tz: ZoneInfo = LONDON


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None


def load() -> Settings:
    return Settings(
        database_url=_env("DATABASE_URL"),
        supabase_url=_env("SUPABASE_URL"),
        supabase_service_key=_env("SUPABASE_SERVICE_KEY"),
        postiz_api_key=_env("POSTIZ_API_KEY"),
    )


def now_london() -> datetime:
    """Current time as an aware datetime in Europe/London."""
    return datetime.now(LONDON)
