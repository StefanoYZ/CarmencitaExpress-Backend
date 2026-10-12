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
from app.modules.agencies import model as agencies_model  # noqa: F401
from app.modules.agencies.model import Agency
from app.modules.charge_logs import model as charge_logs_model  # noqa: F401
from app.modules.clients import model as clients_model  # noqa: F401
from app.modules.destinations import model as destinations_model  # noqa: F401
from app.modules.destinations.model import Destination
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
    _create_role_user(db, "qa_admin", "ADMIN_GENERAL")
    operational_agency = _create_operational_test_agency(db)
    _create_role_user(db, "qa_secretaria", "SECRETARIA", agency_id=operational_agency.id)
    _create_role_user(db, "qa_estiba", "ESTIBA", agency_id=operational_agency.id)

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
        "aviso_privacidad_aceptado": True,
        "version_aviso_privacidad": "2026-10-11",
    }


def _create_role_user(db: Session, username: str, role_name: str, agency_id: int | None = None) -> None:
    user = create_user(
        db,
        UserCreate(
            username=username,
            password="QaPassword123",
            full_name=f"TEST QA {role_name}",
        ),
    )
    role = users_repository.get_role_by_name(db, role_name)
    if agency_id is None:
        assign_role_to_user(db, user.id, role.id)
        return
    persisted = users_repository.get_user_by_id(db, user.id)
    persisted.agency_id = agency_id
    persisted.roles.append(role)
    db.add(persisted)
    db.commit()


def _create_operational_test_agency(db: Session) -> Agency:
    destination = Destination(name="QA Operativa", normalized_name="qa operativa", is_active=True)
    db.add(destination)
    db.flush()
    agency = Agency(code="AG-QA-OPERATIVA", destination_id=destination.id, is_active=True)
    db.add(agency)
    db.commit()
    db.refresh(agency)
    return agency


def _login_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "QaPassword123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
