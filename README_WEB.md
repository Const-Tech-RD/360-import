# 360 Import — Catálogo Web

App web para administrar el catálogo y generar el PDF.

## Requisitos

- Python 3.11+
- Playwright Chromium (`playwright install chromium`)

## Configuración local

```bash
cp .env.example .env
# Editar ADMIN_PASSWORD y SECRET_KEY

pip install -r requirements.txt
playwright install chromium

# Cargar catálogo actual (productos_final.csv + imágenes)
python scripts/seed_catalog.py

# Iniciar servidor
uvicorn web.main:app --reload --port 8000
```

Abrir http://localhost:8000 — login con `ADMIN_PASSWORD`.

## Docker

```bash
cp .env.example .env
docker compose build
docker compose run --rm catalog python scripts/seed_catalog.py
docker compose up
```

## Deploy en Fly.io (producción)

App en producción: **https://catalogo-360import.fly.dev**

### Primera vez

```bash
export PATH="$HOME/.fly/bin:$PATH"
fly auth login
fly apps create catalogo-360import   # si no existe
fly volumes create catalog_storage --size 3 --region gru -a catalogo-360import
fly secrets set ADMIN_PASSWORD="..." SECRET_KEY="$(openssl rand -hex 32)" -a catalogo-360import
fly deploy -a catalogo-360import
fly ssh console -a catalogo-360import -C "python scripts/seed_catalog.py"
```

Deploy desde la máquina local (incluye `extracted_images/` en la imagen; no están en GitHub).

### Redeploy

```bash
fly deploy -a catalogo-360import
```

### Dominio custom (`catalogo.360import.com`)

En el panel DNS del dominio `360import.com`, agregar **uno** de:

| Tipo | Host | Valor |
|------|------|-------|
| CNAME | `catalogo` | `zk0rng3.catalogo-360import.fly.dev` |

| Tipo | Host | Valor |
|------|------|-------|
| A | `catalogo` | `66.241.124.115` |
| AAAA | `catalogo` | `2a09:8280:1::13b:541b:0` |

Si usás Cloudflare: modo **DNS only** (nube gris), sin proxy.

Verificar certificado:

```bash
fly certs check catalogo.360import.com -a catalogo-360import
```

Estado objetivo: **Ready**.

### Comandos útiles

```bash
fly status -a catalogo-360import
fly logs -a catalogo-360import
fly secrets list -a catalogo-360import
fly volumes list -a catalogo-360import
```

Nota: generar el PDF completo (168 productos + Playwright) puede tardar varios minutos; Fly corta requests HTTP largos (~60s). Si falla desde el navegador, probá `fly ssh console` o aumentá RAM a 2 GB en `fly.toml`.

## Funciones

- CRUD de productos (nombre, categoría, descripción, ficha técnica, exclusión PDF)
- Subir / quitar imágenes por producto
- Generar y descargar `catalogo_360import.pdf`

## Streamlit (legacy)

La app anterior de revisión sigue en `app.py`:

```bash
streamlit run app.py
```

La fuente de verdad en producción es la base de datos (`data/catalog.db`).
