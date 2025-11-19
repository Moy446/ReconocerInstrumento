"""
Entrenamiento en un solo script (compatible con Google Colab) para un modelo Random Forest
que clasifica instrumento (piano, guitarra, batería, violín) y nota musical.

- Descarga el dataset de Kaggle (soumendraprasad/musical-instruments-sound-dataset) con kagglehub
- Extrae características con librosa
- Entrena RandomForest para instrumento y otro para nota (nota derivada por f0 si no existe en nombre)
- Guarda los artefactos en ./model_artifacts/*.pkl
"""
import os
import sys
import pickle
from typing import List, Tuple, Dict, Optional

# Instalar dependencias automáticamente si estamos en Colab
try:
    import google.colab  # type: ignore
    IN_COLAB = True
except Exception:
    IN_COLAB = False

if IN_COLAB:
    # Paquetes necesarios
    import subprocess
    pkgs = [
        "librosa",
        "scikit-learn",
        "numpy",
        "soundfile",
        "kagglehub>=0.2.5",
        "tqdm",
    ]
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + pkgs)

import numpy as np
from tqdm import tqdm
import librosa
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.utils.multiclass import unique_labels

try:
    import kagglehub
except Exception as e:
    print("kagglehub no disponible. Asegúrate de instalarlo si deseas descargar el dataset automáticamente.")
    kagglehub = None  # type: ignore


def extract_features_vector_from_array(y: np.ndarray, sr: int = 16000,
                                       n_mfcc: int = 13, n_fft: int = 2048, hop_length: int = 512) -> np.ndarray:
    if y.size == 0:
        return np.zeros(2*n_mfcc + 2*12 + 2*5 + 2, dtype=np.float32)

    feats: List[float] = []

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length)
    feats.extend(np.mean(mfcc, axis=1))
    feats.extend(np.std(mfcc, axis=1))

    chroma = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    feats.extend(np.mean(chroma, axis=1))
    feats.extend(np.std(chroma, axis=1))

    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    zcr = librosa.feature.zero_crossing_rate(y=y, hop_length=hop_length)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)

    feats.extend([float(np.mean(spectral_centroid)), float(np.std(spectral_centroid))])
    feats.extend([float(np.mean(spectral_rolloff)), float(np.std(spectral_rolloff))])
    feats.extend([float(np.mean(spectral_bandwidth)), float(np.std(spectral_bandwidth))])
    feats.extend([float(np.mean(zcr)), float(np.std(zcr))])
    feats.extend([float(np.mean(rms)), float(np.std(rms))])

    # f0
    f0 = librosa.yin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), sr=sr)
    f0_valid = f0[f0 > 0]
    if f0_valid.size > 0:
        feats.extend([float(np.mean(f0_valid)), float(np.std(f0_valid))])
    else:
        feats.extend([0.0, 0.0])

    return np.asarray(feats, dtype=np.float32)


def hz_to_note_name(freq: float) -> str:
    if freq <= 0:
        return "Unknown"
    try:
        note_number = librosa.hz_to_midi(freq)
        return str(librosa.midi_to_note(int(round(note_number))))
    except Exception:
        return "Unknown"


def hz_to_note_name(freq: float) -> str:
    if freq <= 0:
        return "Unknown"
    try:
        note_number = librosa.hz_to_midi(freq)
        return str(librosa.midi_to_note(int(round(note_number))))
    except Exception:
        return "Unknown"


def derive_note_from_filename(path: str) -> Optional[str]:
    """Intenta encontrar una nota musical en el nombre del archivo.
    Busca patrones simples como C, C#, D, Eb, etc.
    """
    import re
    name = os.path.basename(path).lower()
    # Patrones comunes: c, c#, db, d, d#, eb, ... b
    # Nota: muy heurístico, para datasets con notas en filename
    pattern = r"\b(a#|bb|a|b|c#|db|c|d#|eb|d|e|f#|gb|f|g#|ab|g)\b"
    m = re.search(pattern, name)
    if not m:
        return None
    token = m.group(1).upper()
    # Normalizar equivalencias bemol->sostenido si se desea
    mapping = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}
    return mapping.get(token, token)




def collect_files(dataset_dir: str) -> List[str]:
    files: List[str] = []
    for root, _, fns in os.walk(dataset_dir):
        for fn in fns:
            if fn.lower().endswith((".wav", ".mp3", ".flac", ".ogg")):
                files.append(os.path.join(root, fn))
    return files


def map_instrument(path: str) -> Optional[str]:
    p = path.lower()
    # Intentar detectar por carpeta/archivo
    if "piano" in p:
        return "piano"
    if ("guitar" in p or "acoustic_guitar" in p or "electric_guitar" in p or
        "guit" in p or "guitarra" in p or "guitars" in p):
        return "guitarra"
    if "violin" in p:
        return "violin"
    if "drum" in p or "drums" in p or "tabla" in p or "dhol" in p or "percussion" in p:
        return "bateria"
    return None


