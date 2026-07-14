# Pruebas de carga y disponibilidad (JMeter)

Plan de carga sobre `POST /api/v1/encomiendas/pre-registro` (endpoint público de
registro, el de mayor tráfico esperado).

- `carmencita_preregistro.jmx` — plan JMeter (2 escenarios: disponibilidad + carga).
- `preregistro_data.csv` — datos parametrizados (DNI + destino) que rotan entre hilos.

La documentación completa (objetivos, umbrales/SLA, interpretación de métricas)
está en [`docs/pruebas/PRUEBAS_CARGA_JMETER.md`](../../docs/pruebas/PRUEBAS_CARGA_JMETER.md).

## Requisitos
- Apache JMeter 5.6+ (`https://jmeter.apache.org/download_jmeter.cgi`), requiere Java 8+.
- Backend levantado y accesible (local o Droplet).

## Ejecución rápida (modo CLI, sin GUI — recomendado para medir)

```bash
# Desde tests/carga/  (ajusta host/port; por defecto 127.0.0.1:8000)

# Smoke de disponibilidad (1 hilo, 10 envíos, valida 201 + SLA):
jmeter -n -t carmencita_preregistro.jmx -l resultados_smoke.jtl \
  -Jhost=127.0.0.1 -Jport=8000

# Carga: 50 hilos concurrentes, rampa 30s, durante 120s:
jmeter -n -t carmencita_preregistro.jmx -l resultados_carga.jtl \
  -Jhost=127.0.0.1 -Jport=8000 -Jthreads=50 -Jrampup=30 -Jduration=120

# Reporte HTML navegable a partir del .jtl:
jmeter -g resultados_carga.jtl -o reporte_html/
```

> Contra el Droplet en producción: `-Jhost=159.203.167.45 -Jport=80`. Ten en
> cuenta que cada envío crea un pre-registro real en la BD; usa un entorno de
> prueba o limpia los registros generados después.

## Parámetros (`-J`)
| Propiedad | Default | Descripción |
|---|---|---|
| `host` / `port` / `protocol` | `127.0.0.1` / `8000` / `http` | Destino |
| `threads` | `50` | Hilos concurrentes (escenario de carga) |
| `rampup` | `30` | Segundos para arrancar todos los hilos |
| `duration` | `120` | Duración del escenario de carga (s) |
| `sla_ms` | `2000` | Umbral de tiempo de respuesta del smoke (Duration Assertion) |
| `smoke_loops` | `10` | Nº de envíos del escenario de disponibilidad |
