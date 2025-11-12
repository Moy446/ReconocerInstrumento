from fastapi import FastAPI, File, UploadFile, Request
import uvicorn
import wave
import os
import json
from datetime import datetime
from typing import Optional
import sys

# Cargar variables .env en desarrollo local si existe (no afecta Azure App Service que ya inyecta vars)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ML predictor (cargado si los archivos de modelo existen)
PREDICTOR_AVAILABLE = False
try:
    from model.predict_runtime import AudioPredictor
    PREDICTOR_AVAILABLE = True
except Exception as _e:
    PREDICTOR_AVAILABLE = False

# Azure Blob (opcional)
AZURE_AVAILABLE = False
try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    AZURE_AVAILABLE = True
except Exception:
    AZURE_AVAILABLE = False

app = FastAPI()
audio_file = "grabacion.raw"
wav_file = "grabacion.wav"
sensor_data_file = "mediciones.json"
sampleRate = 16000
numChannels = 1
sampleWidth = 2

# Almacenar datos de sensores
sensor_readings = []

# Si ya existía, borramos archivos anteriores
for file in [wav_file, audio_file, sensor_data_file]:
    if os.path.exists(file):
        os.remove(file)

# Config Azure (si hay variables de entorno)
blob_service: Optional[BlobServiceClient] = None
container_client = None
container_name = os.getenv("AZURE_STORAGE_CONTAINER", "audio")
if AZURE_AVAILABLE:
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if conn_str:
        try:
            blob_service = BlobServiceClient.from_connection_string(conn_str)
            container_client = blob_service.get_container_client(container_name)
            try:
                container_client.create_container()
            except Exception:
                pass  # ya existe
            print(f"Azure Blob habilitado. Contenedor: {container_name}")
        except Exception as e:
            print(f"No se pudo inicializar Azure Blob: {e}")
            blob_service = None
            container_client = None

# Predictor global (opcional)
predictor: Optional["AudioPredictor"] = None
if PREDICTOR_AVAILABLE:
    try:
        predictor = AudioPredictor()
        print("Predictor de audio cargado")
    except Exception as e:
        predictor = None
        print(f"No se pudo cargar el predictor: {e}")

# PostgreSQL (opcional) - proteger credenciales vía variables de entorno
DB_AVAILABLE = False
DB_DSN: Optional[str] = None

# Opción 1: cadena de conexión completa (recomendada)
DB_DSN = os.getenv("DATABASE_URL") or os.getenv("AZURE_POSTGRESQL_CONNECTION_STRING")
if DB_DSN and DB_DSN.startswith("postgres://"):
    # Normalizar prefijo para psycopg2
    DB_DSN = DB_DSN.replace("postgres://", "postgresql://", 1)

# Opción 2: componentes sueltos
if not DB_DSN:
    host = os.getenv("PGHOST")
    db = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    pwd = os.getenv("PGPASSWORD")
    port = os.getenv("PGPORT", "5432")
    if host and db and user and pwd:
        DB_DSN = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

if DB_DSN:
    DB_AVAILABLE = True

pg_conn = None
if DB_AVAILABLE:
    try:
        import psycopg2  # type: ignore
        from psycopg2.extras import execute_values  # type: ignore
        print("psycopg2 disponible; inserciones a PostgreSQL habilitadas si la conexión funciona")
    except Exception as e:
        DB_AVAILABLE = False
        print(f"psycopg2 no disponible: {e}")

TABLE_SQL = (
    """
    CREATE TABLE IF NOT EXISTS public.detections (
        id SERIAL PRIMARY KEY,
        instrument TEXT,
        note TEXT,
        humidity_avg DOUBLE PRECISION
    );
    """
)

def db_connect():
    global pg_conn
    if not DB_AVAILABLE or not DB_DSN:
        return None
    try:
        import psycopg2  # type: ignore
        if pg_conn is None or pg_conn.closed != 0:
            # SSL requerido generalmente en Azure
            pg_conn = psycopg2.connect(DB_DSN, sslmode=os.getenv("PGSSLMODE", "require"))
            with pg_conn.cursor() as cur:
                cur.execute(TABLE_SQL)
                pg_conn.commit()
        return pg_conn
    except Exception as e:
        print(f"No se pudo conectar a PostgreSQL: {e}")
        return None

@app.post("/upload_chunk")
async def upload_chunk(request: Request):
    global sensor_readings  # Declarar como global
    
    data = await request.body()  # Esto recibe los bytes tal cual
    
    # Obtener datos del sensor de los headers
    humidity = request.headers.get("X-Humidity", "0")
    timestamp = request.headers.get("X-Timestamp", str(int(datetime.now().timestamp() * 1000)))
    
    # Guardar datos del sensor
    sensor_reading = {
        "timestamp": int(timestamp),  # Convertir a int
        "humidity": float(humidity),
        "chunk_size": len(data),
        "datetime": datetime.now().isoformat()
    }
    sensor_readings.append(sensor_reading)
    
    # Guardar audio
    with open(audio_file, "ab") as f:
        f.write(data)
    
    # Guardar datos de sensores en archivo JSON
    with open(sensor_data_file, "w") as f:
        json.dump(sensor_readings, f, indent=2)
    
    return {
        "status": "ok", 
        "chunk_size": len(data),
        "humidity": humidity,
        "total_readings": len(sensor_readings)
    }

