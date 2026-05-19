# Auth, Roles Y Permisos Internos

Este documento describe la implementacion backend de usuarios internos, roles dinamicos y permisos dinamicos para Carmencita Smart System / Carmencita Express Cargo.

No se uso Alembic. No se implemento DigitalOcean. No se implemento acomodo de paquetes. No se documento Postman.

## Arquitectura Por Capas

La implementacion nueva queda organizada asi:

- Presentacion: `app/modules/auth/router.py` y `app/modules/users/router.py`
- Servicios: `app/modules/auth/service.py` y `app/modules/users/service.py`
- Acceso a datos: `app/modules/users/repository.py`
- Seguridad: `app/core/security.py` y `app/core/dependencies.py`

Los roles y permisos son registros de PostgreSQL. No se usa logica `if role == "SECRETARIA"` para autorizar acciones.

## Modulos Tocados

- `app/core/config.py`
- `app/core/database.py`
- `app/core/dependencies.py`
- `app/core/security.py`
- `app/main.py`
- `app/modules/auth/`
- `app/modules/users/`
- `.env.example`

No se modificaron funcionalmente:

- `app/modules/reniec/`
- `app/modules/payments/`
- `app/modules/yape/`

Los endpoints de encomiendas, cotizaciones y SUNAT se dejaron publicos por compatibilidad con el frontend actual. La dependencia `require_permission(...)` ya esta lista para protegerlos progresivamente.

## Tablas Nuevas

- `internal_users`
- `roles`
- `permissions`
- `user_roles`
- `role_permissions`

## Variables Nuevas

Se agregaron solo a `.env.example`:

```env
SECRET_KEY=change_me
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_EMAIL=admin@carmencita.com
DEFAULT_ADMIN_PASSWORD=admin123
```

Cambiar `SECRET_KEY` y `DEFAULT_ADMIN_PASSWORD` antes de usar fuera de desarrollo.

## Roles Base

El seed idempotente crea:

- `ADMINISTRADOR`
- `SECRETARIA`
- `ESTIBA`

El sistema permite crear mas roles desde PostgreSQL o desde los endpoints protegidos.

## Permisos Base

Encomiendas:

- `encomiendas.read`
- `encomiendas.write`
- `encomiendas.update`
- `encomiendas.cancel`
- `encomiendas.deliver`

Cotizaciones:

- `cotizaciones.calculate`
- `cotizaciones.read`

SUNAT:

- `sunat.emit`
- `sunat.read`
- `sunat.download_pdf`

Etiquetas:

- `etiquetas.generate`
- `etiquetas.read`

Tracking:

- `tracking.read`
- `tracking.update_status`

Usuarios:

- `users.read`
- `users.write`
- `users.update`
- `users.disable`

Roles:

- `roles.read`
- `roles.write`
- `roles.update`
- `roles.assign_permissions`

Permisos:

- `permissions.read`
- `permissions.write`

## Seed Inicial

En startup se ejecuta:

1. `create_all`
2. seed idempotente de permisos
3. seed idempotente de roles
4. asignacion de permisos base a roles
5. creacion opcional del admin inicial si no existe
6. asignacion de `ADMINISTRADOR` al admin inicial

Credenciales de desarrollo por defecto:

```text
username: admin
password: admin123
```

Debe cambiarse la contrasena.

## Login

Endpoint publico:

```text
POST /api/v1/auth/login
```

Payload:

```json
{
  "username": "admin",
  "password": "admin123"
}
```

`username` puede ser username o email.

