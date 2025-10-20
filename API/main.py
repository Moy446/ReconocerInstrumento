from fastapi import FastAPI, File, UploadFile, Request
import uvicorn
import wave
import os
import json
from datetime import datetime

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

    # Limpiar datos para próxima grabación
    sensor_readings = []

    return {
        "status": "ok", 
        "audio_file": wav_file,
        "audio_size": filesize,
        "sensor_data_file": sensor_data_file,
        "sensor_stats": sensor_stats
    }

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
