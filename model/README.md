# Modelo de instrumento y nota (Random Forest)

Este directorio contiene:
- `train_colab.py`: script único para entrenar en Google Colab (o local) descargando el dataset de Kaggle y generando artefactos.
- `feature_extraction.py`: extracción de características consistente entre entrenamiento e inferencia.
- `predict_runtime.py`: cargador de modelos y predictor (usado por la API en Azure).

## Entrenar en Google Colab

1. Abre Google Colab y sube `train_colab.py` o cárgalo por URL.
2. Ejecuta el script. Descargará el dataset `soumendraprasad/musical-instruments-sound-dataset` vía `kagglehub`.
3. Entrenará dos modelos Random Forest:
   - Instrumento: piano, guitarra, batería, violín.
   - Nota: derivada por nombre de archivo o por frecuencia fundamental (f0). Si no hay suficientes clases de nota, se omitirá este modelo y en runtime se usará f0.
4. Guardará artefactos en `./model_artifacts/`:
   - `instrument_rf.pkl`, `instrument_encoder.pkl`
   - (opcional) `note_rf.pkl`, `note_encoder.pkl`

Variables de entorno útiles en Colab:
- `MAX_PER_CLASS`: limita cantidad de muestras por instrumento (default 400) para acelerar.
- `DATASET_DIR`: usa dataset local (si no se desea usar kagglehub).

## Despliegue en Azure (inferencia)

- Copia la carpeta `model_artifacts` (con los `.pkl`) al entorno de la API (por ejemplo, incluyéndola en el repo o montándola como volumen en App Service).
- La API intentará cargar los modelos al iniciar. Variables de entorno opcionales:
  - `MODEL_DIR` (default: `./model_artifacts`)
  - `INSTRUMENT_MODEL_FILE`, `NOTE_MODEL_FILE`
  - `INSTRUMENT_ENCODER_FILE`, `NOTE_ENCODER_FILE`

## PostgreSQL en Azure

Configura una de estas variables de entorno en App Service para habilitar inserciones:
 `DATABASE_URL` (recomendado) o `AZURE_POSTGRESQL_CONNECTION_STRING` (formato psycopg/postgresql://). Si empieza con `postgres://`, se normaliza a `postgresql://`.
 Alternativa por partes (se usan solo si no hay cadena completa): `PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGPORT` (y opcional `PGSSLMODE`, default `require`).

La API creará (si no existe) la tabla `public.audio_readings` con columnas:

## Notas

### Ejemplo de .env
Consulta el archivo `.env.example` incluido y copia a `.env` (no lo subas al repositorio):
```
DATABASE_URL=postgresql://usuario:password@host:5432/base?sslmode=require
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=...;AccountName=...;AccountKey=...
AZURE_STORAGE_CONTAINER=audio
MODEL_DIR=./model_artifacts
```