Respuesta:

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@carmencita.com",
    "full_name": "Administrador del Sistema",
    "is_active": true,
    "roles": ["ADMINISTRADOR"],
    "permissions": ["users.read"]
  }
}
```

La contrasena se guarda con hash PBKDF2-SHA256. El token es JWT HS256.

## Uso En Swagger

Abrir:

```text
http://127.0.0.1:8000/docs
```

Flujo:

1. Ejecutar `POST /api/v1/auth/login`.
2. Copiar `access_token`.
3. Pulsar `Authorize`.
4. Pegar el token.
5. Probar endpoints protegidos.

Swagger/OpenAPI muestra seguridad Bearer en los endpoints protegidos.

## Endpoints Protegidos

Usuarios:

- `POST /api/v1/users` requiere `users.write`
- `GET /api/v1/users` requiere `users.read`
- `GET /api/v1/users/{user_id}` requiere `users.read`
- `PUT /api/v1/users/{user_id}` requiere `users.update`
- `DELETE /api/v1/users/{user_id}` requiere `users.disable`
- `POST /api/v1/users/{user_id}/roles/{role_id}` requiere `users.update`
- `DELETE /api/v1/users/{user_id}/roles/{role_id}` requiere `users.update`
- `GET /api/v1/users/{user_id}/roles` requiere `users.read`

Roles:

- `POST /api/v1/roles` requiere `roles.write`
- `GET /api/v1/roles` requiere `roles.read`
- `GET /api/v1/roles/{role_id}` requiere `roles.read`
- `PUT /api/v1/roles/{role_id}` requiere `roles.update`
- `DELETE /api/v1/roles/{role_id}` requiere `roles.update`
- `POST /api/v1/roles/{role_id}/permissions/{permission_id}` requiere `roles.assign_permissions`
- `DELETE /api/v1/roles/{role_id}/permissions/{permission_id}` requiere `roles.assign_permissions`
- `GET /api/v1/roles/{role_id}/permissions` requiere `roles.read`

Permisos:

- `GET /api/v1/permissions` requiere `permissions.read`
- `GET /api/v1/permissions/{permission_id}` requiere `permissions.read`
- `POST /api/v1/permissions` requiere `permissions.write`
- `PUT /api/v1/permissions/{permission_id}` requiere `permissions.write`

## Endpoints Publicos

- `GET /`
- `GET /health`
- `POST /api/v1/auth/login`
- `POST /api/v1/encomiendas/pre-registro`
- `GET /api/v1/encomiendas/codigo/{codigo_encomienda}`
- `GET /api/v1/reniec/{dni}`

Tambien quedan publicos temporalmente por compatibilidad:

- encomiendas internas existentes
- cotizaciones
- SUNAT mock/beta
- payments
- Yape

## Proteccion Progresiva Pendiente

Cuando el frontend ya envie token, se recomienda aplicar:

- `encomiendas.write` a `POST /api/v1/encomiendas`
- `encomiendas.update` a `PUT /api/v1/encomiendas/{id}`
- `encomiendas.cancel` a anulacion
- `encomiendas.deliver` a entrega
- `cotizaciones.calculate` a cotizacion
- `sunat.emit` a emision SUNAT
- `etiquetas.generate` a QR/PDF

No proteger el pre-registro externo ni tracking publico.

## Operaciones Comunes

Crear un nuevo rol:

```text
POST /api/v1/roles
```

Asignar permiso a rol:

```text
POST /api/v1/roles/{role_id}/permissions/{permission_id}
```

Asignar rol a usuario:

```text
POST /api/v1/users/{user_id}/roles/{role_id}
```

Desactivar usuario:

```text
DELETE /api/v1/users/{user_id}
```

El borrado es logico: `is_active = false`.

## SQL Manual De Revision

Si `create_all` no se ejecuta o se quiere revisar manualmente:

```sql
CREATE TABLE IF NOT EXISTS internal_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(120) UNIQUE NOT NULL,
    name VARCHAR(120) NOT NULL,
    description TEXT,
    module VARCHAR(80) NOT NULL,
    action VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES internal_users(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id),
    permission_id INTEGER NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (role_id, permission_id)
);
```

No ejecutar SQL destructivo. No borrar datos.

## Validacion En PostgreSQL

```sql
SELECT * FROM internal_users;
SELECT * FROM roles;
SELECT * FROM permissions;
SELECT * FROM user_roles;
SELECT * FROM role_permissions;
```

Confirmar:

- Los roles estan en BD.
- Los permisos estan en BD.
- El usuario interno tiene rol.
- El rol tiene permisos.
- La autorizacion se basa en permisos, no en roles quemados.

## Validacion Manual En Swagger

1. `GET /health`
2. Levantar app y verificar seed en base de datos
3. `POST /api/v1/auth/login`
4. Copiar token
5. Usar `Authorize`
6. `GET /api/v1/users`
7. `GET /api/v1/roles`
8. `GET /api/v1/permissions`
9. Crear usuario interno
10. Asignar rol a usuario
11. Crear rol nuevo
12. Asignar permisos al rol
13. Probar que un usuario sin permiso no accede a endpoint protegido
14. Probar que `ADMINISTRADOR` si accede
15. Confirmar que `GET /health` sigue publico
16. Confirmar que pre-registro externo sigue publico
17. Confirmar que RENIEC sigue funcionando
18. Confirmar que Payments sigue respondiendo
19. Confirmar que Yape sigue respondiendo
20. Confirmar que encomiendas, cotizaciones y SUNAT siguen funcionando
