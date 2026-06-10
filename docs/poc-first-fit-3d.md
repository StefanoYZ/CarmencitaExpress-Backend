# PoC First Fit 3D

Este documento describe como se implemento la prueba de concepto First Fit 3D para la optimizacion de carga de Carmencita Express Cargo.

La PoC esta aislada de los modulos productivos. No persiste resultados en tablas de negocio y no modifica RENIEC, Payments, Yape, SUNAT, Encomiendas, Clientes, Usuarios ni Cotizaciones.

## Objetivo

Simular el acomodo de paquetes dentro de un camion usando coordenadas 3D generadas por backend y renderizadas en frontend.

El objetivo de esta rama es validar:

- Ordenamiento deterministico de paquetes.
- Calculo de posiciones `x`, `y`, `z`.
- Prevencion de solapes.
- Validacion de limites internos del camion.
- Validacion de peso maximo.
- Validacion de zonas logisticas por destino.
- Validacion de estiba por fragilidad.
- Validacion de estabilidad al apilar.
- Visualizacion progresiva paquete por paquete.
- Vistas isometrica, superior y frontal desde la puerta de carga.

## Rama

La implementacion corresponde a:

```txt
feature/poc-first-fit-3d
```

Esta rama parte de la base comun:

```txt
feature/poc-packing-ui-base
```

## Backend

Modulo creado:

```txt
app/modules/optimization_poc/
```

Archivos principales:

```txt
app/modules/optimization_poc/fixtures/packages_50.json
app/modules/optimization_poc/fixtures/trucks.json
app/modules/optimization_poc/repository.py
app/modules/optimization_poc/schema.py
app/modules/optimization_poc/service.py
app/modules/optimization_poc/validators.py
app/modules/optimization_poc/metrics.py
app/modules/optimization_poc/router.py
```

El router se registra en `app/main.py` bajo el prefijo global del API:

```txt
/api/v1
```

## Endpoints usados

### Escenario

```http
GET /api/v1/optimization/poc/scenario?limit=50
```

Devuelve:

- Lista inicial de paquetes.
- Camiones disponibles.
- Sistema de coordenadas usado por la PoC.

### Ejecucion First Fit

```http
POST /api/v1/optimization/poc/first-fit/run
```

Payload:

```json
{
  "truck_id": "CAMION_A",
  "package_limit": 50,
  "allow_rotation": true
}
```

Respuesta principal:

```json
{
  "simulation_id": "poc-xxxxxxxx",
  "algorithm": "FIRST_FIT_3D",
  "truck": {},
  "ordered_packages": [],
  "placements": [],
  "unplaced_packages": [],
  "metrics": {}
}
```

Cada elemento de `placements` contiene las coordenadas y dimensiones finales:

```json
{
  "package_id": 1,
  "codigo": "D000000001",
  "loading_sequence": 1,
  "delivery_order": 1,
  "x": 0,
  "y": 0,
  "z": 0,
  "width": 30,
  "height": 22,
  "depth": 42,
  "orientation": "WHD",
  "destination": "Santiago de Chuco",
  "fragility": "ALTA",
  "peso_kg": 8.7
}
```

## Sistema de coordenadas

El backend trabaja en centimetros.

```txt
X = ancho del camion
Y = altura del camion
Z = largo/profundidad del camion
Origen = (0, 0, 0)
Puerta de carga = Z = 0
Fondo del camion = Z positivo
```

Esto permite que la vista frontal del frontend se ubique desde la puerta `Z=0` mirando hacia el fondo del compartimiento.

## Dataset

Los datos de prueba viven en fixtures JSON:

```txt
packages_50.json
trucks.json
```

El camion principal de la PoC queda definido como:

```txt
Camion A
Ancho: 300 cm
Alto: 250 cm
Largo: 600 cm
Peso maximo: 5000 kg
```

La lectura se hace con `utf-8-sig` en `repository.py` porque los fixtures pueden venir guardados con BOM. Sin eso, Python puede lanzar:

```txt
JSONDecodeError: Unexpected UTF-8 BOM
```

## Ordenamiento logistico

Antes de acomodar, el backend desordena la lista inicial con semilla fija:

```txt
2026
```

La ruta logistica modelada en la PoC es:

