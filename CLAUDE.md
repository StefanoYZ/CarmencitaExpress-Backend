# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repositories

This project is split across two repos:
- **Backend** (`CarmencitaExpress/`) — FastAPI + PostgreSQL
- **Frontend** (`Front-Carmencita/frontend/`) — React 18 + Vite + Tailwind CSS

---

## Backend

### Run commands

```bash
# Start dev server (from CarmencitaExpress/)
uvicorn app.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/path/to/test_file.py

# Run with coverage
pytest --cov=app
```

API docs available at `http://127.0.0.1:8000/docs` when running.

### Architecture

- `app/main.py` — FastAPI app, CORS middleware, router registration, startup hooks
- `app/core/config.py` — `Settings` via pydantic-settings (reads `.env`); normalizes `postgres://` → `postgresql+psycopg2://`
- `app/core/database.py` — SQLAlchemy engine/session, `create_db_tables()`, `sync_development_schema()`
- `app/core/dependencies.py` — `get_current_user()`, `require_permission(code)`, `require_role(name)`
- `app/core/security.py` — JWT HS256 encode/decode, PBKDF2-SHA256 password hashing
- `app/core/business_time.py` — `business_now()` returns current time in `America/Lima`

All API routes are prefixed with `/api/v1`.

### Module pattern

Every domain module lives in `app/modules/<name>/` with these files:
- `model.py` — SQLAlchemy ORM model (adds to `Base.metadata`)
- `schema.py` — Pydantic v2 schemas for request/response
- `service.py` — Business logic, calls repository
- `router.py` — FastAPI router, declares endpoints, uses `require_permission`/`require_role` dependencies
- `repository.py` — DB queries (receives `Session`)

### Database

- **No Alembic.** Tables are created/updated on startup via:
  1. `Base.metadata.create_all()` — creates missing tables
  2. `sync_development_schema()` — adds missing columns to existing tables using raw `ALTER TABLE`
- **Never add Alembic migrations.** Follow the existing pattern instead.
- `seed_initial_access_control(db)` seeds roles, permissions, role-permission assignments, and the default admin user (idempotent).
- `seed_default_destinations(db)` seeds route destinations (idempotent).

### Auth & roles

Three built-in roles: `ADMINISTRADOR`, `SECRETARIA`, `ESTIBA`.

Authorization is permission-based, not role-based in code:
- `require_permission("encomiendas.write")` — checks the decoded JWT user's permission codes
- `require_role("SECRETARIA")` — role check (use sparingly; prefer permissions)
- ADMINISTRADOR bypasses all permission checks in `hasAnyPermission` on the frontend

Public endpoints (no auth): `GET /`, `GET /health`, `POST /api/v1/auth/login`, `POST /api/v1/encomiendas/pre-registro`, `GET /api/v1/encomiendas/codigo/{codigo}`, `GET /api/v1/reniec/{dni}`

### Business logic

**Tariff formula:**
```
price = base_rate(route) + peso_kg×2 + volume_m3×20 + fragility_surcharge
fragility_surcharge: BAJA=0, MEDIA=5, ALTA=10
price_with_igv = price × 1.18
```

**Package state machine:** `PRE_REGISTRADA → REGISTRADA → PAGO_CONFIRMADO → EN_TRANSITO → ENTREGADA` (also `ANULADA`)

**SUNAT environments:** `SUNAT_ENV=mock|beta|production` in `.env` controls whether boleta emission hits a real API.

### Key env vars (see `.env.example`)

```
DATABASE_URL
SECRET_KEY
SUNAT_ENV
LYCET_API_URL
RENIEC_API_URL
MERCADOPAGO_ACCESS_TOKEN
```

### Measurement logs module

`app/modules/measurement_logs/` records two types of performance logs:
- `logs_emision_boleta` — timing for boleta emission; FK to `encomiendas` and `boletas_electronicas`
- `logs_servicio_transporte` — timing for registro/carga/entrega phases; FK to `encomiendas`

---

## Frontend

### Run commands

```bash
# From Front-Carmencita/frontend/
npm run dev        # dev server
npm run build      # production build
npm run lint       # ESLint
npm run test       # Vitest (run once)
npm run test:watch # Vitest watch mode
npm run test:e2e   # Playwright
```

### Architecture

- `src/main.jsx` — React root, wraps in `<AuthProvider>` + `<BrowserRouter>`
- `src/routes/AppRoutes.jsx` — all route definitions; uses `ProtectedRoute` with role/permission guards
- `src/auth/` — `AuthContext.jsx` (JWT state), `accessControl.js` (role/permission helpers)
- `src/services/apiClient.js` — Axios instance; injects `Authorization: Bearer <token>`; dispatches `carmencita:auth-expired` custom event on 401
- `src/services/` — one file per domain (`encomiendasService.js`, `sunatService.js`, etc.)

API base URL is read from `VITE_API_BASE_URL` env var (defaults to `/api/v1`).

### Key pages

| Route | Component | Role required |
|---|---|---|
| `/secretaria` | `SecretariaDashboard` | SECRETARIA |
| `/admin/*` | Admin pages | ADMINISTRADOR |
| `/admin/optimizacion-carga` | `OptimizacionCarga` | ESTIBA |
| `/registrar-envio`, `/cotizar`, `/tracking` | Public pages | none |

### Shared success component

`src/pages/public/RegistroExitosoPage.jsx` exports `RegistroExitosoContent` which accepts:
- `homePath` / `homeLabel` — for `<Link>`-based navigation
- `onHome` — callback for state-reset navigation (renders a `<button>` instead of `<Link>`)

Use `onHome` when the success screen is embedded inside a dashboard and "Volver" should reset local state rather than navigate.
