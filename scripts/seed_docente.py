"""Crea/actualiza los usuarios de evaluacion asincrona.

- Ejecuta seed_initial_access_control (asegura roles/permisos y QUITA developer.*
  del rol ADMINISTRADOR).
- Crea los usuarios del docente: administrador (sin developer), secretaria y
  estibador. Ademas deja un usuario DEVELOPER aparte para el equipo (no se entrega
  al docente).
- Idempotente: si el usuario ya existe, resetea su contraseña y garantiza el rol.

Uso (desde la raiz del backend, con el venv):
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_docente.py
"""
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.modules.users import repository, service
from app.modules.users.schema import UserCreate
from app.modules.users.service import seed_initial_access_control

# (username, password, full_name, rol)
USERS = [
    ("docente_admin",      "Docente2025", "Docente Administrador", "ADMINISTRADOR"),
    ("docente_secretaria", "Docente2025", "Docente Secretaria",    "SECRETARIA"),
    ("docente_estiba",     "Docente2025", "Docente Estibador",     "ESTIBA"),
    # Usuario del EQUIPO para la vista Developer (NO se entrega al docente):
    ("dev_equipo",         "Equipo2025",  "Desarrollador del equipo", "DEVELOPER"),
]


def ensure_user(db, username, password, full_name, role_name):
    username = username.strip().lower()
    role = repository.get_role_by_name(db, role_name)
    if role is None:
        raise SystemExit(f"El rol {role_name} no existe. Levanta el backend una vez para sembrarlo.")

    user = repository.get_user_by_username(db, username)
    if user is None:
        response = service.create_user(
            db, UserCreate(username=username, password=password, full_name=full_name)
        )
        user_id = response.id
        action = "creado"
    else:
        user.password_hash = hash_password(password)
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
        action = "actualizado (password reseteada)"

    try:
        service.assign_role_to_user(db, user_id, role.id)
    except ValueError:
        pass  # el usuario ya tenia asignado ese rol

    print(f"{action}: {username} -> {role_name}", flush=True)


def main():
    db = SessionLocal()
    try:
        seed_initial_access_control(db)
        print("Roles/permisos sincronizados (developer.* retirado de ADMINISTRADOR).", flush=True)
        for user in USERS:
            ensure_user(db, *user)
    finally:
        db.close()


if __name__ == "__main__":
    main()