```txt
TRUJILLO -> SHOREY -> HUAYATAN/HUAYCATAN -> SANTIAGO DE CHUCO -> CHACOMAS -> CACHICADAN -> SANTA CRUZ DE CHUCA -> COCHAPAMBA -> ALGALLAMA -> VILLACRUZ -> LAS MANZANAS -> ANGASMARCA -> OROCULLAY
```

Luego `ordered_packages()` ordena de forma deterministica usando:

1. destino mas lejano primero
2. `prioridad`
3. `fragilidad`
4. volumen descendente
5. `codigo`

La prioridad de fragilidad usada es:

```txt
ALTA -> MEDIA -> BAJA
```

## Algoritmo First Fit 3D

La funcion principal es:

```txt
run_first_fit()
```

Flujo:

1. Cargar camion por `truck_id`.
2. Cargar paquetes ordenados.
3. Recorrer paquete por paquete.
4. Validar peso acumulado.
5. Generar puntos candidatos.
6. Generar orientaciones posibles.
7. Probar cada combinacion hasta encontrar la primera posicion valida.
8. Registrar el paquete en `placements`.
9. Enviar a `unplaced_packages` si no hay posicion valida.
10. Calcular metricas.

## Puntos candidatos

La funcion `_candidate_points()` genera puntos a partir de paquetes ya colocados:

```txt
(0, 0, 0)
(x + width, y, z)
(x, y + height, z)
(x, y, z + depth)
```

Luego los ordena por:

```txt
Z, Y, X
```

El camion se divide en tres zonas sobre el eje `Z`:

```txt
Zona cercana: Z 0-200 cm
Zona media: Z 200-400 cm
Zona lejana: Z 400-600 cm
```

Los destinos lejanos se ubican en la zona lejana, al fondo del camion. Los destinos intermedios se ubican en zona media y los destinos cercanos en zona cercana.

El algoritmo prioriza posiciones en piso antes que apilar. Para zona lejana, los candidatos se prueban desde el fondo hacia la puerta. Para zona cercana y media, se prueban desde su inicio de zona hacia adelante.

## Rotaciones

La funcion `_orientations()` permite rotar paquetes cuando:

```txt
allow_rotation = true
package.permite_rotacion = true
```

Se generan permutaciones unicas de:

```txt
ancho, alto, largo
```

Cada orientacion queda etiquetada en `orientation`.

## Validaciones geometricas

La funcion `_is_valid()` acepta una posicion solo si cumple:

```txt
is_inside_truck()
_is_inside_logistic_zone()
not has_overlap()
has_minimum_support()
respects_fragility()
```

### Limites del camion

`is_inside_truck()` valida que el paquete no salga del volumen disponible:

```txt
x >= 0
y >= 0
z >= 0
x + width <= ancho camion
y + height <= alto camion
z + depth <= largo camion
```

### Solapes

`has_overlap()` rechaza paquetes que se intersectan en 3D.

### Zonas logisticas

`_is_inside_logistic_zone()` valida que el paquete permanezca dentro del sector asignado segun su destino:

```txt
cercana -> primer tercio del camion
media -> tercio central
lejana -> tercio del fondo
```

### Peso maximo

`is_weight_allowed()` valida que el peso acumulado no supere la capacidad del camion.

### Estabilidad de soporte

`has_minimum_support()` valida que un paquete elevado tenga soporte suficiente.

Reglas actuales:

```txt
SUPPORT_RATIO = 0.6
EDGE_SUPPORT_RATIO = 0.12
```

Esto significa:

- Si `y = 0`, el paquete esta en piso y se acepta el soporte.
- Si esta apilado, al menos 60% de la base debe estar soportada.
- Ademas debe existir soporte cerca de los bordes de ancho y profundidad.

Esta segunda regla se agrego para evitar que paquetes grandes queden balanceados sobre paquetes mas pequenos, lo que visualmente podia generar acomodos inestables.

### Fragilidad

`respects_fragility()` calcula la capacidad de carga segun la fragilidad del paquete que esta debajo:

```txt
ALTA -> soporta 0 kg
MEDIA -> soporta 50% de su propio peso
BAJA -> soporta 200% de su propio peso
```

Si un paquete superior se apoya en varios paquetes inferiores, su peso se distribuye proporcionalmente segun el area de contacto.

## Metricas

