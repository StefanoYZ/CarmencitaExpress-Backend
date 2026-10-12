from fastapi.testclient import TestClient

from app.modules.shipments.model import Shipment


def _create_agency(client: TestClient, headers: dict[str, str], destination_id: int) -> dict:
    response = client.post(
        "/api/v1/agencias",
        headers=headers,
        json={"destination_id": destination_id, "address": "Av. Agencia 123", "phone": "987654321"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_and_assign_agency_admin(
    client: TestClient,
    headers: dict[str, str],
    agency_id: int,
    username: str,
) -> dict[str, str]:
    assigned = client.post(
        f"/api/v1/agencias/{agency_id}/agency-admin",
        headers=headers,
        json={"username": username, "password": "QaPassword123", "full_name": username},
    )
    assert assigned.status_code == 200, assigned.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "QaPassword123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_create_agency_requires_active_destination_and_starts_inactive(
    api_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    destinations = api_client.get("/api/v1/destinos").json()
    agency = _create_agency(api_client, admin_headers, destinations[0]["id"])

    assert agency["code"].startswith("AG-")
    assert agency["is_active"] is False
    assert agency["destination"]["id"] == destinations[0]["id"]
    assert agency["admin"] is None

    assert api_client.post(
        f"/api/v1/agencias/{agency['id']}/activate", headers=admin_headers
    ).status_code == 400

    duplicate = api_client.post(
        "/api/v1/agencias",
        headers=admin_headers,
        json={"destination_id": destinations[0]["id"]},
    )
    assert duplicate.status_code == 409

    linked_destination = api_client.put(
        f"/api/v1/destinos/{destinations[0]['id']}", json={"activo": False}
    )
    assert linked_destination.status_code == 409

    deactivated = api_client.put(
        f"/api/v1/destinos/{destinations[2]['id']}", json={"activo": False}
    )
    assert deactivated.status_code == 200
    inactive_destination = api_client.post(
        "/api/v1/agencias",
        headers=admin_headers,
        json={"destination_id": destinations[2]["id"]},
    )
    assert inactive_destination.status_code == 409


def test_agency_admin_is_limited_to_its_agency_and_operational_roles(
    api_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    destinations = api_client.get("/api/v1/destinos").json()
    first = _create_agency(api_client, admin_headers, destinations[0]["id"])
    second = _create_agency(api_client, admin_headers, destinations[1]["id"])
    agency_admin_headers = _create_and_assign_agency_admin(
        api_client, admin_headers, first["id"], "agency_admin_one"
    )

    own = api_client.get(f"/api/v1/agencias/{first['id']}", headers=agency_admin_headers)
    other = api_client.get(f"/api/v1/agencias/{second['id']}", headers=agency_admin_headers)
    assert own.status_code == 200
    assert other.status_code == 404

    staff = api_client.post(
        f"/api/v1/agencias/{first['id']}/users",
        headers=agency_admin_headers,
        json={
            "username": "secretaria_one",
            "password": "QaPassword123",
            "full_name": "Secretaria Uno",
            "role": "SECRETARIA",
        },
    )
    assert staff.status_code == 201, staff.text
    assert staff.json()["agency_id"] == first["id"]
    assert staff.json()["roles"] == ["SECRETARIA"]

    escalation = api_client.post(
        f"/api/v1/agencias/{first['id']}/users",
        headers=agency_admin_headers,
        json={
            "username": "bad_admin",
            "password": "QaPassword123",
            "full_name": "Bad Admin",
            "role": "ADMIN_GENERAL",
        },
    )
    assert escalation.status_code == 422
    assert api_client.post("/api/v1/agencias", headers=agency_admin_headers, json={"destination_id": destinations[2]["id"]}).status_code == 403
    assert api_client.get("/api/v1/users", headers=agency_admin_headers).status_code == 403
    assert api_client.get("/api/v1/roles", headers=agency_admin_headers).status_code == 403

    agency_admin_role = next(
        role for role in api_client.get("/api/v1/roles", headers=admin_headers).json()
        if role["name"] == "AGENCY_ADMIN"
    )
    assert api_client.post(
        f"/api/v1/users/{staff.json()['id']}/roles/{agency_admin_role['id']}",
        headers=admin_headers,
    ).status_code == 400
    agency_admin = next(
        user for user in api_client.get(f"/api/v1/agencias/{first['id']}/users", headers=admin_headers).json()
        if "AGENCY_ADMIN" in user["roles"]
    )
    assert api_client.delete(
        f"/api/v1/users/{agency_admin['id']}/roles/{agency_admin_role['id']}",
        headers=admin_headers,
    ).status_code == 400


def test_business_roles_cannot_be_assigned_without_an_agency(
    api_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    user = api_client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"username": "unassigned_staff", "password": "QaPassword123", "full_name": "Unassigned Staff"},
    )
    assert user.status_code == 400


def test_agency_admin_can_be_created_and_assigned_atomically(
    api_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    destination = api_client.get("/api/v1/destinos").json()[0]
    agency = _create_agency(api_client, admin_headers, destination["id"])

    assigned = api_client.post(
        f"/api/v1/agencias/{agency['id']}/agency-admin",
        headers=admin_headers,
        json={"username": "atomic_admin", "password": "QaPassword123", "full_name": "Atomic Admin"},
    )

    assert assigned.status_code == 200, assigned.text
    admin = assigned.json()["admin"]
    assert admin["username"] == "atomic_admin"
    assert admin["agency_id"] == agency["id"]
    assert admin["roles"] == ["AGENCY_ADMIN"]
    login = api_client.post("/api/v1/auth/login", json={"username": "atomic_admin", "password": "QaPassword123"})
    assert login.status_code == 200


def test_agency_users_and_dashboard_are_server_scoped(
    api_client: TestClient,
    admin_headers: dict[str, str],
    valid_shipment_payload: dict,
) -> None:
    destinations = api_client.get("/api/v1/destinos").json()
    first = _create_agency(api_client, admin_headers, destinations[0]["id"])
    second = _create_agency(api_client, admin_headers, destinations[1]["id"])
    first_headers = _create_and_assign_agency_admin(api_client, admin_headers, first["id"], "agency_admin_a")
    second_headers = _create_and_assign_agency_admin(api_client, admin_headers, second["id"], "agency_admin_b")
    for agency in (first, second):
        response = api_client.post(f"/api/v1/agencias/{agency['id']}/activate", headers=admin_headers)
        assert response.status_code == 200, response.text

    for agency, headers, username in (
        (first, first_headers, "staff_a"),
        (second, second_headers, "staff_b"),
    ):
        response = api_client.post(
            f"/api/v1/agencias/{agency['id']}/users",
            headers=headers,
            json={"username": username, "password": "QaPassword123", "full_name": username, "role": "ESTIBA"},
        )
        assert response.status_code == 201, response.text

    wrong_origin = api_client.post(
        f"/api/v1/agencias/{first['id']}/encomiendas",
        headers=first_headers,
        json={**valid_shipment_payload, "origen": second["destination"]["name"]},
    )
    assert wrong_origin.status_code == 400

    first_origin = first["destination"]["name"]
    first_destination = "Trujillo" if first_origin != "Trujillo" else "Angasmarca"
    first_shipment_payload = {
        **valid_shipment_payload,
        "origen": first_origin,
        "destino": first_destination,
    }
    first_shipment = api_client.post(
        f"/api/v1/agencias/{first['id']}/encomiendas",
        headers=first_headers,
        json=first_shipment_payload,
    )
    assert first_shipment.status_code == 201, first_shipment.text
    assert first_shipment.json()["agency_id"] == first["id"]
    second_payload = {
        **valid_shipment_payload,
        "remitente_numero_documento": "70123457",
        "origen": second["destination"]["name"],
        "destino": "Trujillo" if second["destination"]["name"] != "Trujillo" else "Angasmarca",
    }
    second_shipment = api_client.post(
        f"/api/v1/agencias/{second['id']}/encomiendas",
        headers=second_headers,
        json=second_payload,
    )
    assert second_shipment.status_code == 201, second_shipment.text
    assert second_shipment.json()["agency_id"] == second["id"]

    own_users = api_client.get(f"/api/v1/agencias/{first['id']}/users", headers=first_headers)
    assert own_users.status_code == 200
    assert {user["username"] for user in own_users.json()} == {"agency_admin_a", "staff_a"}
    assert api_client.get(f"/api/v1/agencias/{second['id']}/users", headers=first_headers).status_code == 404

    dashboard = api_client.get(f"/api/v1/agencias/{first['id']}/dashboard", headers=first_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["total_shipments"] == 1
    assert [shipment["id"] for shipment in dashboard.json()["recent_shipments"]] == [first_shipment.json()["id"]]
    assert api_client.get(f"/api/v1/agencias/{second['id']}/dashboard", headers=first_headers).status_code == 404
    assert api_client.get("/api/v1/encomiendas", headers=first_headers).json()[0]["id"] == first_shipment.json()["id"]
    assert api_client.get(f"/api/v1/encomiendas/{second_shipment.json()['id']}", headers=first_headers).status_code == 404
    own_list = api_client.get(f"/api/v1/agencias/{first['id']}/encomiendas", headers=first_headers)
    assert own_list.status_code == 200
    assert [item["id"] for item in own_list.json()] == [first_shipment.json()["id"]]
    assert api_client.get(
        f"/api/v1/agencias/{first['id']}/encomiendas/{second_shipment.json()['id']}",
        headers=admin_headers,
    ).status_code == 404
    assert api_client.get(f"/api/v1/agencias/{second['id']}/clientes", headers=first_headers).status_code == 404
    report = api_client.get(f"/api/v1/agencias/{first['id']}/reportes/operativo.pdf", headers=first_headers)
    assert report.status_code == 200
    assert report.content.startswith(b"%PDF")
    estiba_login = api_client.post(
        "/api/v1/auth/login", json={"username": "staff_a", "password": "QaPassword123"}
    )
    assert estiba_login.status_code == 200
    estiba_auth = {"Authorization": f"Bearer {estiba_login.json()['access_token']}"}
    own_packages = api_client.get("/api/v1/optimization/poc/packages", headers=estiba_auth)
    assert own_packages.status_code == 200
    assert {item["codigo"] for item in own_packages.json()} == {first_shipment.json()["codigo_encomienda"]}
    other_code = second_shipment.json()["codigo_encomienda"]
    excluded = api_client.post(
        "/api/v1/optimization/poc/first-fit/run", headers=estiba_auth,
        json={"truck_id": "CAMION_A", "package_codes": [other_code]},
    )
    assert excluded.status_code == 200
    assert excluded.json()["input_count"] == 0


def test_origin_agency_assignment_and_backfill_make_shipments_visible(
    api_client: TestClient,
    admin_headers: dict[str, str],
    db_session,
    valid_shipment_payload: dict,
) -> None:
    from app.modules.agencies.service import backfill_shipment_agencies_by_origin
    from app.modules.destinations.model import Destination
    from app.modules.shipments.repository import create_shipment as create_shipment_in_repository
    from app.modules.shipments.schema import ShipmentCreate

    trujillo = db_session.query(Destination).filter(Destination.name == "Trujillo").one()
    agency = _create_agency(api_client, admin_headers, trujillo.id)
    legacy = create_shipment_in_repository(
        db_session,
        ShipmentCreate.model_validate({**valid_shipment_payload, "origen": "Trujillo"}),
    )
    assert legacy.agency_id is None

    public_payload = {
        **valid_shipment_payload,
        "origen": "Trujillo",
        "remitente_numero_documento": "70121112",
    }
    public_shipment = api_client.post("/api/v1/encomiendas/registro-publico", json=public_payload)
    assert public_shipment.status_code == 201, public_shipment.text
    assert public_shipment.json()["agency_id"] == agency["id"]

    pre_registration = api_client.post(
        "/api/v1/encomiendas/pre-registro",
        json={
            **valid_shipment_payload,
            "origen": "Trujillo",
            "remitente_numero_documento": "70121113",
        },
    )
    assert pre_registration.status_code == 201, pre_registration.text
    pre_registered_shipment = db_session.get(Shipment, pre_registration.json()["id"])
    assert pre_registered_shipment.agency_id == agency["id"]

    updated_rows = backfill_shipment_agencies_by_origin(db_session)
    db_session.refresh(legacy)
    assert updated_rows == 1
    assert legacy.agency_id == agency["id"]

    listed = api_client.get(
        f"/api/v1/agencias/{agency['id']}/encomiendas", headers=admin_headers
    )
    assert listed.status_code == 200, listed.text
    expected_ids = {legacy.id, public_shipment.json()["id"], pre_registered_shipment.id}
    assert {row["id"] for row in listed.json()} == expected_ids
    dashboard = api_client.get(
        f"/api/v1/agencias/{agency['id']}/dashboard", headers=admin_headers
    )
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["total_shipments"] == 3


def test_public_pre_registration_requires_and_records_privacy_notice(
    api_client: TestClient,
    db_session,
    valid_shipment_payload: dict,
) -> None:
    without_notice = {
        key: value
        for key, value in valid_shipment_payload.items()
        if key not in {"aviso_privacidad_aceptado", "version_aviso_privacidad"}
    }
    rejected = api_client.post("/api/v1/encomiendas/pre-registro", json=without_notice)
    assert rejected.status_code == 422

    created = api_client.post("/api/v1/encomiendas/pre-registro", json=valid_shipment_payload)
    assert created.status_code == 201, created.text
    shipment = db_session.get(Shipment, created.json()["id"])
    assert shipment.privacy_notice_version == "2026-10-11"
    assert shipment.privacy_accepted_at is not None
    assert shipment.privacy_channel == "PUBLIC_WEB"


def test_public_formal_registration_requires_notice(api_client, valid_shipment_payload):
    payload = {key: value for key, value in valid_shipment_payload.items()
               if key not in {"aviso_privacidad_aceptado", "version_aviso_privacidad"}}
    assert api_client.post("/api/v1/encomiendas/registro-publico", json=payload).status_code == 422
    response = api_client.post("/api/v1/encomiendas/registro-publico", json=valid_shipment_payload)
    assert response.status_code == 201, response.text
    assert response.json()["canal_aviso_privacidad"] == "PUBLIC_WEB"
    public_status = api_client.get(
        f"/api/v1/encomiendas/codigo/{response.json()['codigo_encomienda']}"
    )
    assert public_status.status_code == 200
    assert "remitente_numero_documento" not in public_status.json()
    assert "destinatario_nombre" not in public_status.json()
