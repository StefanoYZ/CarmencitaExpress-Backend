# Business Core Sprint 1

Esta rama completa logica backend de encomiendas para Sprint 1. No se uso Alembic, no se crearon migraciones y la logica nueva persiste o lee datos reales desde PostgreSQL mediante SQLAlchemy.

## Estados De Encomienda

Estados permitidos:

- `PRE_REGISTRADA`
- `REGISTRADA`
- `COTIZADA`
- `PAGO_CONFIRMADO`
- `BOLETA_EMITIDA`
- `EN_TRANSITO`
- `EN_DESTINO`
- `ENTREGADA`
- `ANULADA`

## Endpoints Nuevos

- `POST /api/v1/encomiendas/pre-registro`
- `POST /api/v1/encomiendas/{encomienda_id}/confirmar-registro`
- `POST /api/v1/encomiendas/{encomienda_id}/anular`
- `GET /api/v1/encomiendas/{encomienda_id}/etiqueta`
- `GET /api/v1/encomiendas/{encomienda_id}/etiqueta/qr`
- `GET /api/v1/encomiendas/{encomienda_id}/etiqueta/pdf`
- `POST /api/v1/encomiendas/{encomienda_id}/entregar`

Los endpoints existentes de encomiendas, cotizaciones y SUNAT se mantienen.

## Pre-Registro

`POST /api/v1/encomiendas/pre-registro` crea una encomienda con codigo automatico, `estado = PRE_REGISTRADA` y `origen_registro = EXTERNO`.

No llama SUNAT, pagos, Yape, Mercado Pago ni RENIEC.

## Confirmacion De Pre-Registro

`POST /api/v1/encomiendas/{encomienda_id}/confirmar-registro` cambia `PRE_REGISTRADA` a `REGISTRADA`.

Reglas:

- 404 si la encomienda no existe.
- 400 si esta `ANULADA`.
- 400 si esta en un estado distinto a `PRE_REGISTRADA`.
- Mantiene `origen_registro = EXTERNO`.

## Registro Presencial

`POST /api/v1/encomiendas` mantiene la ruta publica actual.

Reglas:

- Genera `codigo_encomienda` en backend.
- Guarda `estado = REGISTRADA`.
- Guarda `origen_registro = INTERNO`.
- Acepta `tipo_contenido`.
- Valida `peso_kg`, `largo_cm`, `ancho_cm` y `alto_cm` mayores a cero.
- Valida `fragilidad` en `BAJA`, `MEDIA` o `ALTA`.
- No acepta `codigo_encomienda`, `id`, `created_at` ni `updated_at` en payload.

## Cotizacion Por Ruta

`POST /api/v1/cotizaciones/calcular`

Payload:

```json
{
  "encomienda_id": 1
}
```

Tarifa base por ruta normalizada:

- `Trujillo -> Angasmarca`: 10
- `Angasmarca -> Trujillo`: 10
- `Trujillo -> Huamachuco`: 8
- `Huamachuco -> Trujillo`: 8
- Otras rutas: 12

Formula:

```text
weight_cost = peso_kg * 2
volume_m3 = largo_cm * ancho_cm * alto_cm / 1000000
volume_cost = volume_m3 * 20
fragility_surcharge = BAJA 0, MEDIA 5, ALTA 10
subtotal = base_rate + weight_cost + volume_cost + fragility_surcharge
igv = subtotal * 0.18
total = subtotal + igv
```

Si `tipo_contenido` contiene `FRAGIL`, aplica al menos recargo `MEDIA`.

Reglas:

- No permite cotizar `ANULADA`.
- Si esta `REGISTRADA`, cambia a `COTIZADA`.
- Si esta `PRE_REGISTRADA`, calcula el monto pero no cambia estado.

## SUNAT

Endpoints mantenidos:

- `POST /api/v1/sunat/boletas/emitir-desde-encomienda`
- `GET /api/v1/sunat/boletas/mock/{serie}/{numero}/pdf`
- `POST /api/v1/sunat/boletas/beta/pdf-desde-encomienda`
- `POST /api/v1/sunat/boletas/beta/xml-desde-encomienda`

Reglas nuevas:

- No permite emitir boleta si la encomienda esta `ANULADA`.
- No permite emitir boleta si la encomienda esta `PRE_REGISTRADA`.
- No llama payments ni Yape.
- Se mantiene mock y beta con Lycet, incluyendo normalizacion de hash/CDR.

## Anulacion

Endpoint recomendado:

```text
POST /api/v1/encomiendas/{encomienda_id}/anular
```

Payload:

```json
{
  "motivo": "Error en datos del destinatario"
}
```

Reglas:

- 404 si no existe.
- 400 si ya esta `ANULADA`.
- 400 si esta `ENTREGADA`.
- Guarda `estado = ANULADA`, `motivo_anulacion` y `fecha_anulacion`.
- No borra fisicamente.
- No llama SUNAT, payments ni Yape.
- Devuelve `reversion_cobro = PENDIENTE_NO_INTEGRADO`.

`DELETE /api/v1/encomiendas/{encomienda_id}` se mantiene por compatibilidad y usa motivo generico.

## Edicion

`PUT /api/v1/encomiendas/{encomienda_id}` solo permite editar si la encomienda esta `PRE_REGISTRADA` o `REGISTRADA`.

No permite cambiar estado por `PUT`. Para cambios de estado se usan endpoints de negocio.

