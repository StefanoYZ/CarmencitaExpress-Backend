# Carmencita Express

## Contexto de trabajo

Antes de editar código en la estación principal, leer
`C:\Users\angel\Desktop\PROYECTOS PERSONALES\Mente 2.0\Proyectos\CarmencitaExpress\handoff.md`.

- La zona volátil indica la tarea activa, bloqueos y siguiente paso; la zona estable contiene decisiones y restricciones vigentes.
- Confirmar siempre el estado real de los repositorios antes de asumir que el handoff está actualizado.
- Al cerrar una sesión relevante, actualizar la zona volátil y la bitácora diaria del vault.
- No guardar secretos, tokens, credenciales, certificados privados ni datos personales reales en Git, documentos o capturas.
- `docs/` contiene documentación local de trabajo y está excluido de Git. No volver a versionarlo.

## Repositorios y despliegue

El sistema está dividido en tres repositorios hermanos:

- Backend: `C:\Users\angel\Desktop\CarmencitaExpress` (FastAPI y PostgreSQL).
- Frontend: `C:\Users\angel\Desktop\Front-Carmencita\frontend` (React, Vite y Tailwind CSS).
- Lycet: `C:\Users\angel\Desktop\Lycet-Carmencita` (adaptador PHP de Greenter para SUNAT).

El despliegue soportado usa un Droplet de DigitalOcean y
`deploy/docker-compose.yml`. Los clones del backend y frontend quedan como
hermanos de `deploy/`; Lycet se consume como imagen de GHCR. La carpeta local
ignorada `external/` no es una fuente del despliegue.

Los workflows despliegan únicamente desde `main`. Una rama feature o un cambio
local no debe describirse como desplegado.

## Backend

### Comandos

