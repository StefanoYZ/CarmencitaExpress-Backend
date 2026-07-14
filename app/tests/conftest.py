import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SUNAT_ENV", "mock")

from app.core.database import Base, get_db
from app.main import app
from app.modules.charge_logs import model as charge_logs_model  # noqa: F401
from app.modules.clients import model as clients_model  # noqa: F401
from app.modules.destinations import model as destinations_model  # noqa: F401
from app.modules.destinations.service import seed_default_destinations
from app.modules.shipments import model as shipments_model  # noqa: F401
from app.modules.sunat import model as sunat_model  # noqa: F401
from app.modules.users import model as users_model  # noqa: F401
from app.modules.users import repository as users_repository
from app.modules.users.schema import UserCreate
from app.modules.users.service import (
    assign_role_to_user,
    create_user,
    seed_initial_access_control,
)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    seed_initial_access_control(db)
    seed_default_destinations(db)
    _create_role_user(db, "qa_admin", "ADMINISTRADOR")
    _create_role_user(db, "qa_secretaria", "SECRETARIA")
    _create_role_user(db, "qa_estiba", "ESTIBA")

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def admin_headers(api_client: TestClient) -> dict[str, str]:
    return _login_headers(api_client, "qa_admin")


@pytest.fixture()
def secretaria_headers(api_client: TestClient) -> dict[str, str]:
    return _login_headers(api_client, "qa_secretaria")


@pytest.fixture()
def estiba_headers(api_client: TestClient) -> dict[str, str]:
    return _login_headers(api_client, "qa_estiba")


@pytest.fixture()
def valid_shipment_payload() -> dict:
    return {
        "remitente_tipo_documento": "DNI",
        "remitente_numero_documento": "70123456",
        "remitente_nombre": "TEST QA REMITENTE",
        "remitente_direccion": "Av. Pruebas 100",
        "remitente_telefono": "987654321",
        "remitente_correo": "remitente.qa@test.local",
        "destinatario_tipo_documento": "DNI",
        "destinatario_numero_documento": "70876543",
        "destinatario_nombre": "TEST QA DESTINATARIO",
        "destinatario_direccion": "Jr. Destino 200",
        "destinatario_telefono": "976543210",
        "destinatario_correo": "destinatario.qa@test.local",
        "origen": "Trujillo",
        "destino": "Angasmarca",
        "descripcion": "Paquete de prueba QA",
        "tipo_contenido": "ROPA",
        "peso_kg": 10.5,
        "largo_cm": 40,
        "ancho_cm": 30,
        "alto_cm": 20,
        "fragilidad": "MEDIA",
        "orientacion_base": "LARGO_ANCHO",
    }


def _create_role_user(db: Session, username: str, role_name: str) -> None:
    user = create_user(
        db,
        UserCreate(
            username=username,
            password="QaPassword123",
            full_name=f"TEST QA {role_name}",
        ),
    )
    role = users_repository.get_role_by_name(db, role_name)
    assign_role_to_user(db, user.id, role.id)


def _login_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "QaPassword123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
