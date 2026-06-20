import pytest


def test_login_rejects_invalid_password(api_client):
    response = api_client.post(
        "/api/v1/auth/login",
        json={"username": "qa_admin", "password": "incorrecta"},
    )
    assert response.status_code == 401


def test_users_endpoint_requires_authentication(api_client):
    response = api_client.get("/api/v1/users")
    assert response.status_code == 401


def test_estiba_cannot_access_users(api_client, estiba_headers):
    response = api_client.get("/api/v1/users", headers=estiba_headers)
    assert response.status_code == 403


def test_admin_creates_and_toggles_user_without_email(api_client, admin_headers):
    created = api_client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "qa_toggle",
            "password": "QaPassword123",
            "full_name": "TEST QA TOGGLE",
        },
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert "email" not in data
    assert data["is_active"] is True

    disabled = api_client.put(
        f"/api/v1/users/{data['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["is_active"] is False

    enabled = api_client.put(
        f"/api/v1/users/{data['id']}",
        headers=admin_headers,
        json={"is_active": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["is_active"] is True

    delete_attempt = api_client.delete(
        f"/api/v1/users/{data['id']}",
        headers=admin_headers,
    )
    assert delete_attempt.status_code == 405


def test_admin_cannot_run_optimization(api_client, admin_headers):
    response = api_client.post(
        "/api/v1/optimization/poc/first-fit/run",
        headers=admin_headers,
        json={"truck_id": "CAMION_A", "package_limit": 5, "allow_rotation": True},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/optimization/poc/first-fit/run",
        "/api/v1/optimization/poc/best-fit/run",
        "/api/v1/optimization/poc/worst-fit/run",
        "/api/v1/optimization/poc/minimax-maximin/run",
        "/api/v1/optimization/poc/backtracking/run",
    ],
)
def test_inactive_optimization_algorithms_are_disabled(
    api_client,
    estiba_headers,
    path,
):
    response = api_client.post(
        path,
        headers=estiba_headers,
        json={"truck_id": "CAMION_A", "package_limit": 12, "allow_rotation": True},
    )
    assert response.status_code == 410, response.text


def test_best_fit_decreasing_uses_registered_shipments_and_skips_envelopes(
    api_client,
    estiba_headers,
    valid_shipment_payload,
):
    for index, destination in enumerate(("Shorey", "Angasmarca", "Orocullay"), start=1):
        payload = {
            **valid_shipment_payload,
            "descripcion": f"Paquete optimizable {index}",
            "destino": destination,
            "tipo_contenido": "ROPA",
            "largo_cm": 30 + index,
            "ancho_cm": 20 + index,
            "alto_cm": 15 + index,
        }
        created = api_client.post("/api/v1/encomiendas", json=payload)
        assert created.status_code == 201, created.text

    envelope_payload = {
        **valid_shipment_payload,
        "descripcion": "Sobre sin estiba",
        "destino": "Cachicadan",
        "tipo_contenido": "DOCUMENTOS",
        "largo_cm": 0,
        "ancho_cm": 0,
        "alto_cm": 0,
    }
    envelope = api_client.post("/api/v1/encomiendas", json=envelope_payload)
    assert envelope.status_code == 201, envelope.text
    envelope_code = envelope.json()["codigo_encomienda"]

    scenario = api_client.get(
        "/api/v1/optimization/poc/scenario?limit=4",
        headers=estiba_headers,
    )
    assert scenario.status_code == 200, scenario.text
    packages = scenario.json()["packages"]
    assert len(packages) == 4
    assert next(item for item in packages if item["codigo"] == envelope_code)["requires_packing"] is False

    response = api_client.post(
        "/api/v1/optimization/poc/best-fit-decreasing/run",
        headers=estiba_headers,
        json={"truck_id": "CAMION_A", "package_limit": 4, "allow_rotation": True},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    metrics = data["metrics"]
    assert metrics["overlap_violations"] == 0
    assert metrics["boundary_violations"] == 0
    assert metrics["placed_count"] == 3
    assert metrics["unplaced_count"] == 0
    assert len(data["ordered_packages"]) == 4
    assert envelope_code not in {placement["codigo"] for placement in data["placements"]}
