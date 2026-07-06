# Despliegue en DigitalOcean (Droplet unico)

Este directorio orquesta los 4 servicios de Carmencita Express Cargo en un solo
Droplet mediante Docker Compose, reemplazando Render (backend) + Netlify
(frontend) + Render (Lycet).

## Arquitectura de red

```
Internet
   │  :80 / :443
   ▼
┌─────────────────────────┐
│  frontend (nginx)       │  <- UNICO servicio expuesto al exterior
│  sirve el SPA (React)   │
│  reverse-proxy /api/v1  │──────┐
└─────────────────────────┘      │ red interna de Docker (sin puertos publicos)
                                  ▼
                        ┌───────────────────┐      ┌───────────────────┐
                        │  backend (FastAPI)│─────▶│  lycet_service    │
                        │  puerto 8000      │      │  (imagen ghcr.io) │
                        └───────────────────┘      │  puerto 8000      │
                                  │                 └───────────────────┘
                                  ▼
                        ┌───────────────────┐
                        │  postgres_db      │
                        │  puerto 5432      │
                        └───────────────────┘
```

**Por que solo el frontend esta expuesto:** nginx hace reverse proxy interno de
`/api/v1/*`, `/docs`, `/redoc`, `/openapi.json` y `/health` hacia `backend:8000`.
El navegador del cliente siempre habla con el mismo origen (el dominio del
Droplet), nunca cruza a otro dominio ni puerto. Esto elimina CORS como
dependencia critica en produccion (el `CORS_ORIGINS` del backend queda como
resguardo para accesos directos/debug) y reduce la superficie de ataque: solo
un puerto (80/443) recibe trafico de internet.

## Layout de directorios en el Droplet

```
/opt/carmencita/
├── deploy/
│   ├── docker-compose.yml     <- este archivo (viene del repo backend)
│   ├── .env                   <- secretos reales, NO se commitea
│   └── .env.example
├── CarmencitaExpress-Backend/ <- git clone del repo backend (se compila aqui)
└── Front-Carmencita/          <- git clone del repo frontend (se compila aqui)
```

`Lycet-Carmencita` **no se clona en el Droplet**. Su imagen se compila y se
publica en `ghcr.io` desde el propio CI del repo (runner de GitHub, con RAM de
sobra), y el Droplet solo hace `docker compose pull` — nunca corre
`composer install` ni compila PHP localmente. Backend y frontend si se compilan
en el Droplet porque cambian con más frecuencia; Lycet es estable (sin tests,
cambia poco) y es el servicio mas pesado de compilar (composer + wkhtmltopdf),
asi que sacar su build del Droplet es lo que mas RAM ahorra.

Los 3 repos son independientes en GitHub (`CarmencitaExpress-Backend`,
`Front-Carmencita`, `lycet-carmencita`). El `docker-compose.yml` referencia
backend/frontend como contextos de build relativos
(`../CarmencitaExpress-Backend`, `../Front-Carmencita/frontend`) y a Lycet como
`image: ghcr.io/stefanoyz/lycet-carmencita:${LYCET_IMAGE_TAG:-latest}`.

## Primer despliegue (una sola vez)

```bash
ssh root@TU_DROPLET_IP
curl -fsSL https://raw.githubusercontent.com/StefanoYZ/CarmencitaExpress-Backend/main/deploy/droplet-bootstrap.sh -o bootstrap.sh
bash bootstrap.sh
# Sigue las instrucciones que imprime el script: completar .env y autenticar
# Docker contra ghcr.io antes del primer "docker compose pull"
cd /opt/carmencita/deploy
docker compose pull lycet_service
docker compose up --build -d
```

`droplet-bootstrap.sh` instala Docker, crea un swap de 4GB (red de seguridad:
compilar backend+frontend en 2GB RAM sin swap puede quedarse sin memoria,
sobre todo el build de Vite/Rollup), configura el firewall (ufw: solo
22/80/443) y clona backend + frontend (Lycet no se clona, ver arriba).

### Autenticacion contra ghcr.io (paquete privado de Lycet)

El paquete `ghcr.io/stefanoyz/lycet-carmencita` es privado por defecto. El
Droplet necesita autenticarse **una sola vez** para poder hacer `pull`:

