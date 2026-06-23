"""
DeepFace backend.

Uses the ``deepface`` library to produce high-dimensional face embeddings
with GPU support and multiple model options.
Install with: ``pip install cctvql[deepface]``

Supported models (pass as ``model_name`` kwarg to the constructor):
  VGG-Face (default), Facenet, Facenet512, OpenFace, DeepFace, DeepID,
  ArcFace (recommended for accuracy), SFace, GhostFaceNet

Distance metric: cosine (default). ArcFace + cosine is the recommended
combination for high-accuracy production deployments.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np

from cctvql.core.face_backends.base import BaseFaceBackend

logger = logging.getLogger(__name__)

try:
    import deepface  # type: ignore[import]   # noqa: F401
    from deepface import DeepFace as _DeepFace  # type: ignore[import]
    _AVAILABLE = True
except ImportError:
    _DeepFace = None  # type: ignore[assignment]
    _AVAILABLE = False


# Embedding dimensions by model name
_MODEL_DIMS: dict[str, int] = {
    "VGG-Face": 4096,
    "Facenet": 128,
    "Facenet512": 512,
    "OpenFace": 128,
    "DeepFace": 4096,
    "DeepID": 160,
    "ArcFace": 512,
    "SFace": 128,
    "GhostFaceNet": 512,
}

# Cosine tolerance: deepface cosine distance is in [0, 1]; typical ArcFace
# threshold is 0.68, Facenet512 is 0.30. We default to a conservative 0.40
# which works reasonably across ArcFace / Facenet512 / Facenet.
_DEFAULT_COSINE_TOLERANCE = 0.40


class DeepFaceBackend(BaseFaceBackend):
    """
    DeepFace backend with GPU support and pluggable model choice.

    Args:
        model_name:      DeepFace model to use (default: ``"ArcFace"``).
        detector_backend: Face detector backend (default: ``"retinaface"``).
                          Options: opencv, ssd, mtcnn, retinaface, mediapipe, yolov8.
        enforce_detection: If True (default), raise on no-face images.
    """

    def __init__(
        self,
        model_name: str = "ArcFace",
        detector_backend: str = "retinaface",
        enforce_detection: bool = True,
    ) -> None:
        self._model_name = model_name
        self._detector_backend = detector_backend
        self._enforce_detection = enforce_detection
        self.tolerance = _DEFAULT_COSINE_TOLERANCE
        self.embedding_dim = _MODEL_DIMS.get(model_name, 512)

    @property
    def available(self) -> bool:
        return _AVAILABLE

    def embed_single(self, image_bytes: bytes) -> list[float]:
        """Extract embedding for the one face in the image (for enrollment)."""
        if not _AVAILABLE:
            raise ImportError(
                "deepface is not installed. Run: pip install cctvql[deepface]"
            )
        img_array = _bytes_to_array(image_bytes)
        embeddings = _DeepFace.represent(
            img_path=img_array,
            model_name=self._model_name,
            detector_backend=self._detector_backend,
            enforce_detection=self._enforce_detection,
        )
        if len(embeddings) == 0:
            raise ValueError(
                "No face detected in the enrollment image. "
                "Please provide a clear, well-lit frontal photo."
            )
        if len(embeddings) > 1:
            raise ValueError(
                f"{len(embeddings)} faces detected. "
                "Enrollment requires a photo containing exactly one person."
            )
        return _normalise(embeddings[0]["embedding"])

    def detect_and_embed(self, image_bytes: bytes) -> list[list[float]]:
        """Detect all faces and return one embedding per face."""
        if not _AVAILABLE:
            raise ImportError(
                "deepface is not installed. Run: pip install cctvql[deepface]"
            )
        img_array = _bytes_to_array(image_bytes)
        try:
            results = _DeepFace.represent(
                img_path=img_array,
                model_name=self._model_name,
                detector_backend=self._detector_backend,
                enforce_detection=False,  # don't raise on no faces for recognition
            )
        except Exception as exc:
            logger.warning("DeepFace.represent failed: %s", exc)
            return []
        return [_normalise(r["embedding"]) for r in results]

    def compare(
        self,
        known_embeddings: list[list[float]],
        query_embedding: list[float],
    ) -> list[float]:
        """
        Compute cosine distances between *known_embeddings* and *query_embedding*.

        Cosine distance = 1 − cosine_similarity, so 0.0 is a perfect match
        and 1.0 is maximally dissimilar.
        """
        if not known_embeddings:
            return []
        known = np.array(known_embeddings, dtype=np.float32)
        query = np.array(query_embedding, dtype=np.float32)

        # Normalise to unit length for numerically stable cosine similarity
        known_norms = np.linalg.norm(known, axis=1, keepdims=True)
        query_norm = np.linalg.norm(query)
        known_safe = known / np.where(known_norms == 0, 1.0, known_norms)
        query_safe = query / (query_norm if query_norm else 1.0)

        cosine_similarities = known_safe @ query_safe
        distances = 1.0 - cosine_similarities
        return [float(d) for d in distances]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bytes_to_array(image_bytes: bytes):
    """Decode raw bytes to a numpy RGB array that DeepFace can consume."""
    from PIL import Image
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.array(pil_img)


def _normalise(embedding: list[Any]) -> list[float]:
    """Return a plain list[float] with L2-normalised values."""
    arr = np.array(embedding, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()
