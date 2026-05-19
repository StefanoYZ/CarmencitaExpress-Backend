from app.modules.clients.schema import ClientCreate, ClientResponse


# TODO: reemplazar este almacenamiento en memoria por repository + PostgreSQL.
_clients_store: dict[int, ClientResponse] = {}
_next_client_id = 1


def create_client(payload: ClientCreate) -> ClientResponse:
    global _next_client_id

    client = ClientResponse(id=_next_client_id, **payload.model_dump(by_alias=True))
    _clients_store[client.id] = client
    _next_client_id += 1
    return client


def list_clients() -> list[ClientResponse]:
    return list(_clients_store.values())


def get_client(client_id: int) -> ClientResponse | None:
    return _clients_store.get(client_id)