Ejecutar desde la raíz del backend:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
python -m pytest -q
python -m pytest app/tests/test_shipments_flow.py -q
python -m pytest --cov=app
docker build .
docker compose -f deploy/docker-compose.yml config --quiet
```

`pytest.ini` descubre las pruebas Python en `app/tests`; `tests/carga` contiene
los recursos de JMeter. La documentación OpenAPI se sirve en `/docs` con assets
locales.

### Arquitectura

- `app/main.py`: aplicación FastAPI, CORS, Swagger, routers y arranque.
- `app/core/config.py`: configuración con Pydantic Settings y normalización de URLs PostgreSQL.
- `app/core/database.py`: engine, sesiones, creación de tablas y sincronización aditiva.
- `app/core/dependencies.py`: usuario activo, permisos y roles.
- `app/core/security.py`: JWT HS256 y contraseñas PBKDF2-SHA256.
- `app/core/business_time.py`: hora de negocio en `America/Lima`.
- `app/modules/`: módulos de dominio.
- `app/integrations/`: adaptadores de LLM y búsqueda web.

El patrón preferido es `router -> service -> repository`, acompañado por
modelos SQLAlchemy y esquemas Pydantic cuando corresponda. No todos los módulos
necesitan todas las capas; no crear wrappers vacíos para forzar el patrón.

Los nombres internos son principalmente en inglés. Las rutas, aliases y
respuestas públicas conservan los términos de negocio en español.

### Base de datos

No hay Alembic. En el arranque se ejecutan `Base.metadata.create_all()` y
`sync_development_schema()`. Esta sincronización solo cubre cambios aditivos
específicos; no migra de forma segura tipos, nombres, restricciones, índices,
claves foráneas, nulabilidad ni eliminaciones.

- No introducir Alembic ni otro mecanismo de migraciones sin una decisión arquitectónica explícita.
- Para cambios no aditivos, respaldar los datos y diseñar una migración revisada.
- El arranque siembra roles, permisos, administrador inicial y destinos de forma idempotente.
- Los scripts de respaldo y restauración son `scripts/backup_bd.py` y `scripts/restore_bd.py`.

### Autenticación y autorización

Los roles base son `ADMINISTRADOR`, `SECRETARIA`, `ESTIBA` y `DEVELOPER`.
Usar las dependencias backend de rol o permiso según el caso; una protección de
ruta en React nunca sustituye la autorización de la API.

- `ADMINISTRADOR` no tiene un bypass universal de permisos en el backend.
- Optimización requiere el rol `ESTIBA` y el permiso correspondiente.
- Developer requiere `developer.read`; las mutaciones también requieren `developer.write`.
- La cobertura de autorización del resto de endpoints está incompleta. Verificar cada router antes de asumir que está protegido.

### Reglas de negocio relevantes

- El pre-registro crea una encomienda `PRE_REGISTRADA`/`EXTERNO`; el registro directo crea `REGISTRADA`/`INTERNO`.
- Los estados declarados son `PRE_REGISTRADA`, `REGISTRADA`, `COTIZADA`, `PAGO_CONFIRMADO`, `BOLETA_EMITIDA`, `EN_TRANSITO`, `EN_DESTINO`, `ENTREGADA` y `ANULADA`.
- No existe todavía una máquina lineal persistente para todos esos estados. Revisar escritores y validaciones antes de documentar una transición como implementada.
- Pagos y Yape registran resultados, pero no persisten actualmente una entidad de pago ni el estado de pago de la encomienda.
- SUNAT funciona en mock y beta; la emisión de producción permanece bloqueada.
- La cotización usa la heurística `reported-patterns-v1`, no la fórmula tarifaria simple histórica.
- La lógica de cotización pública está reflejada también en `frontend/src/utils/publicShipment.js`; cualquier cambio debe coordinarse y probarse en ambos repositorios.

## Frontend

### Comandos

Ejecutar desde `C:\Users\angel\Desktop\Front-Carmencita\frontend`:

```powershell
npm ci
npm run dev
npm run build
npm run preview
npm run lint
npm run test
npm run test:watch
npm run test:coverage
npm run test:e2e
```

El proyecto declara Node 20. Playwright levanta el backend hermano y utiliza una
base PostgreSQL E2E dedicada.

### Arquitectura y acceso

- `src/main.jsx` monta `BrowserRouter`; `src/App.jsx` monta `AuthProvider`, configuración visual y rutas.
- `src/routes/AppRoutes.jsx` centraliza las rutas y sus guards.
- `src/context/` contiene el contexto de autenticación; `src/auth/` contiene helpers de sesión y acceso.
- `src/services/apiClient.js` adjunta el JWT y emite `carmencita:auth-expired` ante HTTP 401.
- `src/services/` agrupa adaptadores por dominio sin imponer un archivo por módulo.
- El JWT y usuario se guardan en `sessionStorage`.
- `VITE_API_BASE_URL` usa `/api/v1` como fallback y `VITE_API_TIMEOUT_MS` controla el timeout.

Rutas públicas principales: `/`, `/login`, `/registrar-envio`, `/cotizar` y
`/tracking`. `/secretaria`, `/admin/developer` y
`/admin/optimizacion-carga` tienen guards específicos. Las rutas administrativas
usan guards anidados; comprobar el acceso efectivo completo antes de cambiar un
rol o permiso.

`RegistroExitosoContent` es el componente compartido de éxito. Usar `onHome`
cuando la vista esté embebida y deba reiniciar estado; usar `homePath` para
navegación mediante enlace.

## Configuración y seguridad

- No leer, imprimir ni confirmar archivos `.env` reales.
- `.env` del backend, `.env` del frontend y `deploy/.env` tienen alcances distintos; no fusionarlos.
- Los certificados y logos de Lycet viven en su repositorio local bajo `data/`, que está ignorado. No duplicarlos dentro del backend.
- El stack publica únicamente Nginx; PostgreSQL, FastAPI y Lycet permanecen en la red interna de Compose.
- El despliegue actual publica HTTP. No afirmar que HTTPS está habilitado hasta verificar puerto 443 y certificados.
- `/health` no comprueba todavía PostgreSQL ni Lycet.
- Mantener cambios pequeños y verificar backend y frontend cuando una regla esté duplicada entre ambos.
