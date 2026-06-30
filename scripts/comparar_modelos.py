"""Compara los modelos de optimización 3D sobre el mismo escenario.

Ejecuta cada algoritmo con el mismo set de paquetes (fixture packages_70.json) y
camión, y tabula las métricas clave para decidir cuáles activar.
"""
from __future__ import annotations

from app.modules.optimization_poc.schema import RunRequest
from app.modules.optimization_poc.service import (
    run_best_fit,
    run_best_fit_decreasing,
    run_first_fit,
    run_minimax_maximin,
    run_worst_fit,
)

LIMIT = 70
TRUCK = "CAMION_A"
ACTIVO = "BEST_FIT_DECREASING_3D"


def _req(strategy="MINIMAX"):
    return RunRequest(truck_id=TRUCK, package_limit=LIMIT, allow_rotation=True, strategy=strategy)


MODELOS = [
    ("BEST_FIT_DECREASING_3D", lambda: run_best_fit_decreasing(_req())),
    ("FIRST_FIT_3D", lambda: run_first_fit(_req())),
    ("BEST_FIT_3D", lambda: run_best_fit(_req())),
    ("WORST_FIT", lambda: run_worst_fit(_req())),
    ("MINIMAX", lambda: run_minimax_maximin(_req("MINIMAX"))),
    ("MAXIMIN", lambda: run_minimax_maximin(_req("MAXIMIN"))),
]


def main() -> None:
    filas = []
    for nombre, runner in MODELOS:
        print(f"... corriendo {nombre}", flush=True)
        try:
            m = runner().metrics
            filas.append({
                "modelo": nombre,
                "colocados": m.placed_count,
                "sin_colocar": m.unplaced_count,
                "util_%": m.utilization_percent,
                "violaciones": m.overlap_violations + m.boundary_violations,
                "pen_entrega": m.delivery_order_penalty,
                "ms": m.execution_ms,
            })
        except Exception as exc:  # noqa: BLE001
            filas.append({"modelo": nombre, "error": f"{type(exc).__name__}: {exc}"})

    cab = f"{'modelo':<24}{'coloc':>7}{'sin':>6}{'util%':>8}{'viol':>6}{'pen_ent':>10}{'ms':>7}"
    print(cab)
    print("-" * len(cab))
    for f in filas:
        if "error" in f:
            print(f"{f['modelo']:<24}  ERROR: {f['error']}")
            continue
        print(f"{f['modelo']:<24}{f['colocados']:>7}{f['sin_colocar']:>6}"
              f"{f['util_%']:>8}{f['violaciones']:>6}{f['pen_entrega']:>10}{f['ms']:>7}")

    # Ranking: más colocados, más utilización, menos violaciones, menor penalización de entrega.
    validos = [f for f in filas if "error" not in f]
    ranking = sorted(
        validos,
        key=lambda f: (-f["colocados"], -f["util_%"], f["violaciones"], f["pen_entrega"]),
    )
    print("\nRanking (mejor primero):")
    for i, f in enumerate(ranking, 1):
        marca = "  <- ACTIVO" if f["modelo"] == ACTIVO else ""
        print(f"  {i}. {f['modelo']}{marca}")

    otros = [f["modelo"] for f in ranking if f["modelo"] != ACTIVO]
    print(f"\nActivo actual: {ACTIVO}")
    print(f"Dos mejores adicionales sugeridos: {otros[0]}, {otros[1]}")


if __name__ == "__main__":
    main()
