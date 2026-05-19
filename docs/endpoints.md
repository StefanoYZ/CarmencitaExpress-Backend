# Endpoints y Flujo De Desarrollo

Nota: la logica de negocio Sprint 1 para pre-registro, anulacion con motivo, tarifa por ruta, etiqueta QR y entrega base esta documentada en `docs/business-core.md`.

Nota: la autenticacion interna, roles dinamicos y permisos se documentan en `docs/auth-roles-permissions.md`.

## Base De Datos

El backend usa PostgreSQL mediante SQLAlchemy.

Variable requerida:

```env
DATABASE_URL=postgresql+psycopg2://postgres:password@localhost:5432/carmencita_db
```

En esta fase no se usa Alembic. Temporalmente, al iniciar FastAPI, se ejecuta:

```python
Base.metadata.create_all(bind=engine)
```

Esto crea automaticamente la tabla `encomiendas` en desarrollo. Cuando el modelo inicial este estable, se reemplazara por una migracion inicial con Alembic.

## Crear Base De Datos Vacia

En PostgreSQL:

```sql
CREATE DATABASE carmencita_db;
```

Luego configurar `DATABASE_URL` en `.env`.

## Levantar Backend

```powershell
cd C:\Users\angel\Desktop\CarmencitaExpress
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Encomiendas

Crear:

```text
POST /api/v1/encomiendas
```

Payload:

```json
{
  "remitente_tipo_documento": "DNI",
  "remitente_numero_documento": "76619947",
  "remitente_nombre": "Stefano Yepez Zapata",
  "remitente_direccion": "Trujillo",
  "remitente_telefono": "999999999",
  "destinatario_tipo_documento": "DNI",
  "destinatario_numero_documento": "87654321",
  "destinatario_nombre": "Vania Melissa Ramos Cotrina",
  "destinatario_direccion": "Angasmarca",
  "destinatario_telefono": "988888888",
  "origen": "Trujillo",
  "destino": "Angasmarca",
  "descripcion": "Caja mediana con documentos",
  "peso_kg": 3.5,
  "largo_cm": 40,
  "ancho_cm": 30,
  "alto_cm": 25,
  "fragilidad": "MEDIA"
}
```

El frontend no envia `codigo_encomienda`. El backend lo genera con formato:

```text
{letra_dia}{correlativo_9_digitos}
```

Ejemplo:

```text
D000000001
```

Consultar:

```text
GET /api/v1/encomiendas
GET /api/v1/encomiendas/{encomienda_id}
GET /api/v1/encomiendas/codigo/{codigo_encomienda}
```

Actualizar:

```text
PUT /api/v1/encomiendas/{encomienda_id}
```

Payload:

```json
{
  "remitente_tipo_documento": "DNI",
  "remitente_numero_documento": "76619947",
  "remitente_nombre": "Stefano Yepez Zapata Actualizado",
  "remitente_direccion": "Trujillo",
  "remitente_telefono": "999999999",
  "destinatario_tipo_documento": "DNI",
  "destinatario_numero_documento": "87654321",
  "destinatario_nombre": "Vania Melissa Ramos Cotrina",
  "destinatario_direccion": "Angasmarca",
  "destinatario_telefono": "988888888",
  "origen": "Trujillo",
  "destino": "Angasmarca",
  "descripcion": "Caja mediana actualizada",
  "peso_kg": 4.0,
  "largo_cm": 45,
  "ancho_cm": 30,
  "alto_cm": 25,
  "fragilidad": "MEDIA",
  "estado": "REGISTRADA"
}
```

`id` y `codigo_encomienda` no se aceptan como campos editables. El codigo original se mantiene.

Anular:

```text
DELETE /api/v1/encomiendas/{encomienda_id}
```

Respuesta:

```json
{
  "success": true,
  "message": "Encomienda anulada correctamente",
  "id": 1,
  "codigo_encomienda": "D000000001",
  "estado": "ANULADA"
}
```

El `DELETE` es una eliminacion logica: no borra la fila, solo cambia `estado` a `ANULADA`.

## Cotizacion

```text
POST /api/v1/cotizaciones/calcular
```

Payload:

```json
{
  "encomienda_id": 1
}
```

La cotizacion se calcula desde la encomienda persistida y marca la encomienda como `COTIZADA` si estaba `REGISTRADA`.

No se permite cotizar encomiendas con estado `ANULADA`.

## SUNAT Mock

```text
POST /api/v1/sunat/boletas/emitir-desde-encomienda
GET /api/v1/sunat/boletas/mock/{serie}/{numero}/pdf
```

Payload:

```json
{
  "encomienda_id": 1,
  "confirmar_pago": true
}
```

El modo mock no llama SUNAT ni Lycet y no tiene valor tributario.

No se permite emitir boleta para encomiendas con estado `ANULADA`.

## SUNAT Beta

Requiere:

```env
SUNAT_ENV=beta
LYCET_API_URL=http://localhost:8001
LYCET_CLIENT_TOKEN=...
```

Endpoints:

```text
POST /api/v1/sunat/boletas/emitir-desde-encomienda
POST /api/v1/sunat/boletas/beta/pdf-desde-encomienda
POST /api/v1/sunat/boletas/beta/xml-desde-encomienda
```

El backend construye internamente el payload tributario completo desde `encomienda_id`.

Si Lycet devuelve CDR, la respuesta normaliza:

- `hash`
- `cdr`
- `cdr_code`
- `cdr_description`
- `cdr_notes`

`cdr_code = "0"` indica aceptacion beta.

## Modulos No Modificados

En esta fase no se modifico la logica de:

- RENIEC
- Payments / Mercado Pago
- Yape
