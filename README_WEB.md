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
