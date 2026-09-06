import pytest
from fastapi import HTTPException
from sqlalchemy.engine import URL

import app.main as main_module
from app.core.config import Settings


def test_local_database_url_is_normalized() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://local_user:local_password@localhost/local_db",
    )

    assert settings.sqlalchemy_database_url == (
        "postgresql+psycopg2://local_user:local_password@localhost/local_db"
    )


def test_cloud_sql_url_preserves_special_password_characters() -> None:
    settings = Settings(
        _env_file=None,
        DB_USER="cloud_user",
        DB_PASSWORD="p@ss:/?#% word",
        DB_NAME="cloud_db",
        INSTANCE_UNIX_SOCKET="/cloudsql/project:southamerica-west1:instance",
    )

    url = settings.sqlalchemy_database_url

    assert isinstance(url, URL)
    assert url.username == "cloud_user"
    assert url.password == "p@ss:/?#% word"
    assert url.host == "/cloudsql/project:southamerica-west1:instance"
    assert url.database == "cloud_db"


@pytest.mark.parametrize("enabled", [False, True])
def test_startup_bootstrap_toggle(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    calls = []
    monkeypatch.setattr(main_module.settings, "auto_create_schema", enabled)
    monkeypatch.setattr(main_module, "bootstrap_database", lambda: calls.append(True))

    main_module.startup()

    assert calls == ([True] if enabled else [])


def test_readiness_reports_database_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "database_is_ready", lambda: True)
    assert main_module.ready() == {"status": "ready"}

    monkeypatch.setattr(main_module, "database_is_ready", lambda: False)
    with pytest.raises(HTTPException) as exc_info:
        main_module.ready()

    assert exc_info.value.status_code == 503
