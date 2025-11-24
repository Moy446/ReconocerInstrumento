from fastapi import FastAPI, File, UploadFile, Request
import uvicorn
import wave
import os
import json
from datetime import datetime
from typing import Optional
import sys
import numpy as np
import scipy.signal as sps
from collections import defaultdict
import time

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
sampleRate = 32000
numChannels = 1
sampleWidth = 2
wf = None
recording_started = False

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
    global sensor_readings, recording_started, wf

    if not recording_started:
        recording_started = True
        sensor_readings = []

    data = await request.body()
    data = await request.body()

    # Obtener datos de sensores
    humidity = request.headers.get("X-Humidity", "0")
    timestamp = request.headers.get("X-Timestamp", str(int(datetime.now().timestamp() * 1000)))

    # Guardar lectura del sensor
    sensor_reading = {
        "timestamp": int(timestamp),
        "humidity": float(humidity),
        "chunk_size": len(data),
        "datetime": datetime.now().isoformat()
    }
    sensor_readings.append(sensor_reading)

    # Guardar datos de sensores en JSON
    with open(sensor_data_file, "w") as f:
        json.dump(sensor_readings, f, indent=2)

    if len(data) > 0:
        with open(audio_file, "ab") as f:
            f.write(data)

    return {
        "status": "ok",
        "chunk_size": len(data),
        "humidity": humidity,
        "total_readings": len(sensor_readings)
    }


@app.get("/finalize_wav")
def finalize_wav():
    global sensor_readings, recording_started

    recording_started = False

    # Validar archivo recibido
    if not os.path.exists(audio_file):
        return {"status": "error", "message": "No hay datos para procesar."}

    filesize = os.path.getsize(audio_file)
    if filesize == 0:
        return {"status": "error", "message": "Archivo vacío."}

    # Crear WAV base a partir del RAW recibido
    with open(audio_file, "rb") as rf:
        raw_data = rf.read()

    with wave.open(wav_file, "wb") as wf_tmp:
        wf_tmp.setnchannels(numChannels)
        wf_tmp.setsampwidth(sampleWidth)
        wf_tmp.setframerate(sampleRate)
        wf_tmp.writeframes(raw_data)

    wav_to_use = wav_file
    
    # --- Aplicar filtro band-pass como el código que pediste ---
    try:
        cleaned_wav = "grabacion_limpia.wav"

        # Leer señal
        with wave.open(wav_file, "rb") as rf:
            frames = rf.readframes(rf.getnframes())
            sr = rf.getframerate()

        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)

        # Calcular frecuencias normalizadas
        low = 300 / (sr / 2)
        high = 3400 / (sr / 2)

        # Protección por si audio es muy corto
        if len(audio) < 50:
            raise Exception("Audio demasiado corto para filtrar")

        b, a = sps.butter(4, [low, high], btype="band")
        filtered = sps.lfilter(b, a, audio)

        # Guardar WAV filtrado
        with wave.open(cleaned_wav, "wb") as wf_out:
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)
            wf_out.setframerate(sampleRate)
            wf_out.writeframes(filtered.astype(np.int16).tobytes())

        wav_to_use = cleaned_wav
        print("✔ Audio filtrado correctamente (300–3400 Hz).")

    except Exception as e:
        print(f"⚠ No se pudo filtrar audio: {e}")
        wav_to_use = wav_file

    # -----------------------------
    #   ESTADÍSTICAS DE SENSORES
    # -----------------------------
    sensor_stats = {}
    if sensor_readings:
        humidities = [reading["humidity"] for reading in sensor_readings]
        sensor_stats = {
            "total_readings": len(sensor_readings),
            "humidity_avg": sum(humidities) / len(humidities),
            "humidity_min": min(humidities),
            "humidity_max": max(humidities),
            "recording_duration_ms":
                sensor_readings[-1]["timestamp"] - sensor_readings[0]["timestamp"]
                if len(sensor_readings) > 1 else 0
        }

    # -----------------------------
    #   PREDICCIÓN MODELO
    # -----------------------------
    prediction = {"instrument": "Unknown", "note": "Unknown"}
    if predictor is not None:
        try:
            prediction = predictor.predict(wav_to_use)
        except Exception as e:
            prediction = {"instrument": "Unknown", "note": "Unknown", "error": str(e)}
    # -----------------------------
    #   SUBIR A AZURE BLOB STORAGE
    # -----------------------------
    if container_client:
        try:
            blob_name = f"audio_{int(time.time())}.wav"
            with open(wav_to_use, "rb") as data:
                container_client.upload_blob(name=blob_name, data=data, overwrite=True)
            print(f"✔ WAV subido a Azure Blob: {blob_name}")
        except Exception as e:
            print(f"⚠ Error al subir WAV a Azure Blob: {e}")
    # -----------------------------
    #   INSERTAR EN POSTGRESQL
    # -----------------------------
    conn = db_connect()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO public.detections (instrument, note, humidity) VALUES (%s, %s, %s)",
                    (
                        prediction.get("instrument", "Unknown"),
                        prediction.get("note", "Unknown"),
                        sensor_stats.get("humidity_avg", None),
                    )
                )
                conn.commit()
            print("✔ Registro insertado en PostgreSQL.")
        except Exception as e:
            print(f"⚠ Error al insertar en PostgreSQL: {e}")

    # Reset
    sensor_readings = []

    return {
        "status": "ok",
        "audio_file": wav_file,
        "clean_audio": wav_to_use,
        "audio_size": filesize,
        "sensor_stats": sensor_stats,
        "prediction": prediction,
    }


@app.get("/sensor_data")
def get_sensor_data():
    """Endpoint para obtener los datos del sensor por separado"""
    conn = db_connect()
    ins = set(["bateria","guitarra","violin","piano"])
    dataInst = defaultdict(int)
    dataNote = defaultdict(int)
    dataHumidity = defaultdict(int)
    lastInstrument = ""
    lastNote = ""
    lastHumidity = ""
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT instrument,note,humidity,count(*) AS total FROM public.detections GROUP BY instrument,note,humidity;"
                )
                data = cur.fetchall()
                cur.execute(
                    "SELECT instrument,note,humidity FROM public.detections ORDER BY id DESC limit 1;"
                )
                lastData = cur.fetchall()
            for instrument,note,humidity,total in data:
                dataInst[instrument] += total
                dataNote[note] += total
                dataHumidity[humidity] += total
            lastInstrument,lastNote,lastHumidity = lastData[0]
            
            return {"status":"ok", "data":{"instrumentos": dict(dataInst),"notas": dict(dataNote),"humedades": dict(dataHumidity), "lastInstrument": lastInstrument, "lastNote": lastNote, "lastHumidity": lastHumidity}}
        except Exception as e:
            return {"status": "error", "message": f"Error al seleccionar datos en PostgreSQL: {e}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
