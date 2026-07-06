"""Lanza el backend para pruebas E2E (full-stack).

Asegura/siembra la BD E2E dedicada (`carmencita_e2e`), fija el entorno de prueba
(SUNAT mock, LLM off) y arranca uvicorn en 127.0.0.1:8000. Pensado para que
Playwright lo levante como webServer.

Uso:
    .venv/Scripts/python -m scripts.e2e_backend
"""
from __future__ import annotations

from scripts.e2e_seed import bootstrap


def main() -> None:
    bootstrap()  # fija DATABASE_URL/entorno E2E e importa la app ya ligada a la BD E2E

    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