def main():
    sr = 16000
    out_dir = os.path.join(os.getcwd(), "model_artifacts")
    os.makedirs(out_dir, exist_ok=True)

    # Descargar dataset
    dataset_dir: Optional[str] = None
    if kagglehub is not None:
        try:
            print("Descargando dataset de Kaggle...")
            dataset_dir = kagglehub.dataset_download("soumendraprasad/musical-instruments-sound-dataset")
            print("Dataset en:", dataset_dir)
        except Exception as e:
            print("Fallo al descargar dataset:", e)
            dataset_dir = None

    if dataset_dir is None:
        # Si falla, esperar que el usuario lo monte o provea carpeta
        dataset_dir = os.getenv("DATASET_DIR", "./dataset")
        print("Usando dataset local:", dataset_dir)

    all_files = collect_files(dataset_dir)
    print(f"Archivos totales encontrados: {len(all_files)}")

    X_inst: List[np.ndarray] = []
    y_inst: List[str] = []
    X_note: List[np.ndarray] = []
    y_note: List[str] = []

    max_per_class = int(os.getenv("MAX_PER_CLASS", "400"))  # para mantener razonable
    counts: Dict[str, int] = {"piano": 0, "guitarra": 0, "bateria": 0, "violin": 0}

    for path in tqdm(all_files, desc="Extrayendo características"):
        inst = map_instrument(path)
        if inst is None:
            continue
        if counts[inst] >= max_per_class:
            continue

        try:
            y, _ = librosa.load(path, sr=sr, mono=True)
            if y.size < sr // 2:  # al menos 0.5s
                continue
            feats = extract_features_vector_from_array(y, sr)
            X_inst.append(feats)
            y_inst.append(inst)

            # Nota para entrenamiento: 1) intentar por nombre 2) si no, por f0
            note = derive_note_from_filename(path)
            if note is None:
                f0 = feats[-2]  # mean f0
                note = hz_to_note_name(float(f0))
            X_note.append(feats)
            y_note.append(note)

            counts[inst] += 1
        except Exception:
            continue

    X_inst_arr = np.vstack(X_inst) if X_inst else np.empty((0, 2*13+2*12+2*5+2), dtype=np.float32)
    X_note_arr = np.vstack(X_note) if X_note else np.empty((0, 2*13+2*12+2*5+2), dtype=np.float32)

    print("Muestras instrumento:", len(y_inst))
    print("Muestras nota:", len(y_note))
    print("Muestras instrumento:", len(y_inst))
    print("Muestras nota:", len(y_note))

    # Codificadores
    inst_le = LabelEncoder()
    if y_inst:
        y_inst_enc = inst_le.fit_transform(y_inst)
    else:
        y_inst_enc = np.array([])

    note_le = LabelEncoder()
    if y_note:
        y_note_enc = note_le.fit_transform(y_note)
    else:
        y_note_enc = np.array([])

    # Entrenar modelos
    inst_model: Optional[RandomForestClassifier] = None
    note_model: Optional[RandomForestClassifier] = None

    if len(y_inst_enc) > 0:
        Xtr, Xte, ytr, yte = train_test_split(X_inst_arr, y_inst_enc, test_size=0.2, random_state=42, stratify=y_inst_enc)
        inst_model = RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1)
        inst_model.fit(Xtr, ytr)
        ypr = inst_model.predict(Xte)
        print("Reporte instrumento:\n", classification_report(yte, ypr, target_names=inst_le.classes_))

    if len(y_note_enc) > 0 and len(set(y_note)) > 1:
        class_counts = np.bincount(y_note_enc)
        if np.min(class_counts) >= 2:
            Xtr, Xte, ytr, yte = train_test_split(X_note_arr, y_note_enc, test_size=0.2, random_state=42, stratify=y_note_enc)
            note_model = RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1)
            note_model.fit(Xtr, ytr)
            ypr = note_model.predict(Xte)
            # Use unique_labels to get labels actually present in yte and ypr
            labels = unique_labels(yte, ypr)
            target_names = note_le.inverse_transform(labels)
            print("Reporte nota:\n", classification_report(yte, ypr, labels=labels, target_names=target_names))
        else:
            print("Suficientes muestras por clase no encontradas para estratificación; se omitirá estratificación para el modelo de notas.")
            Xtr, Xte, ytr, yte = train_test_split(X_note_arr, y_note_enc, test_size=0.2, random_state=42)
            note_model = RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1)
            note_model.fit(Xtr, ytr)
            ypr = note_model.predict(Xte)
            # Use unique_labels to get labels actually present in yte and ypr
            labels = unique_labels(yte, ypr)
            target_names = note_le.inverse_transform(labels)
            print("Reporte nota (sin estratificación):\n", classification_report(yte, ypr, labels=labels, target_names=target_names))

    # Guardar artefactos
    if inst_model is not None:
        with open(os.path.join(out_dir, "instrument_rf.pkl"), 'wb') as f:
            pickle.dump(inst_model, f)
        with open(os.path.join(out_dir, "instrument_encoder.pkl"), 'wb') as f:
            pickle.dump(inst_le, f)

    if note_model is not None:
        with open(os.path.join(out_dir, "note_rf.pkl"), 'wb') as f:
            pickle.dump(note_model, f)
        with open(os.path.join(out_dir, "note_encoder.pkl"), 'wb') as f:
            pickle.dump(note_le, f)

    print("Artefactos guardados en:", out_dir)


if __name__ == "__main__":
    main()
