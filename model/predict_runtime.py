"""
Cargador de modelo y predictor para Azure runtime.
- Carga RandomForest entrenado (pickle)
- Extrae características con feature_extraction.extract_features_vector
- Devuelve instrumento y nota estimada

Variables de entorno esperadas (opcional, para rutas por defecto):
- MODEL_DIR (default: ./model_artifacts)
- INSTRUMENT_MODEL_FILE (default: instrument_rf.pkl)
- NOTE_MODEL_FILE (default: note_rf.pkl)  # opcional si solo usamos f0->nota
- INSTRUMENT_ENCODER_FILE (default: instrument_encoder.pkl)
- NOTE_ENCODER_FILE (default: note_encoder.pkl)
"""
import os
import pickle
from typing import Dict, Optional

import numpy as np

from .feature_extraction import extract_features_vector, hz_to_note_name


class AudioPredictor:
    def __init__(self, model_dir: Optional[str] = None) -> None:
        base = model_dir or os.getenv("MODEL_DIR", os.path.join(os.getcwd(), "model_artifacts"))
        self.instrument_model_path = os.path.join(base, os.getenv("INSTRUMENT_MODEL_FILE", "instrument_rf.pkl"))
        self.instrument_encoder_path = os.path.join(base, os.getenv("INSTRUMENT_ENCODER_FILE", "instrument_encoder.pkl"))
        self.note_model_path = os.path.join(base, os.getenv("NOTE_MODEL_FILE", "note_rf.pkl"))
        self.note_encoder_path = os.path.join(base, os.getenv("NOTE_ENCODER_FILE", "note_encoder.pkl"))

        self.inst_model = None
        self.inst_encoder = None
        self.note_model = None
        self.note_encoder = None

        # Intentar cargar modelo/encoder de instrumento
        if os.path.exists(self.instrument_model_path) and os.path.exists(self.instrument_encoder_path):
            with open(self.instrument_model_path, 'rb') as f:
                self.inst_model = pickle.load(f)
            with open(self.instrument_encoder_path, 'rb') as f:
                self.inst_encoder = pickle.load(f)

        # Nota (opcional); si falta, usaremos f0 para nota
        if os.path.exists(self.note_model_path) and os.path.exists(self.note_encoder_path):
            try:
                with open(self.note_model_path, 'rb') as f:
                    self.note_model = pickle.load(f)
                with open(self.note_encoder_path, 'rb') as f:
                    self.note_encoder = pickle.load(f)
            except Exception:
                self.note_model = None
                self.note_encoder = None

    def predict(self, audio_path: str) -> Dict[str, str]:
        x = extract_features_vector(audio_path)
        x2d = x.reshape(1, -1)

        result = {"instrument": "Unknown", "note": "Unknown"}

        # Instrumento
        if self.inst_model is not None and self.inst_encoder is not None:
            try:
                y_pred = self.inst_model.predict(x2d)
                label = self.inst_encoder.inverse_transform(y_pred)[0]
                result["instrument"] = str(label)
            except Exception:
                pass

        # Nota via modelo o f0
        if self.note_model is not None and self.note_encoder is not None:
            try:
                y_note = self.note_model.predict(x2d)
                note_label = self.note_encoder.inverse_transform(y_note)[0]
                result["note"] = str(note_label)
                return result
            except Exception:
                pass

        # Fallback: derivar nota desde f0 mean (está en las últimas 2 features)
        try:
            f0_mean = float(x[-2])
            result["note"] = hz_to_note_name(f0_mean)
        except Exception:
            result["note"] = "Unknown"

        return result
