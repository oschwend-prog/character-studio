from datetime import timedelta
from zoneinfo import ZoneInfo

from studio import config

ENV_VARS = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "POSTIZ_API_KEY")


def test_load_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc")
    monkeypatch.setenv("POSTIZ_API_KEY", "pz")
    s = config.load()
    assert s.database_url == "postgresql://u:p@h/db"
    assert s.supabase_url == "https://x.supabase.co"
    assert s.supabase_service_key == "svc"
    assert s.postiz_api_key == "pz"
    assert s.tz == ZoneInfo("Europe/London")


def test_load_missing_env_is_none(monkeypatch):
    for v in ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    s = config.load()
    assert s.database_url is None
    assert s.supabase_url is None
    assert s.supabase_service_key is None
    assert s.postiz_api_key is None


def test_load_empty_env_is_none(monkeypatch):
    # bin/studio exports empty strings when a Keychain item is missing; treat as unset
    for v in ENV_VARS:
        monkeypatch.setenv(v, "")
    s = config.load()
    assert s.database_url is None and s.postiz_api_key is None


def test_now_london_is_aware_and_london():
    now = config.now_london()
    assert now.tzinfo is not None
    assert now.tzinfo == ZoneInfo("Europe/London")
    assert now.utcoffset() in (timedelta(0), timedelta(hours=1))
