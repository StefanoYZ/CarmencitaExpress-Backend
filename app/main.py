from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
# Importaciones tuyas
from app.modules.clientes.router import router as clientes_router
from app.modules.cotizacion.router import router as cotizacion_router
from app.modules.encomiendas.router import router as encomiendas_router
from app.modules.sunat.router import router as sunat_router
# Importaciones de ella
from app.modules.reniec.router import router as reniec_router
from app.modules.payments.router import router as payments_router
from app.modules.yape.router import router as yape_router

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    # Recomiendo dejar localhost para seguridad, o "*" si están en pruebas rápidas
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registramos TODOS los routers
app.include_router(clientes_router, prefix=settings.api_prefix)
app.include_router(encomiendas_router, prefix=settings.api_prefix)
app.include_router(cotizacion_router, prefix=settings.api_prefix)
app.include_router(sunat_router, prefix=settings.api_prefix)
app.include_router(reniec_router, prefix=settings.api_prefix)
app.include_router(payments_router, prefix=settings.api_prefix)
app.include_router(yape_router, prefix=settings.api_prefix)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}

@app.get("/")
def root():
    return {"message": "Backend de Carmencita Express funcionando"}
