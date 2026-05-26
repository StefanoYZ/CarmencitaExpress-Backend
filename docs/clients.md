# Clientes locales

## Objetivo

La tabla `clientes` guarda datos recurrentes de personas identificadas por DNI para reutilizar nombre, telefono, correo y direccion en futuros registros de encomiendas.

Esta tabla no reemplaza a RENIEC. RENIEC sigue siendo la fuente externa para obtener nombres por DNI cuando el cliente no existe localmente o cuando el frontend decida consultarlo.

## Diferencia entre RENIEC y clientes locales

- `GET /api/v1/reniec/{dni}` consulta el servicio RENIEC existente.
- `GET /api/v1/clientes/{dni}` consulta solo PostgreSQL en la tabla `clientes`.
- Los datos de telefono, correo y direccion se guardan localmente porque RENIEC no necesariamente los devuelve.

## Escenarios

Cliente nuevo:

1. El usuario ingresa DNI y nombre, manualmente o con apoyo de RENIEC.
2. El usuario puede ingresar telefono, correo y direccion.
3. Al crear pre-registro o registro presencial, el backend crea la fila en `clientes`.

Cliente recurrente:

1. El frontend puede consultar `GET /api/v1/clientes/{dni}`.
2. Si existe, devuelve los datos guardados para autocompletar.
3. Si no existe, responde 404 con `Cliente no encontrado en base local.`

Cliente con datos actualizados:

1. Si el DNI ya existe, el backend actualiza nombre, telefono, correo o direccion cuando llegan valores nuevos validos.
2. Si un campo llega `null` o vacio, no borra el valor existente.
3. `updated_at` se actualiza cuando hay cambios.

## Endpoints

- `GET /api/v1/clientes`: lista clientes locales.
- `GET /api/v1/clientes/{dni}`: obtiene un cliente local por DNI.
- `POST /api/v1/clientes`: crea o actualiza un cliente por DNI.
- `PUT /api/v1/clientes/{dni}`: actualiza datos del cliente sin cambiar DNI.

Tag en Swagger: `Clientes`.

## Integracion con encomiendas

Pre-registro:

- `POST /api/v1/encomiendas/pre-registro` hace upsert del remitente y destinatario antes de crear la encomienda.
- La encomienda conserva su estado `PRE_REGISTRADA`.

Registro presencial:

- `POST /api/v1/encomiendas` hace upsert del remitente y destinatario antes de crear la encomienda.
- La encomienda conserva su estado `REGISTRADA`.

Edicion:

- `PUT /api/v1/encomiendas/{id}` hace upsert cuando se editan datos personales.
- Respeta las reglas actuales de edicion por estado.
- La tabla `encomiendas` conserva la foto historica del envio.

## Validaciones

- DNI: exactamente 8 digitos numericos.
- Telefono: opcional, exactamente 9 digitos si llega.
- Correo: opcional, formato valido si llega.
- Nombre completo: obligatorio al crear o hacer upsert.
- Direccion: opcional.

## SQL manual

Ejecutar el script:

`docs/sql/clients_patch.sql`

No se uso Alembic en este cambio.

## Pruebas en Swagger

1. `GET /api/v1/clientes/76619947` debe responder 404 si no existe.
2. `POST /api/v1/clientes`:

```json
{
  "dni": "76619947",
  "nombre_completo": "Stefano Yepez Zapata",
  "telefono": "999999999",
  "correo": "stefano@test.com",
  "direccion": "Trujillo"
}
```

3. `GET /api/v1/clientes/76619947` debe devolver los datos guardados.
4. `PUT /api/v1/clientes/76619947`:

```json
{
  "telefono": "988888888",
  "correo": "nuevo@test.com",
  "direccion": "Nueva direccion"
}
```

5. Crear un pre-registro y verificar que remitente y destinatario aparecen en `clientes`.
6. Crear un registro presencial y verificar el mismo comportamiento.
7. Enviar correo vacio en un segundo registro y confirmar que no borra el correo anterior.

## Verificacion en PostgreSQL

```sql
SELECT dni, nombre_completo, telefono, correo, direccion, created_at, updated_at
FROM clientes
ORDER BY updated_at DESC;
```

## Notas

- No se modifico funcionalmente `app/modules/reniec/`.
- No se modifico `app/modules/payments/`.
- No se modifico `app/modules/yape/`.
- No se modifico SUNAT.
- No se agregaron migraciones Alembic.
