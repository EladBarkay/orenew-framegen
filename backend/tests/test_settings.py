import psycopg.conninfo
import pytest
from pydantic import SecretStr, ValidationError

from framegen.settings import Settings


def test_database_password_with_reserved_characters_is_quoted() -> None:
    settings = Settings(db_host="postgres", db_password=SecretStr("a/b+c@d#e 'f'"))
    parsed = psycopg.conninfo.conninfo_to_dict(settings.database_conninfo)
    assert parsed["host"] == "postgres"
    assert parsed["password"] == "a/b+c@d#e 'f'"


def test_production_refuses_development_passwords() -> None:
    with pytest.raises(ValidationError, match="development passwords"):
        Settings(environment="production")
    Settings(
        environment="production",
        db_password=SecretStr("real-db-password"),
        s3_secret_key=SecretStr("real-s3-secret"),
    )
