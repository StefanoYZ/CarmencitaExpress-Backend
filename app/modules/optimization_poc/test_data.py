"""Generacion y control de PAQUETES DE PRUEBA para la optimizacion 3D.

El "modo prueba" de la optimizacion se considera ACTIVO cuando existen encomiendas
de prueba registradas hoy (marcadas con el prefijo TEST_PACKAGE_MARKER en la
descripcion). Cuando hay paquetes de prueba, el escenario de optimizacion los usa;
cuando no, usa las encomiendas reales registradas por la web (ver
`repository.list_registered_packages`).

Este modulo centraliza construir/sembrar/contar/borrar esos paquetes, de modo que
lo usen por igual el switch de la Vista Developer y el script
`scripts/seed_paquetes_prueba.py`.
"""
from __future__ import annotations

import secrets
from random import Random

from sqlalchemy.orm import Session

from app.core.business_time import business_now, business_today, ensure_business_tz
from app.modules.measurement_logs.model import (
    LogCargaPaquete,
    LogEmisionBoleta,
    LogServicioTransporte,
)
from app.modules.optimization_poc.utils.constants import LOGISTIC_ROUTE
from app.modules.shipments.constants import INTERNAL_REGISTRATION_ORIGIN, REGISTERED_STATUS
from app.modules.shipments.model import Shipment
from app.modules.shipments.repository import generate_shipment_code

# Tablas con FK a encomiendas que la optimizacion puede generar (logs de medicion).
# Deben borrarse antes que la encomienda de prueba para no violar la llave foranea.
_DEPENDENT_LOG_MODELS = (LogEmisionBoleta, LogServicioTransporte, LogCargaPaquete)

# Prefijo de descripcion que marca una encomienda como paquete de prueba.
TEST_PACKAGE_MARKER = "[PRUEBA]"
# Cuando no se indica una cantidad, se elige una AL AZAR en este rango, para que
# cada activacion pruebe un lote de tamano distinto (tope 70 por la optimizacion).
MIN_TEST_PACKAGE_COUNT = 20
MAX_TEST_PACKAGE_COUNT = 60
DEFAULT_TEST_PACKAGE_COUNT = 50

ORIGEN = "TRUJILLO"
_DESTINOS = [stop for stop in LOGISTIC_ROUTE if stop != ORIGEN]
_FRAGILIDADES = ["BAJA", "MEDIA", "ALTA"]
_NOMBRES = [
    "Juan Perez", "Maria Lopez", "Carlos Diaz", "Ana Torres", "Luis Ramos",
    "Rosa Vega", "Jose Castro", "Elena Rios", "Pedro Soto", "Lucia Mora",
]

# Formas variadas -> (nombre, tipo_contenido, generador de dims cm, rango densidad kg/m3).
# Todas caben en el CAMION_A (491x210x220) y ninguna es DOCUMENTOS (asi participan
# en el empaquetado). Distribucion: mayoria chicas/medianas, algunas grandes/incomodas.
_FORMAS = [
    ("caja chica",      "ROPA",              lambda r: (r.randint(20, 45), r.randint(20, 45), r.randint(20, 45)), (120, 220)),
    ("caja mediana",    "ALIMENTOS",         lambda r: (r.randint(45, 75), r.randint(40, 65), r.randint(40, 80)), (150, 260)),
    ("bulto grande",    "ELECTRODOMESTICOS", lambda r: (r.randint(70, 130), r.randint(60, 100), r.randint(80, 190)), (110, 190)),
    ("cubo",            "OTROS",             lambda r: _cubo_dims(r), (130, 200)),
    ("plano",           "ELECTRONICOS",      lambda r: (r.randint(160, 200), r.randint(50, 80), r.randint(10, 22)), (150, 240)),
    ("largo/tubo",      "OTROS",             lambda r: (r.randint(180, 200), r.randint(18, 30), r.randint(18, 30)), (150, 240)),
]
_PESOS_FORMA = [0.28, 0.24, 0.14, 0.12, 0.12, 0.10]


def _cubo_dims(r: Random) -> tuple[int, int, int]:
    base = r.randint(48, 54)
    return (base, base, r.randint(48, 54))


