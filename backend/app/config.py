from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./reconcilr.db"
    audit_actor: str = "system"
    matching_amount_tolerance_absolute: Decimal = Decimal("1.00")
    matching_amount_tolerance_percentage: Decimal = Decimal("0.01")
    matching_date_tolerance_days: int = 7
    matching_fuzzy_minimum_score: int = 85
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