`calculate_metrics()` devuelve:

- `execution_ms`
- `truck_volume_cm3`
- `used_volume_cm3`
- `utilization_percent`
- `placed_count`
- `unplaced_count`
- `total_weight_kg`
- `overlap_violations`
- `boundary_violations`
- `delivery_order_penalty`
- `rotation_count`
- `average_delivery_distance_cm`

En la prueba actual con `CAMION_A` y 50 paquetes:

```txt
placements = 50
unplaced = 0
overlap_violations = 0
boundary_violations = 0
```

## Frontend

Pantalla principal:

```txt
frontend/src/pages/OptimizacionCarga.jsx
```

Escena 3D:

```txt
frontend/src/components/optimization-poc/PackingScene3D.jsx
```

Servicio API:

```txt
frontend/src/services/optimizationPocService.js
```

Ruta interna:

```txt
/admin/optimizacion-carga
```

Alias:

```txt
/admin/estiba/optimizacion-poc
```

## Renderizado 3D

La escena usa:

```txt
three
@react-three/fiber
@react-three/drei
```

El backend entrega centimetros. El frontend escala las coordenadas con:

```txt
SCALE = 0.012
```

Para centrar el camion en la escena, el frontend resta:

```txt
truck.ancho_cm / 2
truck.largo_cm / 2
```

Esto mantiene el origen logistico en backend, pero permite que la camara vea el camion centrado en Three.js.

## Vistas de camara

La escena tiene tres modos:

```txt
isometric
top
front
```

Botones visibles:

- Isometrica
- Superior
- Frontal

La vista frontal se ubica fuera de la puerta `Z=0` y mira hacia el fondo del camion.

## Avance paquete por paquete

Como el escaner QR real aun no esta conectado, el avance se controla con botones:

```txt
Anterior
Siguiente
```

La pantalla mantiene un cursor:

```txt
placementCursor
```

El render muestra:

```txt
orderedPlacements.slice(0, placementCursor)
```

De esta forma:

- Al presionar `Ordenar`, se muestra el primer paquete.
- `Siguiente` agrega el siguiente paquete al render.
- `Anterior` retrocede un paso.
- El paquete actual se resalta.
- Los paquetes previos quedan visibles como ya acomodados.

## Colores

Cada paquete recibe color por secuencia de carga, no por estado unico.

Esto evita que todos los paquetes se vean iguales al avanzar.

El paquete actual se diferencia con:

- mayor opacidad
- borde destacado
- etiqueta resaltada

## Flujo completo

1. El usuario entra a `/admin/optimizacion-carga`.
2. El frontend llama a `GET /optimization/poc/scenario`.
3. El usuario selecciona camion.
4. El usuario presiona `Ordenar`.
5. El frontend llama a `POST /optimization/poc/first-fit/run`.
6. El backend ejecuta First Fit 3D.
7. El backend devuelve `placements`.
8. El frontend renderiza el primer paquete.
9. El usuario avanza con `Siguiente`.
10. La escena agrega paquetes de forma progresiva.
11. El usuario puede cambiar entre vista isometrica, superior y frontal.
12. El usuario puede descargar el JSON de resultado.

## Validacion realizada

Backend:

```powershell
python -m compileall -q app\modules\optimization_poc app\main.py
```

Prueba directa del algoritmo:

```txt
placements 50
unplaced 0
overlap 0
boundary 0
```

Frontend:

```powershell
npm run build
```

Resultado:

```txt
build OK
```

## Limitaciones actuales

- No hay escaneo QR real.
- No se persisten resultados de simulacion.
- No hay scheduler real de cierre automatico.
- El algoritmo First Fit es deterministico, pero no garantiza optimizacion global.
- La estabilidad es una aproximacion geometrica, no una simulacion fisica.
- No considera friccion, aceleracion, curvas, frenado ni vibraciones del camion.

## Pendientes recomendados

- Agregar escaneo QR real o integracion con lector.
- Guardar simulaciones en una tabla propia si luego se requiere trazabilidad.
- Agregar validaciones por centro de masa.
- Penalizar apilados con diferencias grandes de base.
- Comparar First Fit con Minimax/Maximin usando las mismas metricas.
- Agregar pruebas unitarias para `has_minimum_support()`, `has_overlap()` y `_candidate_points()`.
