from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import SessionLocal, create_db_tables
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.clients.router import router as clients_router
from app.modules.payments.router import router as payments_router
from app.modules.quotes.router import router as quotes_router
from app.modules.reniec.router import router as reniec_router
from app.modules.shipments.router import router as shipments_router
from app.modules.sunat.router import router as sunat_router
from app.modules.users.router import permissions_router, roles_router, users_router
from app.modules.users.service import seed_initial_access_control
from app.modules.yape.router import router as yape_router

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients_router, prefix=settings.api_prefix)
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


@app.on_event("startup")
def startup() -> None:
    create_db_tables()
    db = SessionLocal()
    try:
        seed_initial_access_control(db)
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Carmencita Express backend is running"}
