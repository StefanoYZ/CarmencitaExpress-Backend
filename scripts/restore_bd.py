"""Restaura datos desde un respaldo JSON (creado por backup_bd.py).

Es IDEMPOTENTE y NO destructivo: inserta únicamente las filas que falten
(según la clave primaria); nunca borra ni sobrescribe lo existente. Respeta el
orden de dependencias (FK) usando Base.metadata.sorted_tables.

USO:
    python -m scripts.restore_bd                      # usa el backup más reciente
    python -m scripts.restore_bd backups/backup_X.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

import app.main  # noqa: F401  (registra todos los modelos)
from app.core.database import Base, SessionLocal


def _ultimo_backup() -> Path:
    carpeta = Path("backups")
    backups = sorted(carpeta.glob("backup_*.json"))
    if not backups:
        raise SystemExit("No hay respaldos en backups/.")
    return backups[-1]


def restaurar(ruta: Path) -> dict[str, int]:
    data = json.loads(ruta.read_text(encoding="utf-8"))
    db = SessionLocal()
    insertados: dict[str, int] = {}
    try:
        for tabla in Base.metadata.sorted_tables:
            filas = data.get(tabla.name, [])
            if not filas:
                continue
            pk_cols = [c.name for c in tabla.primary_key.columns]
            nuevos = 0
            for fila in filas:
                existe = False
                if pk_cols and all(fila.get(c) is not None for c in pk_cols):
                    cond = [tabla.c[c] == fila[c] for c in pk_cols]
                    existe = db.execute(select(tabla).where(*cond)).first() is not None
                if existe:
                    continue
                columnas = {c.name for c in tabla.columns}
                db.execute(tabla.insert().values(**{k: v for k, v in fila.items() if k in columnas}))
                nuevos += 1
            if nuevos:
                db.commit()
                insertados[tabla.name] = nuevos
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return insertados


def main() -> None:
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else _ultimo_backup()
    print(f"Restaurando desde: {ruta}")
    insertados = restaurar(ruta)
    total = sum(insertados.values())
    if total == 0:
        print("Nada que restaurar: todos los registros del respaldo ya existen en la BD.")
    else:
        print(f"Filas restauradas (faltaban): {total}")
        for nombre, n in sorted(insertados.items()):
            print(f"  {nombre}: {n}")


if __name__ == "__main__":
    main()
