"""Runtime settings, read from FRAMEGEN_* environment variables.

Defaults suit a developer running the services from `deploy/compose.yaml` on their own
machine. Production values come from the environment of the deployment (T-56).
"""

from functools import lru_cache
from typing import Literal, Self

from psycopg.conninfo import make_conninfo
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DB_PASSWORD = "framegen-dev"
DEV_S3_SECRET_KEY = "framegen-dev-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRAMEGEN_")

    environment: Literal["development", "production"] = "development"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "framegen"
    db_user: str = "framegen"
    db_password: SecretStr = SecretStr(DEV_DB_PASSWORD)

    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "framegen"
    s3_access_key: str = "framegen"
    s3_secret_key: SecretStr = SecretStr(DEV_S3_SECRET_KEY)

    @model_validator(mode="after")
    def no_development_secrets_in_production(self) -> Self:
        if self.environment == "production" and (
            self.db_password.get_secret_value() == DEV_DB_PASSWORD
            or self.s3_secret_key.get_secret_value() == DEV_S3_SECRET_KEY
        ):
            raise ValueError("production must not use the development passwords; set real ones")
        return self

    @property
    def database_conninfo(self) -> str:
        """libpq connection string; quotes every value, so any password works."""
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password.get_secret_value(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
