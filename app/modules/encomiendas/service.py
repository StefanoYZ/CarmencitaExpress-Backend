from datetime import datetime

from app.modules.encomiendas.schema import EncomiendaCreate, EncomiendaResponse

ESTADO_INICIAL = "REGISTRADA"

# TODO: reemplazar este almacenamiento en memoria por repository + PostgreSQL.
_encomiendas_store: dict[int, EncomiendaResponse] = {}
_codigo_index: dict[str, int] = {}
_next_encomienda_id = 1
_codigo_encomienda_counter = 0


def generate_codigo_encomienda() -> str:
    global _codigo_encomienda_counter

    letras_dias = {
        0: "L",
        1: "M",
        2: "X",
        3: "J",
        4: "V",
        5: "S",
        6: "D",
    }

    letra_dia = letras_dias[datetime.now().weekday()]
    _codigo_encomienda_counter += 1
    correlativo = str(_codigo_encomienda_counter).zfill(9)

    return f"{letra_dia}{correlativo}"


def create_encomienda(payload: EncomiendaCreate) -> EncomiendaResponse:
    global _next_encomienda_id

    encomienda = EncomiendaResponse(
        id=_next_encomienda_id,
        codigo_encomienda=generate_codigo_encomienda(),
        estado=ESTADO_INICIAL,
        **payload.model_dump(),
    )

    _encomiendas_store[encomienda.id] = encomienda
    _codigo_index[encomienda.codigo_encomienda] = encomienda.id
    _next_encomienda_id += 1

    return encomienda


def list_encomiendas() -> list[EncomiendaResponse]:
    return list(_encomiendas_store.values())


def get_encomienda(encomienda_id: int) -> EncomiendaResponse | None:
    return _encomiendas_store.get(encomienda_id)


def get_encomienda_by_codigo(codigo_encomienda: str) -> EncomiendaResponse | None:
    encomienda_id = _codigo_index.get(codigo_encomienda)
    if encomienda_id is None:
        return None
    return get_encomienda(encomienda_id)