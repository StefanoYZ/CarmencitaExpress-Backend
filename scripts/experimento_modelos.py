"""Banco de pruebas riguroso de los modelos de optimizacion 3D.

Genera escenarios sinteticos con DISTINTAS distribuciones de tamano de paquete,
inyecta esos paquetes (monkeypatch de list_packages) y corre los 7 modelos
activos (incluido backtracking, ya corregida la carga excesiva) sobre cada
escenario, con varias semillas para medir variabilidad. Reporta colocados, utilizacion %, tiempo y penalizacion de
entrega, y un ranking agregado que promedia la posicion de cada modelo a traves
de todos los escenarios.

Complementa a scripts/comparar_modelos.py (que corre una sola vez sobre el
fixture real packages_70.json). Aqui el objetivo es aislar el efecto de la
FORMA y la HETEROGENEIDAD de los paquetes sobre la calidad del acomodo.

Uso (desde la raiz del backend, con el venv):
    PYTHONPATH=. .venv/Scripts/python.exe scripts/experimento_modelos.py

Los resultados de referencia estan documentados en docs/comparacion-modelos.md.
"""
from __future__ import annotations

import statistics
from random import Random

from app.modules.optimization_poc import service
from app.modules.optimization_poc.schema import Package, RunRequest
from app.modules.optimization_poc.utils.constants import LOGISTIC_ROUTE, ROUTE_RANK

TRUCK = "CAMION_A"          # 491 x 210 x 220 cm  (largo x ancho x alto), 5470 kg
DESTINOS = [d for d in LOGISTIC_ROUTE if d != "TRUJILLO"]

# ---------------------------------------------------------------------------
# Generadores de escenarios: cada uno devuelve una funcion (rng)->dims(cm) y un
# rango de densidad kg/m3 para derivar el peso. Todas las cotas estan pensadas
# para el CAMION_A (491x210x220). El objetivo es aislar el efecto de la FORMA y
# la HETEROGENEIDAD de los paquetes sobre el acomodo.
# ---------------------------------------------------------------------------

def _dims_pequenos(rng: Random):
    # Cajas chicas y compactas: muchas caben, poco desperdicio intrinseco.
    return (rng.randint(20, 45), rng.randint(20, 45), rng.randint(20, 45))

def _dims_grandes(rng: Random):
    # Bultos voluminosos tipo electrodomestico: pocos, dominan el volumen.
    return (rng.randint(70, 130), rng.randint(60, 100), rng.randint(80, 190))

def _dims_cubicos(rng: Random):
    # Cubos casi identicos ~50: mide eficiencia pura de empaquetado (poca forma).
    base = rng.randint(48, 54)
    return (base, base, rng.randint(48, 54))

def _dims_planos_largos(rng: Random):
    # Formas incomodas: tablones/roperos/tubos. Estresa la fragmentacion.
    tipo = rng.random()
    if tipo < 0.5:
        return (rng.randint(160, 200), rng.randint(50, 80), rng.randint(10, 22))   # plano
    return (rng.randint(180, 200), rng.randint(18, 30), rng.randint(18, 30))        # largo/tubo

def _dims_mixto(rng: Random):
    # Mezcla realista: 55% chicos, 30% medianos, 15% grandes.
    r = rng.random()
    if r < 0.55:
        return _dims_pequenos(rng)
    if r < 0.85:
        return (rng.randint(45, 75), rng.randint(40, 65), rng.randint(40, 80))
    return _dims_grandes(rng)

def _dims_heterogeneo(rng: Random):
    # Heterogeneidad extrema: salta entre chico, plano, grande y cubo al azar.
    return rng.choice([_dims_pequenos, _dims_planos_largos, _dims_grandes, _dims_cubicos])(rng)


ESCENARIOS = {
    "PEQUENOS":     (_dims_pequenos,     (120, 220)),
    "GRANDES":      (_dims_grandes,      (110, 190)),
    "CUBICOS":      (_dims_cubicos,      (130, 200)),
    "PLANOS_LARGOS":(_dims_planos_largos,(150, 260)),
    "MIXTO":        (_dims_mixto,        (120, 220)),
    "HETEROGENEO":  (_dims_heterogeneo,  (120, 230)),
}

FRAGILIDADES = ["BAJA", "MEDIA", "ALTA"]


def generar_paquetes(escenario: str, n: int, seed: int) -> list[Package]:
    dims_fn, (den_lo, den_hi) = ESCENARIOS[escenario]
    rng = Random(seed)
    paquetes: list[Package] = []
    for i in range(1, n + 1):
        largo, ancho, alto = dims_fn(rng)
        vol_m3 = (largo * ancho * alto) / 1_000_000
        densidad = rng.uniform(den_lo, den_hi)         # kg/m3
        peso = round(max(1.0, min(vol_m3 * densidad, 180.0)), 1)
        destino = DESTINOS[i % len(DESTINOS)]
        # permite_rotacion: los muy altos/verticales no rotan (como el fixture real).
        permite_rot = not (alto >= 150 and alto > largo and alto > ancho)
        paquetes.append(Package(
            id=i,
            codigo=f"E{escenario[:3]}{i:04d}",
            descripcion=f"{escenario.lower()} {i}",
            destino=destino,
            orden_entrega=ROUTE_RANK.get(destino.upper(), 0),
            prioridad=rng.randint(1, 3),
            fragilidad=rng.choice(FRAGILIDADES),
            peso_kg=peso,
            largo_cm=largo,
            ancho_cm=ancho,
            alto_cm=alto,
            permite_rotacion=permite_rot,
        ))
    return paquetes