## Etiqueta QR

`GET /api/v1/encomiendas/{encomienda_id}/etiqueta` devuelve JSON con datos reales de PostgreSQL:

```json
{
  "codigo_encomienda": "D000000001",
  "origen": "Trujillo",
  "destino": "Angasmarca",
  "remitente": "Stefano Yepez Zapata",
  "destinatario": "Vania Ramos Cotrina",
  "qr_payload": {
    "codigo_encomienda": "D000000001",
    "origen": "Trujillo",
    "destino": "Angasmarca",
    "tracking": "/tracking/D000000001"
  }
}
```

`GET /api/v1/encomiendas/{encomienda_id}/etiqueta/qr` devuelve PNG.

`GET /api/v1/encomiendas/{encomienda_id}/etiqueta/pdf` devuelve PDF imprimible.

No genera etiqueta para encomiendas `ANULADA`.

Dependencias usadas:

- `qrcode`
- `Pillow`
- `reportlab`

## Entrega Con Firma

`POST /api/v1/encomiendas/{encomienda_id}/entregar`

Payload:

```json
{
  "dni_receptor": "87654321",
  "clave_seguridad": "ABC123",
  "firma_base64": "data:image/png;base64,..."
}
```

Reglas:

- 404 si no existe.
- 400 si esta `ANULADA`.
- 400 si ya esta `ENTREGADA`.
- Valida DNI contra `destinatario_numero_documento` si ese dato existe.
- Valida `clave_seguridad` solo si ya existe en la encomienda.
- Guarda `estado = ENTREGADA`, `fecha_entrega`, `dni_receptor_entrega` y `firma_digital_base64`.

Queda pendiente la generacion formal de clave de seguridad.

## SQL Manual Para PostgreSQL

Como `create_all` no agrega columnas a una tabla existente, ejecutar manualmente antes de probar sobre una BD ya creada:

```sql
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS tipo_contenido VARCHAR(50);
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS origen_registro VARCHAR(20);
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS motivo_anulacion TEXT;
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS fecha_anulacion TIMESTAMP WITH TIME ZONE;
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS fecha_entrega TIMESTAMP WITH TIME ZONE;
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS dni_receptor_entrega VARCHAR(20);
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS firma_digital_base64 TEXT;
ALTER TABLE encomiendas ADD COLUMN IF NOT EXISTS clave_seguridad VARCHAR(50);

UPDATE encomiendas
SET origen_registro = 'INTERNO'
WHERE origen_registro IS NULL;

UPDATE encomiendas
SET estado = 'REGISTRADA'
WHERE estado IS NULL;
```

No ejecutar SQL destructivo. No usar `DROP TABLE`.

## Validacion Manual En Swagger

Abrir:

```text
http://127.0.0.1:8000/docs
```

Flujo sugerido:

1. `GET /health`
2. `POST /api/v1/encomiendas/pre-registro`
3. `GET /api/v1/encomiendas/{id}`
4. `POST /api/v1/encomiendas/{id}/confirmar-registro`
5. `PUT /api/v1/encomiendas/{id}` en estado `REGISTRADA`
6. `POST /api/v1/cotizaciones/calcular`
7. Intentar `PUT` en estado `COTIZADA` y verificar 400
8. `POST /api/v1/encomiendas/{id}/anular`
9. Intentar cotizar anulada y verificar 400
10. Intentar emitir SUNAT anulada y verificar 400
11. Crear otra encomienda no anulada
12. `GET /api/v1/encomiendas/{id}/etiqueta`
13. `GET /api/v1/encomiendas/{id}/etiqueta/qr`
14. `GET /api/v1/encomiendas/{id}/etiqueta/pdf`
15. `POST /api/v1/encomiendas/{id}/entregar`
16. Verificar que RENIEC sigue respondiendo
17. Verificar que payments/Yape siguen intactos

## Verificacion En PostgreSQL

```sql
SELECT id, codigo_encomienda, estado, origen_registro, tipo_contenido,
       motivo_anulacion, fecha_anulacion, fecha_entrega, dni_receptor_entrega
FROM encomiendas
ORDER BY id DESC;
```

Confirmar:

- Pre-registro guarda `PRE_REGISTRADA`.
- Confirmar registro cambia a `REGISTRADA`.
- Cotizacion cambia a `COTIZADA` si estaba `REGISTRADA`.
- Anulacion guarda `ANULADA`, `motivo_anulacion` y `fecha_anulacion`.
- Entrega guarda `ENTREGADA`, `fecha_entrega`, `dni_receptor_entrega` y firma si se envio.

## Modulos Intactos

No se modificaron:

- `app/modules/reniec/`
- `app/modules/payments/`
- `app/modules/yape/`

SUNAT mock/beta se mantiene y solo se agregaron restricciones por estado.

## Validaciones de datos

Los formularios y endpoints de encomiendas aplican estas reglas:

- DNI: 8 digitos numericos cuando el tipo de documento es `DNI`.
- Telefono: 9 digitos numericos cuando se informa un celular.
- Correo: formato valido si el campo se informa.
- Peso y dimensiones: valores numericos mayores a 0.
- Fragilidad: solo `BAJA`, `MEDIA` o `ALTA`.
- Tipo de contenido: requerido en los formularios actuales y no debe enviarse vacio.

Estas validaciones son de entrada; no cambian estructura de base de datos ni requieren migraciones.
