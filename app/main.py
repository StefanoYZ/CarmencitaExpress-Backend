from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import SessionLocal, create_db_tables
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.clients.router import router as clients_router
from app.modules.charge_logs.router import router as charge_logs_router
from app.modules.destinations.router import router as destinations_router
from app.modules.optimization_poc.router import router as optimization_poc_router
from app.modules.payments.router import router as payments_router
from app.modules.quotes.router import router as quotes_router
from app.modules.reniec.router import router as reniec_router
from app.modules.shipments.router import router as shipments_router
from app.modules.sunat.router import router as sunat_router
from app.modules.users.router import permissions_router, roles_router, users_router
from app.modules.users.service import seed_initial_access_control
from app.modules.destinations.service import seed_default_destinations
from app.modules.asistente.router import (
    asistente_router,
    base_conocimiento_router,
    logs_asistente_router,
    tipos_contenido_router,
)
from app.modules.measurement_logs.router import boletas_router as measurement_boletas_router
from app.modules.measurement_logs.router import carga_router as measurement_carga_router
from app.modules.measurement_logs.router import servicio_router as measurement_servicio_router
from app.modules.yape.router import router as yape_router

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # En produccion (Droplet), nginx expone frontend y backend bajo el mismo
    # origen via reverse proxy (ver deploy/docker-compose.yml + nginx.conf), asi
    # que el navegador no hace peticiones cross-origin. Este regex solo cubre
    # desarrollo local (Vite en localhost) y accesos directos al backend sin proxy.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients_router, prefix=settings.api_prefix)
app.include_router(charge_logs_router, prefix=settings.api_prefix)
app.include_router(destinations_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(users_router, prefix=settings.api_prefix)
app.include_router(roles_router, prefix=settings.api_prefix)
app.include_router(permissions_router, prefix=settings.api_prefix)
app.include_router(shipments_router, prefix=settings.api_prefix)
app.include_router(quotes_router, prefix=settings.api_prefix)
app.include_router(sunat_router, prefix=settings.api_prefix)
app.include_router(reniec_router, prefix=settings.api_prefix)
app.include_router(payments_router, prefix=settings.api_prefix)
app.include_router(yape_router, prefix=settings.api_prefix)
app.include_router(optimization_poc_router, prefix=settings.api_prefix)
app.include_router(measurement_boletas_router, prefix=settings.api_prefix)
app.include_router(measurement_servicio_router, prefix=settings.api_prefix)
app.include_router(measurement_carga_router, prefix=settings.api_prefix)
app.include_router(asistente_router, prefix=settings.api_prefix)
app.include_router(logs_asistente_router, prefix=settings.api_prefix)
app.include_router(base_conocimiento_router, prefix=settings.api_prefix)
app.include_router(tipos_contenido_router, prefix=settings.api_prefix)


@app.on_event("startup")
def startup() -> None:
    create_db_tables()
    db = SessionLocal()
    try:
        seed_initial_access_control(db)
        seed_default_destinations(db)
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Carmencita Express backend is running"}
