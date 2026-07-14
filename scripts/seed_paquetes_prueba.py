"""Siembra encomiendas VARIADAS de prueba registradas HOY para probar la
optimizacion 3D desde la interfaz (vista ESTIBA -> Optimizacion de carga).

Es el equivalente por linea de comandos del switch "modo prueba" de la Vista
Developer: usa las MISMAS funciones (app/modules/optimization_poc/test_data.py),
por lo que ambos caminos generan y limpian los paquetes de forma identica.

El escenario de la interfaz usa los paquetes de prueba cuando existen; si no,
usa las encomiendas reales registradas por la web.

Uso (desde la raiz del backend, con el venv):
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_paquetes_prueba.py
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_paquetes_prueba.py --n 50
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_paquetes_prueba.py --clear
"""
from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.modules.optimization_poc.test_data import (
    DEFAULT_TEST_PACKAGE_COUNT,
    REGISTERED_STATUS,
    clear_test_packages,
    seed_test_packages,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Siembra encomiendas de prueba para la optimizacion 3D.")
    parser.add_argument("--n", type=int, default=DEFAULT_TEST_PACKAGE_COUNT,
                        help=f"Cantidad de paquetes a crear (default {DEFAULT_TEST_PACKAGE_COUNT}).")
    parser.add_argument("--seed", type=int, default=2026, help="Semilla del generador (default 2026).")
    parser.add_argument("--clear", action="store_true",
                        help="Solo borrar los paquetes de prueba y salir (apaga el modo prueba).")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.clear:
            borradas = clear_test_packages(db)
            print(f"Paquetes de prueba borrados: {borradas}. Modo prueba APAGADO.", flush=True)
            return

        creadas = seed_test_packages(db, n=args.n, seed=args.seed)
        print(f"Creadas {creadas} encomiendas de prueba (estado {REGISTERED_STATUS}, hoy).", flush=True)
        print("Origen TRUJILLO | destinos variados | 7 algoritmos habilitados.", flush=True)
        print("Abre la vista ESTIBA -> Optimizacion de carga y corre/compara los modelos.", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
