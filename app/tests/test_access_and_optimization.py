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


def test_admin_cannot_run_optimization(api_client, admin_headers):
    response = api_client.post(
        "/api/v1/optimization/poc/first-fit/run",
        headers=admin_headers,
        json={"truck_id": "CAMION_A", "package_limit": 5, "allow_rotation": True},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("path", "strategy"),
    [
        ("/api/v1/optimization/poc/first-fit/run", None),
        ("/api/v1/optimization/poc/best-fit/run", None),
        ("/api/v1/optimization/poc/worst-fit/run", None),
        ("/api/v1/optimization/poc/best-fit-decreasing/run", None),
        ("/api/v1/optimization/poc/minimax-maximin/run", "MINIMAX"),
        ("/api/v1/optimization/poc/minimax-maximin/run", "MAXIMIN"),
    ],
)
def test_optimization_algorithms_respect_geometry(
    api_client,
    estiba_headers,
    path,
    strategy,
):
    payload = {
        "truck_id": "CAMION_A",
        "package_limit": 12,
        "allow_rotation": True,
    }
    if strategy:
        payload["strategy"] = strategy

    response = api_client.post(path, headers=estiba_headers, json=payload)
    assert response.status_code == 200, response.text
    metrics = response.json()["metrics"]
    assert metrics["overlap_violations"] == 0
    assert metrics["boundary_violations"] == 0
    assert metrics["placed_count"] + metrics["unplaced_count"] == 12