```bash
# Genera un Personal Access Token (classic) con scope "read:packages" en
# https://github.com/settings/tokens, luego en el Droplet:
echo 'TU_TOKEN' | docker login ghcr.io -u StefanoYZ --password-stdin
```

El login queda cacheado en `~/.docker/config.json`; no hay que repetirlo en
cada deploy. Alternativa mas simple (sin token): en GitHub, entra al paquete
`lycet-carmencita` (pestaña Packages) → **Package settings** → cambia la
visibilidad a **Public**. Con el paquete publico, el `docker compose pull` del
Droplet funciona sin ningun login.

## Despliegues siguientes (automatico via GitHub Actions)

**Backend y Frontend**: cada repo tiene su `.github/workflows/deploy.yml` que
se activa en push a `main`: corre las pruebas del repo y, si pasan, hace SSH al
Droplet, actualiza `deploy/.env` desde el secret `ENV_FILE`, hace `git pull` de
su propio codigo y reconstruye **solo su servicio**
(`docker compose up --build -d <servicio>`), nunca ambos a la vez.

**Lycet**: su workflow no compila nada en el Droplet. En el runner de GitHub
construye la imagen y la publica en `ghcr.io` con dos tags (`latest` y el SHA
corto del commit, para poder fijar una version especifica via
`LYCET_IMAGE_TAG` si un deploy sale mal). Luego hace SSH al Droplet y solo
corre `docker compose pull lycet_service && docker compose up -d --no-build
lycet_service`.

Secrets de GitHub necesarios:

| Secret | Repos | Valor |
|---|---|---|
| `DROPLET_HOST` | Backend, Frontend, Lycet | IP o dominio del Droplet |
| `DROPLET_USER` | Backend, Frontend, Lycet | usuario SSH de despliegue (con permiso sobre Docker) |
| `DROPLET_SSH_KEY` | Backend, Frontend, Lycet | clave privada SSH (formato PEM) |
| `ENV_FILE` | Backend, Frontend, Lycet | contenido completo de `deploy/.env` (multilinea) |

Lycet **no necesita** un secret de registry para el *push*: su workflow usa el
`GITHUB_TOKEN` automatico (con permiso `packages: write` declarado en el
propio workflow), que GitHub inyecta solo sin configuracion adicional.

## Certificado y logo de Lycet

`LYCET_CERTIFICATE_BASE64` y `LYCET_LOGO_BASE64` en `.env` reemplazan al
volumen de certificados en texto plano. El propio entrypoint de Lycet
reconstruye `data/cert.pem` (y `data/logo.png` si aplica) desde esas variables
en cada arranque del contenedor. Para generarlas:

```bash
base64 -w0 cert.pem > cert.b64.txt   # pega el contenido en LYCET_CERTIFICATE_BASE64
base64 -w0 logo.png > logo.b64.txt   # opcional, en LYCET_LOGO_BASE64
```

## HTTPS (siguiente paso recomendado)

Una vez el dominio apunte al Droplet, agrega Certbot (modo standalone o el
contenedor `certbot/certbot`) para emitir el certificado, monta
`/etc/letsencrypt` en el servicio `frontend` y agrega un `server` block en
`nginx.conf` escuchando en 443 con `ssl_certificate`/`ssl_certificate_key`.
Publica el puerto `443:443` en `docker-compose.yml`.

## Comandos utiles

```bash
# Ver logs de un servicio
docker compose -f /opt/carmencita/deploy/docker-compose.yml logs -f backend

# Reconstruir solo un servicio que se compila en el Droplet
docker compose -f /opt/carmencita/deploy/docker-compose.yml up --build -d backend

# Actualizar solo Lycet (pull de la imagen mas reciente de ghcr.io)
docker compose -f /opt/carmencita/deploy/docker-compose.yml pull lycet_service
docker compose -f /opt/carmencita/deploy/docker-compose.yml up -d --no-build lycet_service

# Rollback de Lycet a un commit especifico (SHA corto del build que fallo)
LYCET_IMAGE_TAG=a1b2c3d docker compose -f /opt/carmencita/deploy/docker-compose.yml up -d --no-build lycet_service

# Limpiar imagenes/contenedores huerfanos
docker compose -f /opt/carmencita/deploy/docker-compose.yml up -d --remove-orphans
docker image prune -f
```