def build_test_shipments(n: int = DEFAULT_TEST_PACKAGE_COUNT, seed: int | None = None) -> list[Shipment]:
    """Construye (sin persistir) n encomiendas de prueba variadas, sin codigo asignado.

    `seed=None` usa una semilla aleatoria: cada llamada produce un lote distinto.
    """
    r = Random(seed)
    filas: list[Shipment] = []
    for i in range(1, n + 1):
        nombre, tipo, dims_fn, (den_lo, den_hi) = r.choices(_FORMAS, weights=_PESOS_FORMA, k=1)[0]
        largo, ancho, alto = dims_fn(r)
        vol_m3 = (largo * ancho * alto) / 1_000_000
        peso = round(max(1.0, min(vol_m3 * r.uniform(den_lo, den_hi), 180.0)), 1)
        destino = _DESTINOS[i % len(_DESTINOS)]
        filas.append(Shipment(
            shipment_code="",  # se asigna con generate_shipment_code al persistir
            sender_document_type="DNI",
            sender_document_number=f"{r.randint(10_000_000, 79_999_999)}",
            sender_name=r.choice(_NOMBRES),
            sender_phone=f"9{r.randint(10_000_000, 99_999_999)}",
            recipient_document_type="DNI",
            recipient_document_number=f"{r.randint(10_000_000, 79_999_999)}",
            recipient_name=r.choice(_NOMBRES),
            origin=ORIGEN,
            destination=destino,
            description=f"{TEST_PACKAGE_MARKER} {nombre} {i} ({tipo.lower()})",
            weight_kg=peso,
            length_cm=float(largo),
            width_cm=float(ancho),
            height_cm=float(alto),
            fragility=r.choice(_FRAGILIDADES),
            content_type=tipo,
            base_orientation="LARGO_ANCHO",
            registration_origin=INTERNAL_REGISTRATION_ORIGIN,
            status=REGISTERED_STATUS,
            created_at=business_now(),
            updated_at=business_now(),
        ))
    return filas


def _test_packages_query(db: Session):
    return db.query(Shipment).filter(Shipment.description.like(f"{TEST_PACKAGE_MARKER}%"))


def clear_test_packages(db: Session) -> int:
    """Borra todas las encomiendas de prueba (y sus logs dependientes).

    Devuelve cuantas encomiendas borro. Primero elimina los logs de medicion que
    la optimizacion pudo haber creado (FK a encomiendas), para no violar la llave.
    """
    ids = [row.id for row in _test_packages_query(db).with_entities(Shipment.id).all()]
    if ids:
        for log_model in _DEPENDENT_LOG_MODELS:
            db.query(log_model).filter(log_model.encomienda_id.in_(ids)).delete(synchronize_session=False)
    deleted = _test_packages_query(db).delete(synchronize_session=False)
    db.commit()
    return deleted


def count_test_packages_today(db: Session) -> int:
    """Cuenta las encomiendas de prueba registradas HOY (dia de negocio)."""
    hoy = business_today()
    return sum(
        1
        for shipment in _test_packages_query(db).all()
        if ensure_business_tz(shipment.created_at).date() == hoy
    )


def test_mode_active(db: Session) -> bool:
    """El modo prueba esta activo si existe al menos un paquete de prueba de hoy."""
    return count_test_packages_today(db) > 0


def seed_test_packages(
    db: Session,
    n: int | None = None,
    seed: int | None = None,
) -> int:
    """Reemplaza los paquetes de prueba: borra los previos e inserta n nuevos.

    - `n=None`: elige una cantidad AL AZAR entre MIN/MAX_TEST_PACKAGE_COUNT.
    - `seed=None`: usa una semilla aleatoria (paquetes distintos en cada activacion).

    Devuelve la cantidad creada. Cada fila recibe un codigo valido y un id
    incremental (necesario para el siguiente codigo).
    """
    if seed is None:
        seed = secrets.randbelow(1_000_000)
    if n is None:
        n = Random(seed).randint(MIN_TEST_PACKAGE_COUNT, MAX_TEST_PACKAGE_COUNT)
    n = max(1, min(n, 70))
    clear_test_packages(db)
    paquetes = build_test_shipments(n=n, seed=seed)
    for paquete in paquetes:
        paquete.shipment_code = generate_shipment_code(db)
        db.add(paquete)
        db.flush([paquete])
    db.commit()
    return len(paquetes)
