"""
Dlib / face_recognition backend.

Uses the ``face_recognition`` library (which wraps dlib's ResNet-based
face recognition model) to produce 128-dimensional face embeddings.
Install with: ``pip install cctvql[face]``
"""

from __future__ import annotations

import io
import logging

from cctvql.core.face_backends.base import BaseFaceBackend

logger = logging.getLogger(__name__)

try:
    import face_recognition as _fr  # type: ignore[import]
    _AVAILABLE = True
except ImportError:
    _fr = None  # type: ignore[assignment]
    _AVAILABLE = False


class DlibBackend(BaseFaceBackend):
    """
    face_recognition (dlib) backend.

    Produces 128-d Euclidean-space embeddings.
    Default tolerance: 0.6 (dlib's recommended threshold).
    """

    tolerance: float = 0.6
    embedding_dim: int = 128

    @property
    def available(self) -> bool:
        return _AVAILABLE

    def embed_single(self, image_bytes: bytes) -> list[float]:
        if not _AVAILABLE:
            raise ImportError(
                "face_recognition is not installed. Run: pip install cctvql[face]"
            )
        img = _load_image(image_bytes)
        locations = _fr.face_locations(img, model="hog")
        if len(locations) == 0:
            raise ValueError(
                "No face detected in the enrollment image. "
                "Please provide a clear, well-lit frontal photo."
            )
        if len(locations) > 1:
            raise ValueError(
                f"{len(locations)} faces detected. "
                "Enrollment requires a photo containing exactly one person."
            )
        encodings = _fr.face_encodings(img, locations)
        return [float(v) for v in encodings[0]]

    def detect_and_embed(self, image_bytes: bytes) -> list[list[float]]:
        if not _AVAILABLE:
            raise ImportError(
                "face_recognition is not installed. Run: pip install cctvql[face]"
            )
        img = _load_image(image_bytes)
        locations = _fr.face_locations(img, model="hog")
        if not locations:
            return []
        encodings = _fr.face_encodings(img, locations)
        return [[float(v) for v in enc] for enc in encodings]

    def compare(
        self,
        known_embeddings: list[list[float]],
        query_embedding: list[float],
    ) -> list[float]:
        if not _AVAILABLE:
            raise ImportError(
                "face_recognition is not installed. Run: pip install cctvql[face]"
            )
        import numpy as np
        distances = _fr.face_distance(known_embeddings, query_embedding)
        return [float(d) for d in distances]


def _load_image(image_bytes: bytes):
    """Decode bytes to a numpy RGB array."""
    from PIL import Image
    import numpy as np
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.array(pil_img)
