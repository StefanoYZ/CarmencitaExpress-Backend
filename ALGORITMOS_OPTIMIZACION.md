# Algoritmos de optimización de carga 3D — construcción y sustento

Documento técnico de los **7 algoritmos** del módulo `app/modules/optimization_poc`.
Explica cómo está construido cada uno, la infraestructura común que comparten, las
restricciones físicas y logísticas que respetan, y el sustento (por qué se diseñó
así) de cada decisión. Se basa en el código real, no en la teoría genérica.

> Camión de referencia (`fixtures/trucks.json`): **CAMION_A = 491 × 210 × 220 cm**
> (largo × ancho × alto), **5470 kg**. Sistema de coordenadas: `x` = ancho, `y` = alto,
> `z` = largo/profundidad. El origen `(0,0,0)` es la esquina inferior del fondo del box
> (junto a la cabina); `z = 0` es el fondo y `z = largo_cm` es la puerta de carga.

---

## 1. Panorama: dos familias de algoritmos

Los 7 modelos se agrupan por el **motor de colocación** que usan:

| # | Algoritmo | Motor | Endpoint |
|---|-----------|-------|----------|
| 1 | First Fit 3D | Heurístico denso + progresivo | `/first-fit/run` |
| 2 | Best Fit 3D | Heurístico denso + progresivo | `/best-fit/run` |
| 3 | Worst Fit | Heurístico denso + progresivo | `/worst-fit/run` |
| 4 | Best Fit Decreasing 3D | Heurístico denso + progresivo | `/best-fit-decreasing/run` |
| 5 | Minimax | Heurístico denso + progresivo | `/minimax-maximin/run` (`strategy=MINIMAX`) |
| 6 | Maximin | Heurístico denso + progresivo | `/minimax-maximin/run` (`strategy=MAXIMIN`) |
| 7 | Backtracking (orden logístico) | Recursivo sobre espacios libres | `/backtracking/run` |

**Hecho clave de arquitectura:** los modelos 1–6 comparten *exactamente el mismo motor*
(`service._run_simulation`) y **solo se diferencian en dos funciones**: cómo **ordenan**
los paquetes (`order_packages`) y con qué **función de puntaje** eligen la posición
(`_score`). El modelo 7 (backtracking) es el único con motor propio
(`service._run_logistic_simulation` → `backtracking_3d_algorithm`).

> Nota de código: existen dos funciones grandes de "espacios libres"
> (`worst_fit_algorithm` y `best_fit_decreasing_3d_algorithm`) que quedaron en el
> repositorio pero **no las invoca ningún endpoint**; son implementaciones alternativas
> heredadas. Los endpoints de Worst Fit y Best Fit Decreasing usan la versión de
> **candidatos densos** descrita en la sección 2. La lógica de `best_fit_decreasing_3d`
> sí se reutiliza como *semilla* del backtracking.

---

## 2. El motor común de los heurísticos (modelos 1–6)

Todo modelo heurístico se ejecuta con `_run_simulation`, que hace lo siguiente
(`service.py`):

1. **Filtra sobres.** Los `DOCUMENTOS` (`requires_packing = False`) no se estiban.
2. **Ordena** los paquetes con `order_packages` propio del modelo.
3. **Colocación progresiva** (`select_progressive_placement`): en cada paso **evalúa
   TODOS los paquetes pendientes** con `find_placement`, y coloca el que quede **más al
   fondo posible** (menor `z`). Esto permite que una pieza pequeña rellene un hueco
   trasero antes de avanzar hacia la puerta, en lugar de colocar estrictamente en el
   orden de la lista.
4. **Control de peso:** antes de cada paso descarta los pendientes que excederían
   `capacidad_peso_kg` (`is_weight_allowed`) y los marca como no colocados.
5. **Recalcula pesos soportados** (`recompute_supported_weights`) tras cada colocación,
   para que la restricción de fragilidad/estiba se evalúe con el estado real de la pila.
6. **Calcula métricas** y arma la respuesta.

### 2.1 Cómo se generan las posiciones candidatas (`dense_valid_candidates`)

Para un paquete y el estado actual del box:

1. **Orientaciones** (`orientations`): la **cara base** elegida por el usuario
   (`orientacion_base`: `LARGO_ANCHO` / `LARGO_ALTO` / `ANCHO_ALTO`) reduce el paquete a
   **2 giros horizontales**. Un electrodoméstico vertical detectado por palabra clave
   (refrigeradora, lavadora, etc.) se fuerza a **una sola orientación de pie** y no rota.
