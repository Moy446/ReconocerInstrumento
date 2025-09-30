from fastapi import FastAPI, File, UploadFile, Request
import uvicorn
import wave
import os

app = FastAPI()
audio_file = "grabacion.raw"
wav_file = "grabacion.wav"
sampleRate = 16000
numChannels = 1
sampleWidth = 2

@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    with open("grabacion.wav", "wb") as f:
        f.write(await file.read())
    return {"status": "ok", "filename": file.filename}


# Si ya existía, borramos
if os.path.exists(wav_file):
    os.remove(wav_file)
if os.path.exists(audio_file):
    os.remove(audio_file)

@app.post("/upload_chunk")
async def upload_chunk(request: Request):
    data = await request.body()  # Esto recibe los bytes tal cual
    with open(audio_file, "ab") as f:
        f.write(data)
    return {"status": "ok", "chunk_size": len(data)}

@app.post("/stream_chunk")
async def stream_chunk(file: UploadFile = File(...)):
    data = await file.read()
    # Abrimos WAV en modo append
    with wave.open(wav_file, 'rb+') as wf:
        wf.setpos(wf.getnframes())
        wf.writeframesraw(data)
    return {"status": "ok", "chunk_size": len(data)}

@app.get("/finalize_wav")
def finalize_wav():
    """
    Convierte el archivo RAW acumulado en WAV con encabezado correcto.
    """
    if not os.path.exists(audio_file):
        return {"status": "error", "message": "No hay datos para procesar."}

    # Abrimos RAW y luego WAV
    with open(audio_file, "rb") as rf:
        raw_data = rf.read()

    with wave.open(wav_file, 'wb') as wf:
        wf.setnchannels(numChannels)
        wf.setsampwidth(sampleWidth)
        wf.setframerate(sampleRate)
        wf.writeframes(raw_data)

    nframes = len(raw_data) // sampleWidth
    return {"status": "wav_ready", "frames": nframes, "file": wav_file}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
