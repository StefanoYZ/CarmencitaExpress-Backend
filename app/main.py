from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.modules.reniec.router import router as reniec_router
from app.modules.payments.router import router as payments_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reniec_router)
app.include_router(payments_router)

@app.get("/")
def root():
    return {"message": "Backend funcionando"}