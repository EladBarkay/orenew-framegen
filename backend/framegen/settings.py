"""Runtime settings, read from FRAMEGEN_* environment variables.

Defaults suit a developer running the services from `deploy/compose.yaml` on their own
machine. Production values come from the environment of the deployment (T-56).
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRAMEGEN_")

    database_url: str = "postgresql://framegen:framegen-dev@localhost:5432/framegen"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "framegen"
    s3_access_key: str = "framegen"
    s3_secret_key: SecretStr = SecretStr("framegen-dev-secret")


@lru_cache
def get_settings() -> Settings:
    return Settings()