@app.get("/finalize_wav")
def finalize_wav():
    global sensor_readings  # Declarar como global al inicio
    
    if not os.path.exists(audio_file):
        return {"status": "error", "message": "No hay datos para procesar."}

    filesize = os.path.getsize(audio_file)
    if filesize == 0:
        return {"status": "error", "message": "Archivo vacío."}

    with open(audio_file, "rb") as rf:
        raw_data = rf.read()

    with wave.open(wav_file, 'wb') as wf:
        wf.setnchannels(numChannels)
        wf.setsampwidth(sampleWidth)
        wf.setframerate(sampleRate)
        wf.writeframes(raw_data)

    # Procesar estadísticas de los datos del sensor
    sensor_stats = {}
    if sensor_readings:
        humidities = [reading["humidity"] for reading in sensor_readings]
        sensor_stats = {
            "total_readings": len(sensor_readings),
            "humidity_avg": sum(humidities) / len(humidities),
            "humidity_min": min(humidities),
            "humidity_max": max(humidities),
            "recording_duration_ms": sensor_readings[-1]["timestamp"] - sensor_readings[0]["timestamp"] if len(sensor_readings) > 1 else 0
        }

    # Subir a Azure Blob si está configurado
    azure_info = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if container_client is not None:
        try:
            wav_blob_name = f"recordings/grabacion_{timestamp}.wav"
            meta_blob_name = f"recordings/mediciones_{timestamp}.json"

            # Subir WAV
            with open(wav_file, "rb") as f:
                container_client.upload_blob(
                    name=wav_blob_name,
                    data=f,
                    overwrite=True,
                    content_settings=ContentSettings(content_type="audio/wav")
                )
            # Subir JSON de sensores (si existe)
            if os.path.exists(sensor_data_file):
                with open(sensor_data_file, "rb") as f:
                    container_client.upload_blob(
                        name=meta_blob_name,
                        data=f,
                        overwrite=True,
                        content_settings=ContentSettings(content_type="application/json")
                    )

            azure_info = {
                "container": container_name,
                "wav_blob": wav_blob_name,
                "wav_url": f"{container_client.url}/{wav_blob_name}",
                "sensor_blob": meta_blob_name,
                "sensor_url": f"{container_client.url}/{meta_blob_name}"
            }
        except Exception as e:
            azure_info = {"error": str(e)}

    # Predicción (si hay modelo)
    prediction = {"instrument": "Unknown", "note": "Unknown"}
    if predictor is not None:
        try:
            prediction = predictor.predict(wav_file)
        except Exception as e:
            prediction = {"instrument": "Unknown", "note": "Unknown", "error": str(e)}

    # Insertar en PostgreSQL (si está configurado)
    db_insert_status = None
    if DB_AVAILABLE:
        conn = db_connect()
        if conn is not None:
            try:
                wav_url = None
                if isinstance(azure_info, dict) and azure_info.get("wav_url"):
                    wav_url = azure_info["wav_url"]
                hum_avg = None
                if isinstance(sensor_stats, dict) and "humidity_avg" in sensor_stats:
                    hum_avg = float(sensor_stats["humidity_avg"]) if sensor_stats["humidity_avg"] is not None else None
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO public.detections (instrument, note, humidity_avg) VALUES (%s, %s, %s);",
                        (
                            prediction.get("instrument"),
                            prediction.get("note"),
                            hum_avg,
                        ),
                    )
                    conn.commit()
                db_insert_status = "inserted"
            except Exception as e:
                db_insert_status = f"error: {e}"

    # Limpiar datos para próxima grabación
    sensor_readings = []

    result = {
        "status": "ok", 
        "audio_file": wav_file,
        "audio_size": filesize,
        "sensor_data_file": sensor_data_file,
        "sensor_stats": sensor_stats,
        "prediction": prediction,
    }
    if azure_info:
        result["azure"] = azure_info
    if db_insert_status is not None:
        result["postgres_insert"] = db_insert_status
    return result

@app.get("/sensor_data")
def get_sensor_data():
    """Endpoint para obtener los datos del sensor por separado"""
    if os.path.exists(sensor_data_file):
        with open(sensor_data_file, "r") as f:
            data = json.load(f)
        return {"status": "ok", "data": data}
    return {"status": "error", "message": "No hay datos de sensores disponibles"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