# Monkeypatch: el servicio obtiene los paquetes via list_packages(limit, shuffled).
_ACTUAL: list[Package] = []

def _fake_list_packages(limit: int = 70, shuffled: bool = True):
    return list(_ACTUAL[:limit]) if limit else list(_ACTUAL)

service.list_packages = _fake_list_packages


def _req(n: int, strategy: str = "MINIMAX") -> RunRequest:
    return RunRequest(truck_id=TRUCK, package_limit=min(n, 70), allow_rotation=True, strategy=strategy)


MODELOS = [
    ("BEST_FIT_DECREASING_3D", lambda n: service.run_best_fit_decreasing(_req(n))),
    ("FIRST_FIT_3D",           lambda n: service.run_first_fit(_req(n))),
    ("BEST_FIT_3D",            lambda n: service.run_best_fit(_req(n))),
    ("WORST_FIT",              lambda n: service.run_worst_fit(_req(n))),
    ("MINIMAX",                lambda n: service.run_minimax_maximin(_req(n, "MINIMAX"))),
    ("MAXIMIN",                lambda n: service.run_minimax_maximin(_req(n, "MAXIMIN"))),
    ("BACKTRACKING",           lambda n: service.run_backtracking_logistic(_req(n))),
]


def correr_una(escenario: str, n: int, seed: int) -> dict[str, dict]:
    global _ACTUAL
    _ACTUAL = generar_paquetes(escenario, n, seed)
    salida = {}
    for nombre, runner in MODELOS:
        m = runner(n).metrics
        salida[nombre] = {
            "coloc": m.placed_count,
            "util": m.utilization_percent,
            "ms": m.execution_ms,
            "pen": m.delivery_order_penalty,
            "viol": m.overlap_violations + m.boundary_violations,
        }
    return salida


def main() -> None:
    N = 70                              # RunRequest limita a 70; usamos el maximo.
    SEEDS = [11, 29, 47, 83, 101]       # 5 semillas -> promedio + desviacion.

    print(f"Camion CAMION_A (491x210x220 cm, 5470 kg) | N={N} paquetes | "
          f"{len(SEEDS)} semillas por escenario\n", flush=True)

    resumen_global: dict[str, list[int]] = {nombre: [] for nombre, _ in MODELOS}

    for escenario in ESCENARIOS:
        # Acumula por modelo a traves de las semillas.
        acc = {nombre: {"coloc": [], "util": [], "ms": [], "pen": [], "viol": []} for nombre, _ in MODELOS}
        for seed in SEEDS:
            res = correr_una(escenario, N, seed)
            for nombre in acc:
                for k in acc[nombre]:
                    acc[nombre][k].append(res[nombre][k])

        print("=" * 78)
        print(f"ESCENARIO: {escenario}")
        print("-" * 78)
        print(f"{'modelo':<24}{'coloc(+/-)':>13}{'util%(+/-)':>14}{'ms':>7}{'pen':>9}{'viol':>6}")
        filas = []
        for nombre in acc:
            coloc_m = statistics.mean(acc[nombre]["coloc"])
            coloc_sd = statistics.pstdev(acc[nombre]["coloc"])
            util_m = statistics.mean(acc[nombre]["util"])
            util_sd = statistics.pstdev(acc[nombre]["util"])
            ms_m = statistics.mean(acc[nombre]["ms"])
            pen_m = statistics.mean(acc[nombre]["pen"])
            viol_m = statistics.mean(acc[nombre]["viol"])
            filas.append((nombre, coloc_m, coloc_sd, util_m, util_sd, ms_m, pen_m, viol_m))
        filas.sort(key=lambda f: (-f[1], -f[3]))     # mas colocados, luego mas util.
        for i, (nombre, cm, csd, um, usd, ms, pen, viol) in enumerate(filas, 1):
            resumen_global[nombre].append(i)
            print(f"{nombre:<24}{cm:>7.1f}+/-{csd:>3.1f}{um:>9.1f}+/-{usd:>3.1f}{ms:>7.0f}{pen:>9.0f}{viol:>6.1f}")
        print(f"  --> Mejor en {escenario}: {filas[0][0]}")
        print(flush=True)

    print("=" * 78)
    print("RANKING AGREGADO (posicion promedio a traves de todos los escenarios; 1=mejor)")
    print("-" * 78)
    agg = sorted(resumen_global.items(), key=lambda kv: statistics.mean(kv[1]))
    for nombre, posiciones in agg:
        print(f"  {statistics.mean(posiciones):>4.2f}   {nombre:<24} posiciones={posiciones}", flush=True)


if __name__ == "__main__":
    main()
