"""Bootstrap de la base de datos para pruebas E2E (full-stack).

Crea/normaliza una BD PostgreSQL dedicada `carmencita_e2e` (aislada de la de
desarrollo), aplica el esquema y siembra los datos base + usuarios de prueba
(admin/secretaria/estiba). Idempotente: se puede correr antes de cada suite E2E.

Uso:
    .venv/Scripts/python -m scripts.e2e_seed

Variables (opcionales):
    E2E_DB_NAME   nombre de la BD E2E (default: carmencita_e2e)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

# Credenciales base del .env de desarrollo (para derivar la URL E2E).
load_dotenv()

E2E_DB_NAME = os.environ.get("E2E_DB_NAME", "carmencita_e2e")
E2E_ADMIN_USER = "admin"
E2E_ADMIN_PASSWORD = "Admin12345"
E2E_PASSWORD = "QaPassword123"


def _swap_database(url: str, db_name: str) -> str:
    head, _, _tail = url.rpartition("/")
    return f"{head}/{db_name}"


def _raw_dsn(url: str) -> str:
    # psycopg2.connect no acepta el sufijo "+psycopg2".
    return url.replace("postgresql+psycopg2://", "postgresql://").replace("postgres://", "postgresql://")


def _ensure_database(base_url: str) -> str:
    import psycopg2
    from psycopg2 import sql

    e2e_url = _swap_database(base_url, E2E_DB_NAME)
    maintenance_url = _raw_dsn(_swap_database(base_url, "postgres"))

    conn = psycopg2.connect(maintenance_url)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (E2E_DB_NAME,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(E2E_DB_NAME)))
                print(f"[e2e] Base de datos creada: {E2E_DB_NAME}")
            else:
                print(f"[e2e] Base de datos ya existe: {E2E_DB_NAME}")
    finally:
        conn.close()
    return e2e_url


def _seed() -> None:
    # Import diferido: la app crea el engine al importarse, así que las variables
    # de entorno deben quedar fijadas ANTES de importar app.core.*.
    from app.core.database import SessionLocal, create_db_tables
    from app.modules.destinations.service import seed_default_destinations
    from app.modules.users import repository as users_repository
    from app.modules.users.schema import UserCreate
    from app.modules.users.service import (
        assign_role_to_user,
        create_user,
        seed_initial_access_control,
    )

    create_db_tables()
    db = SessionLocal()
    try:
        seed_initial_access_control(db)
        seed_default_destinations(db)
        for username, role_name in (("qa_secretaria", "SECRETARIA"), ("qa_estiba", "ESTIBA")):
            if users_repository.get_user_by_username(db, username) is not None:
                continue
            user = create_user(
                db,
                UserCreate(username=username, password=E2E_PASSWORD, full_name=f"E2E {role_name}"),
            )
            role = users_repository.get_role_by_name(db, role_name)
            assign_role_to_user(db, user.id, role.id)
            print(f"[e2e] Usuario sembrado: {username} ({role_name})")
    finally:
        db.close()


def bootstrap() -> str:
    """Asegura la BD E2E, fija el entorno E2E y siembra los datos. Devuelve la URL E2E."""
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        raise SystemExit("DATABASE_URL no está definida (revisa el .env).")

    e2e_url = _ensure_database(base_url)

    # Fijar el entorno E2E antes de importar la app.
    os.environ["DATABASE_URL"] = e2e_url
    os.environ["SUNAT_ENV"] = "mock"
    os.environ["ASSISTANT_LLM_ENABLED"] = "false"
    os.environ["DEFAULT_ADMIN_USERNAME"] = E2E_ADMIN_USER
    os.environ["DEFAULT_ADMIN_PASSWORD"] = E2E_ADMIN_PASSWORD

    _seed()
    return e2e_url


def main() -> None:
    e2e_url = bootstrap()
    print(f"[e2e] Seed completo -> {e2e_url}")
    print(f"[e2e] admin={E2E_ADMIN_USER}/{E2E_ADMIN_PASSWORD} · qa_secretaria/qa_estiba={E2E_PASSWORD}")


if __name__ == "__main__":
    main()
