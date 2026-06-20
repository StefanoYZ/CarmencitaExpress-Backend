# CarmencitaExpress Backend

Backend FastAPI para Carmencita Smart System. Este repositorio contiene solo el backend. El frontend vive en una carpeta independiente y se conecta por HTTP usando endpoints REST.

## Stack

- Python 3.11
- FastAPI
- Pydantic / pydantic-settings
- Almacenamiento temporal en memoria para flujos de desarrollo
- Lycet/Greenter para integracion SUNAT beta
- Mercado Pago / Yape para pagos
- RENIEC como API externa

PostgreSQL, autenticacion, Docker, Jenkins y Kubernetes no forman parte del alcance actual.

## Estructura De Modulos

Los nombres internos de carpetas estan en ingles:

- `app/modules/clients`
- `app/modules/shipments`
- `app/modules/quotes`
- `app/modules/sunat`
- `app/modules/reniec`
- `app/modules/payments`
- `app/modules/yape`
- `app/modules/optimization`

Las rutas publicas se mantienen en espanol por compatibilidad con Postman y el frontend:

- `/api/v1/clientes`
- `/api/v1/encomiendas`
- `/api/v1/cotizaciones`
- `/api/v1/sunat`

## Variables De Entorno

```env
APP_NAME=Carmencita Smart System
API_PREFIX=/api/v1
DATABASE_URL=postgresql+psycopg2://postgres:password@localhost:5432/carmencita_db
SUNAT_ENV=mock
SUNAT_PROVIDER=lycet
SUNAT_ALLOW_REAL_EMISSION=false
LYCET_API_URL=http://localhost:8001
LYCET_CLIENT_TOKEN=your_lycet_token

RENIEC_API_URL=https://api-reniec.example.com
RENIEC_API_TOKEN=your_reniec_token

MERCADOPAGO_PUBLIC_KEY=your_mercadopago_public_key
MERCADOPAGO_ACCESS_TOKEN=your_mercadopago_access_token
```

No subir al repositorio archivos `.env`, tokens reales, certificados ni credenciales de SUNAT/Lycet.

## Ejecucion Local

Crear la base de datos vacia en PostgreSQL:

```sql
CREATE DATABASE carmencita_db;
```

El backend crea automaticamente las tablas nuevas en desarrollo usando SQLAlchemy `create_all`. Los ajustes sobre bases existentes se documentan mediante scripts SQL idempotentes.

```powershell
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Si el puerto `8000` esta ocupado:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8002
```

URLs utiles:

- Health: `GET http://127.0.0.1:8000/health`
- Swagger docs: `http://127.0.0.1:8000/docs`

## Endpoints Principales

General:
- `GET /health`
- `GET /`

Clientes:
- `POST /api/v1/clientes`
- `GET /api/v1/clientes`
- `GET /api/v1/clientes/{cliente_id}`

Encomiendas:
- `POST /api/v1/encomiendas`
- `GET /api/v1/encomiendas`
- `GET /api/v1/encomiendas/{encomienda_id}`
- `GET /api/v1/encomiendas/codigo/{codigo_encomienda}`
- `PUT /api/v1/encomiendas/{encomienda_id}`
- `DELETE /api/v1/encomiendas/{encomienda_id}`

Cotizaciones:
- `POST /api/v1/cotizaciones/calcular`

SUNAT:
- `POST /api/v1/sunat/boletas/emitir-desde-encomienda`
- `GET /api/v1/sunat/boletas/mock/{serie}/{numero}/pdf`
- `POST /api/v1/sunat/boletas/beta/pdf-desde-encomienda`
- `POST /api/v1/sunat/boletas/beta/xml-desde-encomienda`

RENIEC:
- `GET /api/v1/reniec/{dni}`

Pagos:
- `GET /api/v1/payments/public-key`
- `POST /api/v1/payments/process-payment`
- `POST /api/v1/yape/process-payment`

## Flujo SUNAT Mock

Usar `SUNAT_ENV=mock`.

1. Registrar encomienda.
2. Calcular cotizacion.
3. Emitir boleta mock desde la encomienda.
4. Descargar PDF mock.

Crear encomienda:

```json
{
  "remitente_tipo_documento": "DNI",
  "remitente_numero_documento": "12345678",
  "remitente_nombre": "Juan Perez Lopez",
  "remitente_direccion": "Trujillo",
  "remitente_telefono": "999999999",
  "destinatario_tipo_documento": "DNI",
  "destinatario_numero_documento": "87654321",
  "destinatario_nombre": "Maria Lopez",
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

Calcular cotizacion:

```json
{
  "encomienda_id": 1
}
```

Emitir boleta mock:

```json
{
  "encomienda_id": 1,
  "confirmar_pago": true
}
```

Las boletas mock no tienen valor tributario. No llaman a SUNAT ni a Lycet.

## Flujo SUNAT Beta

Usar `SUNAT_ENV=beta` y levantar Lycet localmente en `http://localhost:8001`.

FastAPI recibe solo datos de negocio (`encomienda_id`), construye internamente el payload tributario completo y llama a Lycet usando token por query param.

Endpoints beta:

```text
POST /api/v1/sunat/boletas/beta/pdf-desde-encomienda
POST /api/v1/sunat/boletas/beta/xml-desde-encomienda
POST /api/v1/sunat/boletas/emitir-desde-encomienda
```

Body:

```json
{
  "encomienda_id": 1,
  "confirmar_pago": true
}
```

Endpoints Lycet usados internamente:

```text
POST http://localhost:8001/api/v1/invoice/pdf?token=123456
POST http://localhost:8001/api/v1/invoice/xml?token=123456
POST http://localhost:8001/api/v1/invoice/send?token=123456
```

La aceptacion beta de SUNAT puede aparecer como `cdrResponse.code = "0"`. Beta no equivale a emision tributaria de produccion.