2. **Puntos candidatos densos** (`dense_candidate_points`): genera muchos puntos de apoyo
   — esquinas de piezas ya colocadas, proyecciones sobre el piso, el `target_z` de la
   ruta, etc. — para explorar posiciones que "encajan" pegadas a lo ya cargado.
3. **Validación física** (`is_valid_placement`, sección 3) de cada punto.
4. **Frontera de carga** (`filter_candidates_by_loading_frontier`): descarta posiciones a
   las que no se podría llegar desde la puerta sin mover otra caja, y se queda solo con
   las del frente activo (menor `z`). Sustenta que la carga sea **físicamente cargable**
   de fondo a puerta, no un Tetris imposible.

`find_placement` toma esos candidatos válidos y elige `min(candidates, key=_score)`. La
diferencia entre los 6 heurísticos está **toda** en `order_packages` y `_score`.

### 2.2 Orden de los paquetes (`package_sort_key`)

Todas las claves empiezan por `-route_rank` → **primero los destinos más lejanos**
(se cargan al fondo). Luego cada estrategia prioriza distinto:

| Estrategia | Clave de orden (se ordena ascendente) | Sustento |
|-----------|----------------------------------------|----------|
| First Fit (default) | `(-ruta, prioridad, estiba, fragilidad, -huella, -volumen, código)` | Estable y "natural": lejano→cercano, frágiles primero por estiba, luego piezas de mayor huella. |
| Best Fit | `(-ruta, prioridad, estiba, -volumen, -huella, -peso, código)` | Prioriza volumen para que las grandes fijen el patrón y las chicas rellenen. |
| Maximin | `(-ruta, prioridad, estiba, -huella, -peso, -volumen, código)` | Huella y peso primero → bases anchas y firmes abajo. |
| Minimax | `(-ruta, -volumen, -peso, prioridad, estiba, código)` | Volumen/peso mandan sobre prioridad: mete primero lo grande y pesado. |

(`estiba` = `STACK_PRIORITY`, `fragilidad` = `FRAGILITY_ORDER`.)

### 2.3 Función de puntaje de cada heurístico (`_score`)

`_score` devuelve una **tupla que se minimiza lexicográficamente**. Un valor menor = mejor
posición. Los componentes provienen de `geometry.py`:

- `support_ratio` / `support_penalty` = fracción de la base apoyada (1 − apoyo).
- `contact_score` / `contact_penalty` = cuánto "toca" paredes, piso y vecinos (compacidad).
- `route_alignment_penalty` = distancia al `target_z` que le corresponde por su destino.
- `projected_bounding_volume` = volumen de la caja envolvente de todo lo cargado
  (crecerla poco = empaque denso).
- `loading_flow_key` = clave base común (z, y, x, ruta, apoyo, contacto) que impone el
  flujo de carga fondo→puerta y abajo→arriba.
- `x/y/z_waste` = desperdicio remanente en cada eje.

| Modelo | Idea central de `_score` (qué minimiza/optimiza) | Sustento |
|--------|--------------------------------------------------|----------|
| **First Fit 3D** | Flujo de carga + primer hueco denso: crece poco la envolvente, se mantiene bajo y pegado, con poca preferencia por no rotar. | La opción **factible más temprana** en el flujo natural; rápido y predecible. |
| **Best Fit 3D** | El **ajuste más ceñido**: minimiza volumen proyectado y suma de desperdicios `x+y+z`, priorizando fondo y piso. | Deja el mínimo hueco alrededor de cada caja → mejor aprovechamiento local. |
| **Worst Fit** | Prioriza contacto y apoyo y luego **maximiza el hueco restante** de la caja envolvente (`-remaining_box_volume`). | Reparte en huecos grandes para **preservar huecos utilizables** para piezas futuras. |
| **Best Fit Decreasing 3D** | Minimiza la **profundidad proyectada** y el **vacío proyectado** (`projected_void_ratio`). | Con paquetes ya ordenados de mayor a menor, empaca denso manteniendo el frente poco profundo. |
| **Minimax** | Minimiza el **peor desperdicio** de los tres ejes (`max(x,y,z_waste)`). | Evita que un solo eje quede muy desaprovechado → colocaciones equilibradas. Suele **colocar más paquetes**. |
| **Maximin** | Maximiza el **mínimo** de las cualidades buenas (apoyo, contacto, compacidad, huella, piso). | Favorece la posición más "segura y firme" en el peor de sus aspectos → estabilidad. |

**Minimax vs Maximin** son duales: Minimax **minimiza lo peor** (desperdicio), Maximin
**maximiza lo mínimo** (calidad de apoyo). Comparten `loading_flow_key`, así que ambos
respetan el flujo de carga; cambian el criterio fino.

