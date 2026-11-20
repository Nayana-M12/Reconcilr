from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./reconcilr.db"
    audit_actor: str = "system"
    app_env: str = "production"
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    llm_redact: bool = False
    matching_amount_tolerance_absolute: Decimal = Decimal("1.00")
    matching_amount_tolerance_percentage: Decimal = Decimal("0.01")
    matching_date_tolerance_days: int = 7
    matching_fuzzy_minimum_score: int = 85
    exception_date_gap_days: int = 30
    exception_medium_amount_threshold: Decimal = Decimal("10.00")
    exception_high_amount_threshold: Decimal = Decimal("100.00")
    exception_critical_amount_threshold: Decimal = Decimal("1000.00")
    approval_small_amount_threshold: Decimal = Decimal("100.00")
    approval_medium_amount_threshold: Decimal = Decimal("1000.00")
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
