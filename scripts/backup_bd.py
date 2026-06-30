"""Respaldo completo de la base de datos a archivos JSON.

Vuelca todas las tablas (según Base.metadata) a JSON, una entrada por tabla,
con un timestamp en el nombre del archivo. Útil antes de correr migraciones.

USO:
    python -m scripts.backup_bd                 # respalda a backups/backup_<fecha>.json
    python -m scripts.backup_bd --dir mis_resp  # carpeta destino distinta
"""
from __future__ import annotations

import argparse
import datetime
import decimal
import json
from pathlib import Path

from sqlalchemy import select

# Importar app.main asegura que TODOS los modelos queden registrados en Base.metadata.
import app.main  # noqa: F401
from app.core.database import Base, SessionLocal


def _serializar(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


def respaldar(destino_dir: str = "backups") -> Path:
    carpeta = Path(destino_dir)
    carpeta.mkdir(parents=True, exist_ok=True)
    sello = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archivo = carpeta / f"backup_{sello}.json"

    db = SessionLocal()
    data: dict[str, list[dict]] = {}
    resumen: dict[str, int] = {}
    try:
        for tabla in Base.metadata.sorted_tables:
            filas = []
            for fila in db.execute(select(tabla)).mappings():
                filas.append({k: _serializar(v) for k, v in dict(fila).items()})
            data[tabla.name] = filas
            resumen[tabla.name] = len(filas)
    finally:
        db.close()

    archivo.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return archivo, resumen


def main() -> None:
    parser = argparse.ArgumentParser(description="Respaldo de la BD a JSON.")
    parser.add_argument("--dir", default="backups", help="Carpeta destino (def: backups/).")
    args = parser.parse_args()
    archivo, resumen = respaldar(args.dir)
    total = sum(resumen.values())
    print(f"Respaldo creado: {archivo}")
    print(f"Tablas: {len(resumen)} · Filas totales: {total}")
    for nombre, n in sorted(resumen.items()):
        if n:
            print(f"  {nombre}: {n}")


if __name__ == "__main__":
    main()