---

## 3. Restricciones físicas compartidas (`validators.py`)

Ninguna posición es válida si no cumple **todas** (`is_valid_placement`):

1. **Dentro del camión** (`is_inside_truck`): no sobresale de 491×210×220.
2. **Sin solapamiento** (`has_overlap`): AABB, ninguna caja se cruza con otra.
3. **Apoyo mínimo** (`has_minimum_support`): al menos **60 %** (`SUPPORT_RATIO = 0.60`)
   de la base debe descansar sobre el piso o sobre cajas inferiores. Evita voladizos.
4. **Fragilidad / estiba** (`respects_fragility`): cada caja soporta un peso máximo según
   su fragilidad, con `stacking_capacity = peso × factor`:
   - `ALTA → 0.0` (no se le pone **nada** encima),
   - `MEDIA → 0.5 × peso`,
   - `BAJA → 1.5 × peso`.
   El peso acumulado transmitido hacia abajo no puede exceder esa capacidad.
5. **Apoyo lateral de piezas delgadas verticales** (`has_lateral_support_for_vertical_thin`):
   una pieza fina parada necesita tocar una pared o un vecino con ≥ 35 % de contacto
   lateral, o se rechaza (evita que se caiga).

El sustento es de **seguridad de carga real**: apoyo, no aplastar frágiles, no voladizos,
no torres inestables.

---

## 4. Reglas logísticas de ruta (`logistic_rules.py`, `models`)

La ruta `LOGISTIC_ROUTE` tiene **19 paradas**, de `TRUJILLO` (origen) a `OROCULLAY`
(más lejana). Reglas:

- **Orden de entrega inverso:** el **destino más lejano se carga primero y va al fondo**
  (`z` alto); el más cercano queda junto a la puerta. Supuesto explícito:
  *"Los destinos más lejanos se cargan primero y se ubican al fondo del box."* Así el
  reparto descarga sin remover carga de otros destinos (LIFO por parada).
- **`target_z` por destino** (`target_z_from_rank` / `route_alignment_penalty`): a cada
  destino le corresponde una profundidad ideal; alejarse de ella penaliza el puntaje.
- **Zonas** (`get_destination_zone`): CERCANA / MEDIA / LEJANA según el rango en la ruta.
- **Penalización de zona** (`calculate_zone_distance_penalty`) y **frontera de carga**
  (`filter_candidate_options_by_loading_frontier`): mantienen coherente el orden espacial
  con el orden de reparto.

Estas reglas se **integran en el puntaje** de todos los modelos (vía `route_penalty` /
`loading_flow_key` en los heurísticos, y de forma explícita en el backtracking).

---

## 5. Backtracking con orden logístico (modelo 7)

Único modelo con **motor propio recursivo** (`backtracking_3d_algorithm`). Modela el box
como **lista de espacios libres** que se parten al colocar una caja
(`split_space`, tipo guillotina), en lugar de puntos candidatos.

### 5.1 Estructura de la búsqueda

1. **Orden:** lejano primero, luego `-volumen`, `-peso`, código.
2. **Semilla codiciosa** (`build_progressive_seed`): construye una primera solución con la
   colocación *Best Fit Decreasing densa* y la fija como `best_solution` inicial. Así el
   backtracking **nunca devuelve algo peor que el heurístico**.
3. **Búsqueda recursiva** `backtrack(index, ...)` sobre cada paquete: por cada uno prueba
   sus rotaciones × espacios libres válidos, valida estiba/estabilidad/zona, y **ramifica**;
   además explora la rama de **no colocar** ese paquete (a veces saltarse uno deja lugar
   para dos).
4. **Objetivo** (`is_better_solution`): **maximizar paquetes colocados**; a igualdad,
   maximizar volumen usado.

### 5.2 Poda y límites — el porqué del arreglo de "carga excesiva"

El backtracking puro **explota combinatoriamente** al crecer el número de paquetes. La
versión actual lo acota con varias técnicas simultáneas (constantes arriba del archivo):

- **Cota superior (`branch and bound`):** si `colocados + restantes < mejor_actual`, poda
  la rama (no puede superar lo ya hallado).
- **Memo de estados vistos** (`seen_states`): si ya visitó un estado equivalente
  (índice, peso, espacios libres, colocados) con igual o mejor calidad, corta.
- **Tope de ramas por nivel:** `BACKTRACKING_MAX_BRANCHES_PER_LEVEL = 8`. Dedup + ordena
  los candidatos por (zona, penalización, z, y, x, score) y **conserva solo los 8 mejores**.
