import json
import threading
from pathlib import Path
from typing import Any

import numpy as np
from django.conf import settings

_model: Any | None = None
_load_lock = threading.Lock()
_load_failed = False
_availability_cached: bool | None = None

MODEL_ID = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIM = 768
_CACHE_DIR_NAMES = (
    "BAAI_bge-base-en-v1.5",
    "models--BAAI--bge-base-en-v1.5",
)


def _get_cache_root() -> Path:
    return settings.BASE_DIR / "llm_test" / "cache" / "embedding-models"


def _get_cache_paths() -> tuple[Path, ...]:
    root = _get_cache_root()
    return tuple(root / name for name in _CACHE_DIR_NAMES)


def is_available() -> bool:
    global _availability_cached
    if _model is not None:
        return True
    if _load_failed:
        return False
    if _availability_cached is not None:
        return _availability_cached
    _availability_cached = any(
        p.exists() and any(p.iterdir()) for p in _get_cache_paths()
    )
    return _availability_cached


def is_loaded() -> bool:
    return _model is not None


def _candidate_devices() -> tuple[str, ...]:
    import torch

    devices: list[str] = []
    if torch.cuda.is_available():
        devices.append("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append("mps")
    devices.append("cpu")
    return tuple(devices)


def _get_model():
    global _model, _load_failed

    if _model is not None:
        return _model

    with _load_lock:
        if _model is not None:
            return _model
        if _load_failed:
            raise RuntimeError("Embedding model previously failed to load")

        from sentence_transformers import SentenceTransformer

        cache_dir = str(_get_cache_root())
        last_error: Exception | None = None

        for device in _candidate_devices():
            try:
                loaded = SentenceTransformer(
                    MODEL_ID,
                    cache_folder=cache_dir,
                    device=device,
                )
                _model = loaded
                return _model
            except Exception as exc:
                last_error = exc

        _load_failed = True
        raise RuntimeError("Failed to load embedding model") from last_error


def encode_texts(texts: list[str], batch_size: int = 32) -> np.ndarray | None:
    try:
        model = _get_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=False,
        )
        return np.array(embeddings, dtype=np.float32)
    except Exception:
        return None


def encode_query(query: str) -> np.ndarray | None:
    result = encode_texts([query])
    if result is None:
        return None
    return result.reshape(1, -1)


def cosine_search(
    query_embedding: np.ndarray,
    corpus_embeddings: np.ndarray,
    top_k: int = 5,
) -> list[tuple[int, float]]:
    from sklearn.metrics.pairwise import cosine_similarity

    if corpus_embeddings.shape[0] == 0:
        return []
    similarities = cosine_similarity(query_embedding, corpus_embeddings)[0]
    top_indices = np.argsort(similarities)[::-1][:top_k]
    return [(int(idx), float(similarities[idx])) for idx in top_indices]


def embedding_to_json(embedding: np.ndarray) -> str:
    return json.dumps(embedding.tolist())


def json_to_embedding(embedding_json: str) -> np.ndarray | None:
    if not embedding_json:
        return None
    try:
        return np.array(json.loads(embedding_json), dtype=np.float32)
    except (json.JSONDecodeError, ValueError):
        return None
