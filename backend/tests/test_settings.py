import psycopg.conninfo
from pydantic import SecretStr

from framegen.settings import Settings


def test_database_password_with_reserved_characters_is_quoted() -> None:
    settings = Settings(db_host="postgres", db_password=SecretStr("a/b+c@d#e 'f'"))
    parsed = psycopg.conninfo.conninfo_to_dict(settings.database_conninfo)
    assert parsed["host"] == "postgres"
    assert parsed["password"] == "a/b+c@d#e 'f'"
