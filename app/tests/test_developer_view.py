"""Pruebas de la vista developer (inspección de tablas + exportación)."""
from fastapi.testclient import TestClient


def _developer_headers(api_client: TestClient, db_session) -> dict[str, str]:
    """Crea un usuario con rol DEVELOPER (seed) y devuelve sus headers."""
    from app.modules.users import repository as users_repository
    from app.modules.users.schema import UserCreate
    from app.modules.users.service import assign_role_to_user, create_user

    user = create_user(
        db_session,
        UserCreate(username="qa_developer", password="QaPassword123", full_name="TEST QA DEVELOPER"),
    )
    role = users_repository.get_role_by_name(db_session, "DEVELOPER")
    assert role is not None, "el seed debe crear el rol DEVELOPER"
    assign_role_to_user(db_session, user.id, role.id)

    response = api_client.post(
        "/api/v1/auth/login",
        json={"username": "qa_developer", "password": "QaPassword123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_developer_view_requiere_autenticacion(api_client):
    assert api_client.get("/api/v1/developer/tablas").status_code == 401


def test_estiba_no_accede_a_developer_view(api_client, estiba_headers):
    response = api_client.get("/api/v1/developer/tablas", headers=estiba_headers)
    assert response.status_code == 403


def test_admin_no_accede_a_developer_view(api_client, admin_headers):
    # La vista developer es exclusiva del rol DEVELOPER; el ADMINISTRADOR ya no
    # tiene los permisos developer.* (evaluacion asincrona del docente).
    response = api_client.get("/api/v1/developer/tablas", headers=admin_headers)
    assert response.status_code == 403, response.text


def test_developer_lista_tablas_ordenadas_con_conteo(api_client, db_session):
    headers = _developer_headers(api_client, db_session)
    response = api_client.get("/api/v1/developer/tablas", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    names = [table["name"] for table in data]
    assert "encomiendas" in names
    assert "internal_users" in names
    assert names == sorted(names)
    users_table = next(table for table in data if table["name"] == "internal_users")
    assert users_table["row_count"] >= 4  # admin + qa_admin/secretaria/estiba + developer


def test_developer_pagina_datos_y_enmascara_sensibles(api_client, db_session):
    headers = _developer_headers(api_client, db_session)
    response = api_client.get(
        "/api/v1/developer/tablas/internal_users?page=1&page_size=2",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["table"] == "internal_users"
    assert data["page_size"] == 2
    assert len(data["rows"]) == 2
    assert data["total"] >= 4
    assert "password_hash" in data["columns"]
    for row in data["rows"]:
        assert row["password_hash"] == "•••"


def test_developer_tabla_inexistente_devuelve_404(api_client, db_session):
    headers = _developer_headers(api_client, db_session)
    response = api_client.get("/api/v1/developer/tablas/no_existe", headers=headers)
    assert response.status_code == 404


def test_developer_exporta_csv_y_excel(api_client, db_session, valid_shipment_payload):
    headers = _developer_headers(api_client, db_session)
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload)
    assert created.status_code == 201, created.text

    csv_response = api_client.get(
        "/api/v1/developer/tablas/encomiendas/export.csv", headers=headers
    )
    assert csv_response.status_code == 200, csv_response.text
    assert "text/csv" in csv_response.headers["content-type"]
    body = csv_response.content.decode("utf-8-sig")
    assert "codigo_encomienda" in body.splitlines()[0]
    assert created.json()["codigo_encomienda"] in body

    xls_response = api_client.get(
        "/api/v1/developer/tablas/encomiendas/export.xls", headers=headers
    )
    assert xls_response.status_code == 200, xls_response.text
    assert "application/vnd.ms-excel" in xls_response.headers["content-type"]
    assert b"<Workbook" in xls_response.content


def test_developer_schema_expone_metadata_de_columnas(api_client, db_session):
    headers = _developer_headers(api_client, db_session)
    response = api_client.get("/api/v1/developer/tablas/internal_users/schema", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["table"] == "internal_users"
    assert data["primary_key"] == ["id"]
    by_name = {column["name"]: column for column in data["columns"]}
    assert by_name["password_hash"]["is_sensitive"] is True
    assert by_name["id"]["is_primary_key"] is True
    assert by_name["username"]["is_sensitive"] is False


def test_estiba_no_puede_escribir_aunque_tenga_solo_lectura(api_client, estiba_headers):
    response = api_client.post(
        "/api/v1/developer/tablas/destinos/filas",
        headers=estiba_headers,
        json={"data": {"nombre": "Nueva Sede", "nombre_normalizado": "nueva sede"}},
    )
    assert response.status_code == 403


def test_developer_crud_completo_sobre_destinos(api_client, db_session):
    headers = _developer_headers(api_client, db_session)

    created = api_client.post(
        "/api/v1/developer/tablas/destinos/filas",
        headers=headers,
        json={"data": {"nombre": "Sede QA", "nombre_normalizado": "sede qa", "activo": True}},
    )
    assert created.status_code == 201, created.text
    row = created.json()["row"]
    assert row["nombre"] == "Sede QA"
    destino_id = row["id"]

    updated = api_client.put(
        "/api/v1/developer/tablas/destinos/filas",
        headers=headers,
        json={"pk": {"id": destino_id}, "data": {"activo": False}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["row"]["activo"] is False

    listing = api_client.get(
        "/api/v1/developer/tablas/destinos?page=1&page_size=200", headers=headers
    )
    assert any(r["id"] == destino_id for r in listing.json()["rows"])

    deleted = api_client.request(
        "DELETE",
        "/api/v1/developer/tablas/destinos/filas",
        headers=headers,
        json={"pk": {"id": destino_id}},
    )
    assert deleted.status_code == 204, deleted.text

    after = api_client.get(
        "/api/v1/developer/tablas/destinos?page=1&page_size=200", headers=headers
    )
    assert not any(r["id"] == destino_id for r in after.json()["rows"])


def test_developer_delete_de_fila_inexistente_devuelve_404(api_client, db_session):
    headers = _developer_headers(api_client, db_session)
    response = api_client.request(
        "DELETE",
        "/api/v1/developer/tablas/destinos/filas",
        headers=headers,
        json={"pk": {"id": 999999}},
    )
    assert response.status_code == 404


def test_developer_crear_usuario_sin_password_hash_da_error_amigable(api_client, db_session):
    """internal_users.password_hash es NOT NULL y sensible: no se puede crear via CRUD generico."""
    headers = _developer_headers(api_client, db_session)
    response = api_client.post(
        "/api/v1/developer/tablas/internal_users/filas",
        headers=headers,
        json={"data": {"username": "otro_qa", "full_name": "Otro QA"}},
    )
    assert response.status_code == 400, response.text
    assert "password_hash" in response.json()["detail"]


def test_developer_update_ignora_columnas_sensibles_en_el_payload(api_client, db_session):
    """Si el payload trae password_hash (p. ej. el valor enmascarado "•••"), se ignora
    silenciosamente: el hash real no se sobreescribe con el literal enmascarado."""
    headers = _developer_headers(api_client, db_session)
    users = api_client.get(
        "/api/v1/developer/tablas/internal_users?page=1&page_size=200", headers=headers
    ).json()
    secretaria_row = next(row for row in users["rows"] if row["username"] == "qa_secretaria")

    response = api_client.put(
        "/api/v1/developer/tablas/internal_users/filas",
        headers=headers,
        json={
            "pk": {"id": secretaria_row["id"]},
            "data": {"password_hash": "•••", "full_name": "Nombre Actualizado QA"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["row"]["full_name"] == "Nombre Actualizado QA"

    # Si el hash real se hubiera sobreescrito con el literal "•••", este login fallaria.
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "qa_secretaria", "password": "QaPassword123"},
    )
    assert login.status_code == 200, login.text
