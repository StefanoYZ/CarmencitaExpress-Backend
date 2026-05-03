from app.modules.clientes.schema import ClienteCreate, ClienteResponse


# TODO: reemplazar este almacenamiento en memoria por repository + PostgreSQL.
_clientes_store: dict[int, ClienteResponse] = {}
_next_cliente_id = 1


def create_cliente(payload: ClienteCreate) -> ClienteResponse:
    global _next_cliente_id

    cliente = ClienteResponse(id=_next_cliente_id, **payload.model_dump())
    _clientes_store[cliente.id] = cliente
    _next_cliente_id += 1
    return cliente


def list_clientes() -> list[ClienteResponse]:
    return list(_clientes_store.values())


def get_cliente(cliente_id: int) -> ClienteResponse | None:
    return _clientes_store.get(cliente_id)
