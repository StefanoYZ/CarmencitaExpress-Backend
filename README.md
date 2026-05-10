
# CarmencitaExpress-Backend

Backend FastAPI para Carmencita Smart System. Este repositorio contiene solo el backend; el frontend vive en otra carpeta independiente y se conectara por HTTP usando endpoints REST y CORS.

## Flujo de prueba SUNAT Mock/Beta

### Variables .env

```env
APP_NAME=Carmencita Smart System
API_PREFIX=/api/v1
SUNAT_ENV=mock
SUNAT_PROVIDER=lycet
SUNAT_ALLOW_REAL_EMISSION=false
LYCET_API_URL=http://localhost:8001
LYCET_CLIENT_TOKEN=tu_token_aqui
```

### Endpoints minimos mock

1. `POST /api/v1/encomiendas`
2. `POST /api/v1/cotizaciones/calcular`
3. `POST /api/v1/sunat/boletas/emitir-desde-encomienda`
4. `GET /api/v1/sunat/boletas/mock/B001/000001/pdf`

El modo mock no tiene valor tributario, no llama a SUNAT, no llama a Lycet y no genera CDR real. El modo beta usa Lycet en `localhost:8001` con token por query param.

### Flujo beta con Lycet

1. Registrar encomienda.
2. Calcular cotizacion.
3. Generar PDF beta desde encomienda.
4. Generar XML beta desde encomienda.
5. Emitir beta desde encomienda.

FastAPI recibe solo `encomienda_id`, busca la encomienda, calcula la cotizacion, construye el payload tributario completo y llama internamente a Lycet. No llamar directamente a Lycet desde Postman usando `encomienda_id`.

### A. Crear encomienda

`POST /api/v1/encomiendas`

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

### B. Calcular cotizacion

`POST /api/v1/cotizaciones/calcular`

```json
{
  "encomienda_id": 1
}
```

### C. Emitir boleta mock

`POST /api/v1/sunat/boletas/emitir-desde-encomienda`

```json
{
  "encomienda_id": 1,
  "confirmar_pago": true
}
```

### D. Descargar PDF

`GET /api/v1/sunat/boletas/mock/B001/000001/pdf`

### E. Generar PDF beta desde encomienda

`POST /api/v1/sunat/boletas/beta/pdf-desde-encomienda`

```json
{
  "encomienda_id": 1,
  "confirmar_pago": true
}
```

### F. Generar XML beta desde encomienda

`POST /api/v1/sunat/boletas/beta/xml-desde-encomienda`

```json
{
  "encomienda_id": 1,
  "confirmar_pago": true
}
```

### G. Emitir beta desde encomienda

`POST /api/v1/sunat/boletas/emitir-desde-encomienda`

```json
{
  "encomienda_id": 1,
  "confirmar_pago": true
}
```

### H. Endpoints Lycet usados internamente

```text
POST http://localhost:8001/api/v1/invoice/pdf?token=123456
POST http://localhost:8001/api/v1/invoice/xml?token=123456
POST http://localhost:8001/api/v1/invoice/send?token=123456
```

Para beta, configurar `SUNAT_ENV=beta` y ejecutar Lycet aparte en `localhost:8001`. No usar datos reales de Carmencita ni credenciales reales para produccion.

# CarmencitaExpress-Backend