- **Límite de tiempo:** `BACKTRACKING_MAX_SECONDS = 3.0` s.
- **Límite de nodos:** `BACKTRACKING_MAX_NODES = 25 000`.
- **Peso:** si `peso_total + paquete > 5470 kg`, ese paquete se marca `WEIGHT_LIMIT` y no
  se carga (nunca sobrepasa la capacidad del camión).

Cuando salta un límite de tiempo/nodos, marca `interrupted` y **devuelve la mejor solución
encontrada hasta ese momento** (que en el peor caso es la semilla codiciosa). Por eso ahora
**termina en ≤ 3 s con 0 violaciones** aunque se aumenten los paquetes, en vez de dispararse.

> Verificado en `scripts/experimento_modelos.py` (70 paquetes, 6 escenarios, 5 semillas):
> backtracking corre con `viol = 0.0` en todos los escenarios y su acomodo coincide con
> Best Fit Decreasing en 5 de 6 (misma semilla), diferenciándose solo en tiempo.

### 5.3 Correctitud del estado por rama

Como cada rama debe tener su propio estado, se clonan las estructuras mutables:
`clone_free_spaces` (copia ligera de espacios) y `clone_placed_packages` (obligatorio
porque `register_supported_weight` modifica el peso soportado de las cajas de abajo). La
`best_solution` se guarda con `deepcopy` para que ramas posteriores no la corrompan.

---

## 6. Métricas de comparación (`metrics.py`)

Toda corrida reporta:

| Métrica | Significado |
|---------|-------------|
| `placed_count` / `unplaced_count` | Paquetes colocados / no colocados. |
| `utilization_percent` | Volumen usado / volumen del camión. |
| `total_weight_kg` | Peso total cargado. |
| `overlap_violations` / `boundary_violations` | Solapamientos / cajas fuera del box (deben ser **0**). |
| `delivery_order_penalty` | Media de `orden_entrega × z`: mide si el orden espacial respeta el de reparto (menor = mejor). |
| `rotation_count` | Cuántas piezas se rotaron. |
| `average_delivery_distance_cm` | Profundidad `z` media. |
| `execution_ms` | Tiempo de cómputo. |

---

## 7. Resumen comparativo y cuándo usar cada uno

Ranking agregado del experimento (posición promedio en 6 escenarios; 1 = mejor):

| # | Modelo | Pos. prom. | Perfil |
|---|--------|:---:|--------|
| 1 | **Worst Fit** | 2.00 | El más robusto en escenarios densos (grandes, cúbicos, mixto). Preserva huecos útiles. |
| 2 | Best Fit Decreasing 3D | 3.33 | Empaque denso; gana con heterogéneo y pequeños. |
| 3 | Minimax | 4.00 | Equilibrado; tiende a **colocar más piezas** al minimizar el peor desperdicio. |
| 4 | First Fit 3D | 4.17 | Simple y rápido; bueno con formas incómodas (planos/largos). |
| 5 | Best Fit 3D | 4.50 | Ajuste ceñido local; intermedio. |
| 6 | Maximin | 4.83 | Prioriza estabilidad/firmeza sobre cantidad. |
| 7 | Backtracking | 5.17 | Seguro (0 violaciones) y respeta el orden logístico; iguala a BFD en colocados pero es más lento (busca dentro de límites). |

**Criterio de elección:**
- **Máximo aprovechamiento / más paquetes:** Worst Fit o Minimax.
- **Empaque denso homogéneo:** Best Fit Decreasing.
- **Estabilidad/seguridad de la pila:** Maximin.
- **Respeto estricto del orden de reparto con garantía ≥ heurístico:** Backtracking.

---

## 8. Referencias de código

| Componente | Archivo |
|-----------|---------|
| Motor heurístico + progresivo | `service.py` (`_run_simulation`, `select_progressive_placement`) |
| Motor backtracking | `algorithms/backtracking_3d.py`, `service._run_logistic_simulation` |
| Orden y claves | `models/package.py` (`package_sort_key`, `destination_rank`) |
| Geometría y candidatos | `utils/geometry.py` |
| Restricciones físicas | `validators.py` |
| Reglas de ruta/estiba | `utils/logistic_rules.py` |
| Métricas | `utils/metrics.py` |
| Puntajes por modelo | `algorithms/{first_fit_3d,best_fit_3d,worst_fit,best_fit_decreasing_3d,minimax_3d,maximin_3d}.py` |
| Banco de pruebas | `scripts/experimento_modelos.py` |
