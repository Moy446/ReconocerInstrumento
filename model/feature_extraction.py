"""
Extracción de características consistente para entrenamiento e inferencia.
"""
from typing import Dict
import numpy as np
import librosa


def extract_features_vector(audio_path: str, sample_rate: int = 16000,
                            n_mfcc: int = 13, n_fft: int = 2048, hop_length: int = 512) -> np.ndarray:
    """Carga audio y retorna un vector 1D de características.
    Características: MFCC (mean,std), Chroma (mean,std), Spectral features (centroid, rolloff,
    bandwidth, zcr, rms) y f0 (mean,std). Orden fijo.
    """
    y, sr = librosa.load(audio_path, sr=sample_rate, mono=True)

    # Evitar audios vacíos
    if y.size == 0:
        return np.zeros(2*n_mfcc + 2*12 + 2*5 + 2, dtype=np.float32)

    feats = []

    # MFCC
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length)
    feats.extend(np.mean(mfcc, axis=1))
    feats.extend(np.std(mfcc, axis=1))

    # Chroma
    chroma = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    feats.extend(np.mean(chroma, axis=1))
    feats.extend(np.std(chroma, axis=1))

    # Spectral centroid, rolloff, bandwidth, zcr, rms
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

    # f0 (frecuencia fundamental)
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
