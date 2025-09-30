from fastapi import FastAPI, File, UploadFile
import uvicorn

app = FastAPI()

@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    with open("grabacion.wav", "wb") as f:
        f.write(await file.read())
    return {"status": "ok", "filename": file.filename}
    