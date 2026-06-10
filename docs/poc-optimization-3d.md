# PoC de optimizacion de carga 3D

Esta prueba de concepto evalua algoritmos de acomodo de paquetes en un camion para Carmencita Express Cargo. La PoC esta aislada de los modulos productivos y utiliza fixtures JSON.

## Ramas

- `feature/poc-packing-ui-base`: interfaz, dataset, contrato y componentes compartidos.
- `feature/poc-first-fit-3d`: rama prevista para First Fit 3D.
- `feature/poc-minimax-maximin-3d`: rama prevista para Minimax/Maximin experimental.

## Dataset y camiones

El dataset comun vive en `app/modules/optimization_poc/fixtures/packages_50.json` y contiene 50 paquetes. Los camiones estan en `trucks.json`:

- Camion A: 600 x 300 x 250 cm, 5000 kg.
- Camion B: 500 x 220 x 220 cm, 3500 kg.

La lista inicial se desordena con semilla fija `2026`. El ordenamiento logistico usa orden de entrega, prioridad, fragilidad, volumen descendente y codigo.

## Coordenadas

- `X`: ancho del camion.
- `Y`: altura.
- `Z`: largo o profundidad.
- Origen `(0, 0, 0)`: esquina inferior izquierda cercana a la puerta.
- Puerta: `Z = 0`.

## Endpoints

- `GET /api/v1/optimization/poc/packages?limit=50`
- `GET /api/v1/optimization/poc/trucks`
- `GET /api/v1/optimization/poc/scenario`
- `POST /api/v1/optimization/poc/first-fit/run`
- `POST /api/v1/optimization/poc/minimax-maximin/run`

## Algoritmos

First Fit 3D procesa paquetes ordenados, genera orientaciones permitidas, calcula puntos candidatos desde bordes de paquetes ya colocados y elige la primera posicion valida.

Minimax/Maximin es una adaptacion experimental: Minimax minimiza la peor penalizacion local; Maximin maximiza el peor puntaje positivo entre soporte, compactacion, accesibilidad y estabilidad.

## Restricciones y metricas

Se valida que las cajas esten dentro del camion, no se solapen, respeten peso maximo, tengan soporte minimo y no ubiquen paquetes pesados sobre paquetes de fragilidad alta.

Las metricas incluyen tiempo, volumen usado, paquetes colocados/no colocados, peso total, violaciones, rotaciones y distancia promedio respecto a la puerta.

## Limitaciones

No hay QR real, camara, scheduler productivo ni persistencia de resultados. La visualizacion 3D usa solo coordenadas generadas por el backend.
