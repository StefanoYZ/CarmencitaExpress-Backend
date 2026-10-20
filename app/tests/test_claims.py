from fastapi.testclient import TestClient

def _create_public_shipment(client: TestClient, payload: dict) -> dict:
    response = client.post("/api/v1/encomiendas/registro-publico", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_public_claim_validates_shipment_party_and_returns_safe_status(
    api_client: TestClient,
    db_session,
    valid_shipment_payload: dict,
) -> None:
    from app.modules.claims.model import Claim, ClaimEvent

    shipment = _create_public_shipment(api_client, valid_shipment_payload)
    sender_lookup = api_client.get(
        f"/api/v1/reclamos/publicos/encomiendas/{shipment['codigo_encomienda']}/remitente"
    )
    assert sender_lookup.status_code == 200, sender_lookup.text
    assert sender_lookup.json() == {
        "shipment_code": shipment["codigo_encomienda"],
        "sender_document_type": "DNI",
        "sender_document_number": valid_shipment_payload["remitente_numero_documento"],
    }
    agencies = api_client.get("/api/v1/reclamos/agencias").json()
    assert agencies
    assert all("admin" not in agency and "agency_admin" not in agency for agency in agencies)

    payload = {
        "shipment_code": shipment["codigo_encomienda"],
        "document_number": valid_shipment_payload["remitente_numero_documento"],
        "agency_id": agencies[0]["id"],
        "category": "DANO",
        "description": "El paquete llegó con la caja dañada.",
        "requested_solution": "Solicito que revisen el caso.",
        "privacy_notice_accepted": True,
        "privacy_notice_version": "2026-10-11",
    }
    created = api_client.post("/api/v1/reclamos/publicos", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "RECIBIDO"
    claim = db_session.query(Claim).filter_by(case_code=created.json()["case_code"]).one()
    db_session.add(ClaimEvent(
        claim_id=claim.id,
        event_type="NOTA",
        note="Nota interna no visible al cliente.",
        visible_to_customer=False,
    ))
    db_session.commit()

    invalid_party = api_client.post("/api/v1/reclamos/publicos", json={**payload, "document_number": "11111111"})
    assert invalid_party.status_code == 404

    second_claim = api_client.post("/api/v1/reclamos/publicos", json=payload)
    assert second_claim.status_code == 201, second_claim.text

    status_response = api_client.post("/api/v1/reclamos/consulta", json={
        "case_code": created.json()["case_code"],
        "shipment_code": shipment["codigo_encomienda"],
        "document_number": payload["document_number"],
    })
    assert status_response.status_code == 200, status_response.text
    public_status = status_response.json()[0]
    assert public_status == {
        "case_code": created.json()["case_code"],
        "category": "DANO",
        "description": "El paquete llegó con la caja dañada.",
        "requested_solution": "Solicito que revisen el caso.",
        "status": "RECIBIDO",
        "created_at": public_status["created_at"],
        "resolution_text": None,
        "events": [{
            "id": public_status["events"][0]["id"],
            "event_type": "RECIBIDO",
            "from_status": None,
            "to_status": None,
            "note": "Hemos recibido tu solicitud.",
            "created_at": public_status["events"][0]["created_at"],
        }],
    }
    assert "Nota interna no visible al cliente." not in str(public_status)
    assert "claimant_document_number" not in public_status
    assert "actor_name" not in public_status["events"][0]

    for lookup in (
        {"case_code": created.json()["case_code"]},
        {"shipment_code": shipment["codigo_encomienda"]},
        {"document_number": payload["document_number"]},
    ):
        response = api_client.post("/api/v1/reclamos/consulta", json=lookup)
        assert response.status_code == 200, response.text
    by_shipment = api_client.post("/api/v1/reclamos/consulta", json={
        "shipment_code": shipment["codigo_encomienda"],
    })
    assert {item["case_code"] for item in by_shipment.json()} == {
        created.json()["case_code"], second_claim.json()["case_code"],
    }
    assert api_client.post("/api/v1/reclamos/consulta", json={}).status_code == 422
    assert api_client.post("/api/v1/reclamos/consulta", json={
        "case_code": created.json()["case_code"],
        "document_number": "11111111",
    }).status_code == 404


def test_monetary_claim_requires_image_and_admin_verification(
    api_client: TestClient,
    admin_headers: dict[str, str],
    valid_shipment_payload: dict,
) -> None:
    shipment = _create_public_shipment(api_client, valid_shipment_payload)
    agency = api_client.get("/api/v1/reclamos/agencias").json()[0]
    agency_admin_user = api_client.post(
        f"/api/v1/agencias/{agency['id']}/agency-admin",
        headers=admin_headers,
        json={"username": "claim_verifier", "password": "QaPassword123", "full_name": "Claim Verifier"},
    )
    assert agency_admin_user.status_code == 200, agency_admin_user.text
    login = api_client.post("/api/v1/auth/login", json={"username": "claim_verifier", "password": "QaPassword123"})
    assert login.status_code == 200, login.text
    agency_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = api_client.post("/api/v1/reclamos/publicos", json={
        "shipment_code": shipment["codigo_encomienda"],
        "document_number": valid_shipment_payload["remitente_numero_documento"],
        "agency_id": agency["id"],
        "category": "DANO",
        "description": "El artículo llegó dañado y no funciona.",
        "privacy_notice_accepted": True,
        "privacy_notice_version": "2026-10-11",
    })
    assert created.status_code == 201, created.text

    assert api_client.get("/api/v1/reclamos", headers=admin_headers).status_code == 400
    claims = api_client.get("/api/v1/reclamos", headers=agency_headers).json()
    claim = next(item for item in claims if item["case_code"] == created.json()["case_code"])
    scoped_admin_detail = api_client.get(
        f"/api/v1/reclamos/{claim['id']}", headers=admin_headers, params={"agency_id": agency["id"]}
    )
    assert scoped_admin_detail.status_code == 200
    assert api_client.get(f"/api/v1/reclamos/{claim['id']}", headers=admin_headers).status_code == 404
    for target in ("EN_REVISION", "INVESTIGANDO"):
        event = api_client.post(f"/api/v1/reclamos/{claim['id']}/eventos", headers=agency_headers, params={"agency_id": agency["id"]}, json={
            "note": "Se revisa la trazabilidad de la encomienda.", "to_status": target,
        })
        assert event.status_code == 200, event.text
        assert event.json()["actor_name"] == "Claim Verifier"

    no_proof = api_client.post(f"/api/v1/reclamos/{claim['id']}/resolucion", headers=admin_headers, params={"agency_id": agency["id"]}, json={
        "resolution_type": "MONETARIA", "resolution_text": "Se realizará la devolución.",
        "amount": 25, "currency": "PEN", "payment_method": "YAPE",
    })
    assert no_proof.status_code == 422

    png = b"\x89PNG\r\n\x1a\n" + b"claim-proof"
    attachment = api_client.post(
        f"/api/v1/reclamos/{claim['id']}/adjuntos",
        headers={**agency_headers, "Content-Type": "image/png", "X-Tipo-Adjunto": "COMPROBANTE_PAGO", "X-Nombre-Archivo": "pago.png"},
        params={"agency_id": agency["id"]},
        content=png,
    )
    assert attachment.status_code == 201, attachment.text
    resolution = api_client.post(f"/api/v1/reclamos/{claim['id']}/resolucion", headers=agency_headers, params={"agency_id": agency["id"]}, json={
        "resolution_type": "MONETARIA", "resolution_text": "Se realizó el abono al cliente.",
        "amount": 25, "currency": "PEN", "payment_method": "YAPE",
        "payment_proof_attachment_id": attachment.json()["id"],
    })
    assert resolution.status_code == 200, resolution.text
    assert resolution.json()["status"] == "PAGO_POR_VERIFICAR"
    assert resolution.json()["resolution_recorded_by_name"] == "Claim Verifier"
    pending_public_status = api_client.post("/api/v1/reclamos/consulta", json={"case_code": created.json()["case_code"]})
    assert pending_public_status.status_code == 200, pending_public_status.text
    assert pending_public_status.json()[0]["resolution_text"] is None

    verified = api_client.post(f"/api/v1/reclamos/{claim['id']}/verificar-pago", headers=agency_headers, params={"agency_id": agency["id"]},
                               json={"verified": True, "note": "Comprobante revisado."})
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "RESUELTO"
    assert verified.json()["payment_verified_at"] is not None
    assert verified.json()["payment_verified_by_name"] == "Claim Verifier"
    assert verified.json()["resolved_by_name"] == "Claim Verifier"
    resolved_public_status = api_client.post("/api/v1/reclamos/consulta", json={"case_code": created.json()["case_code"]})
    assert resolved_public_status.status_code == 200, resolved_public_status.text
    assert resolved_public_status.json()[0]["resolution_text"] == "Se realizó el abono al cliente."
    assert any(event["note"] == "El pago de la solución fue verificado y el reclamo está resuelto."
               for event in resolved_public_status.json()[0]["events"])


def test_secretaria_can_open_an_in_person_case_in_her_agency(
    api_client: TestClient,
    db_session,
    secretaria_headers: dict[str, str],
    valid_shipment_payload: dict,
) -> None:
    from app.modules.agencies.model import Agency
    from app.modules.users.repository import get_user_by_username

    secretary = get_user_by_username(db_session, "qa_secretaria")
    agency = db_session.get(Agency, secretary.agency_id)
    shipment_payload = {
        **valid_shipment_payload,
        "remitente_numero_documento": "70121111",
        "origen": agency.destination.name,
    }
    wrong_origin = api_client.post(
        "/api/v1/encomiendas",
        headers=secretaria_headers,
        json={**shipment_payload, "origen": "Trujillo"},
    )
    assert wrong_origin.status_code == 400
    shipment = api_client.post("/api/v1/encomiendas", headers=secretaria_headers, json=shipment_payload)
    assert shipment.status_code == 201, shipment.text
    secretary_shipments = api_client.get("/api/v1/encomiendas", headers=secretaria_headers)
    assert secretary_shipments.status_code == 200, secretary_shipments.text
    assert any(item["id"] == shipment.json()["id"] for item in secretary_shipments.json())
    sender_lookup_path = (
        f"/api/v1/reclamos/agencia/{secretary.agency_id}/encomiendas/"
        f"{shipment.json()['codigo_encomienda']}/remitente"
    )
    assert api_client.get(sender_lookup_path).status_code == 401
    sender_lookup = api_client.get(sender_lookup_path, headers=secretaria_headers)
    assert sender_lookup.status_code == 200, sender_lookup.text
    assert sender_lookup.json() == {
        "shipment_code": shipment.json()["codigo_encomienda"],
        "sender_document_type": "DNI",
        "sender_document_number": "70121111",
    }
    wrong_agency_lookup = api_client.get(
        f"/api/v1/reclamos/agencia/{secretary.agency_id + 1000}/encomiendas/"
        f"{shipment.json()['codigo_encomienda']}/remitente",
        headers=secretaria_headers,
    )
    assert wrong_agency_lookup.status_code == 404
    response = api_client.post("/api/v1/reclamos/presencial", headers=secretaria_headers, json={
        "shipment_code": shipment.json()["codigo_encomienda"],
        "claimant_document_number": "70121111",
        "category": "FALTANTE",
        "description": "El cliente reporta que falta un artículo en el paquete.",
        "privacy_notice_acknowledged": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "PRESENCIAL"
    assert response.json()["agency_id"] == secretary.agency_id
    forbidden_resolution = api_client.post(
        f"/api/v1/reclamos/{response.json()['id']}/resolucion",
        headers=secretaria_headers,
        params={"agency_id": secretary.agency_id},
        json={"resolution_type": "NO_MONETARIA", "resolution_text": "Se resolvió el caso presencialmente."},
    )
    assert forbidden_resolution.status_code == 403

    trace = api_client.post(
        f"/api/v1/reclamos/agencia/{secretary.agency_id}/encomiendas/{shipment.json()['id']}/trazabilidad",
        headers=secretaria_headers,
        json={"event_type": "INCIDENCIA", "location": "Agencia de origen", "description": "Se inspeccionó el paquete."},
    )
    assert trace.status_code == 200, trace.text
    assert trace.json()["lugar"] == "Agencia de origen"
    assert trace.json()["actor_name"] == "TEST QA SECRETARIA"
