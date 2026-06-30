"""Migración manual de normalización (idempotente y no destructiva).

Contexto: el proyecto NO usa Alembic (el esquema se crea con create_all +
sync_development_schema). Este script aplica SOLO mejoras seguras de
normalización de DATOS, sin renombrar ni eliminar tablas/columnas:

  1. Backfill de `clientes` a partir de los snapshots de remitente/destinatario
     guardados en `encomiendas` (así la tabla maestra de clientes queda completa,
     resolviendo la duplicación que hoy vive embebida en cada encomienda).
  2. Reporte (solo lectura) de referencias huérfanas en los logs del asistente
     (encomienda_id / cliente_id que apuntan a registros inexistentes).

NO agrega constraints FK automáticamente: en una BD viva con datos previos eso
puede fallar por huérfanos y, además, los snapshots de encomiendas son una
denormalización intencional (preservan quién envió/recibió aunque el cliente
cambie luego). Las FK recomendadas se listan al final como sugerencia manual.

USO (haz un RESPALDO de la base antes de ejecutar):
    python -m scripts.migracion_normalizacion            # aplica backfill + reporte
    python -m scripts.migracion_normalizacion --dry-run  # solo reporta, no escribe
"""
from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.modules.clients.service import upsert_client_from_person_data
from app.modules.clients.model import Client
from app.modules.shipments.model import Shipment
from app.modules.asistente.model import LogInteraccionAsistente


def _es_dni(tipo: str | None, numero: str | None) -> bool:
    return bool(tipo and tipo.strip().upper() == "DNI" and numero and numero.strip().isdigit() and len(numero.strip()) == 8)


def backfill_clientes(db, *, dry_run: bool) -> int:
    """Crea/actualiza clientes desde los datos de remitente y destinatario de cada encomienda."""
    creados = 0
    existentes = {row[0] for row in db.query(Client.dni).all()}
    for env in db.query(Shipment).all():
        personas = (
            (env.sender_document_type, env.sender_document_number, env.sender_name,
             env.sender_phone, env.sender_email, env.sender_address),
            (env.recipient_document_type, env.recipient_document_number, env.recipient_name,
             env.recipient_phone, env.recipient_email, env.recipient_address),
        )
        for tipo, numero, nombre, telefono, correo, direccion in personas:
            if not _es_dni(tipo, numero) or not nombre:
                continue
            dni = numero.strip()
            if dni in existentes:
                continue
            if not dry_run:
                upsert_client_from_person_data(
                    db, dni=dni, nombre_completo=nombre, telefono=telefono,
                    correo=correo, direccion=direccion, commit=False,
                )
            existentes.add(dni)
            creados += 1
    if not dry_run:
        db.commit()
    return creados


def reportar_huerfanos(db) -> dict:
    """Cuenta referencias en logs del asistente que no existen como encomienda."""
    ids_encomiendas = {row[0] for row in db.query(Shipment.id).all()}
    huerfanos = 0
    for log in db.query(LogInteraccionAsistente).filter(LogInteraccionAsistente.encomienda_id.isnot(None)).all():
        if log.encomienda_id not in ids_encomiendas:
            huerfanos += 1
    return {"logs_asistente_con_encomienda_inexistente": huerfanos}


# Constraints FK recomendadas (aplicar manualmente solo tras verificar que no hay
# huérfanos; en SQLite no se pueden añadir por ALTER, requieren recrear la tabla):
FK_SUGERIDAS = [
    "ALTER TABLE logs_interaccion_asistente ADD CONSTRAINT fk_log_asist_encomienda "
    "FOREIGN KEY (encomienda_id) REFERENCES encomiendas(id);",
    "ALTER TABLE solicitudes_recojo_externo ADD CONSTRAINT fk_recojo_encomienda "
    "FOREIGN KEY (encomienda_id) REFERENCES encomiendas(id);",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Migración de normalización (idempotente).")
    parser.add_argument("--dry-run", action="store_true", help="Solo reporta, no escribe.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        creados = backfill_clientes(db, dry_run=args.dry_run)
        reporte = reportar_huerfanos(db)
        print(f"Clientes {'que se crearían' if args.dry_run else 'creados'} desde encomiendas: {creados}")
        print(f"Reporte de huérfanos: {reporte}")
        print("\nFK recomendadas (aplicar manualmente con respaldo, solo si no hay huérfanos):")
        for sql in FK_SUGERIDAS:
            print("  " + sql)
    finally:
        db.close()


if __name__ == "__main__":
    main()
