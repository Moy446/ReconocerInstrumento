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

@app.get("/finalize_wav")
def finalize_wav():
    if not os.path.exists(audio_file):
        return {"status": "error", "message": "No hay datos para procesar."}

    filesize = os.path.getsize(audio_file)
    if filesize == 0:
        return {"status": "error", "message": "Archivo vacío."}

    with open(audio_file, "rb") as rf:
        raw_data = rf.read()

    with wave.open(wav_file, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(raw_data)

    return {"status": "ok", "size": filesize, "file": wav_file}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
