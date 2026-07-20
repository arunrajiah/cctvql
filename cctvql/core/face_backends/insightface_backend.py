"""
InsightFace backend.

Uses the ``insightface`` library to produce 512-dimensional ArcFace embeddings
with optional GPU support via ONNX Runtime.
Install with: ``pip install cctvql[insightface]``

Supported models (pass as ``model_name`` kwarg to the constructor):
  buffalo_l (default, highest accuracy), buffalo_m, buffalo_s, buffalo_sc

Distance metric: cosine. Lower is more similar; threshold ~0.40.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from cctvql.core.face_backends.base import BaseFaceBackend

logger = logging.getLogger(__name__)

# Cosine tolerance: 0.40 is consistent with the DeepFace ArcFace threshold
# and works well for buffalo_l in controlled lighting conditions.
_DEFAULT_COSINE_TOLERANCE = 0.40
_EMBEDDING_DIM = 512


class InsightFaceBackend(BaseFaceBackend):
    """
    InsightFace backend using ONNX Runtime for inference.

    Args:
        model_name: InsightFace model pack to use (default: ``"buffalo_l"``).
        det_size:   Detection input resolution as ``(width, height)`` tuple
                    (default: ``(640, 640)``).
        providers:  ONNX Runtime execution providers. Defaults to
                    ``["CUDAExecutionProvider", "CPUExecutionProvider"]``
                    so GPU is used when available and CPU is the fallback.
    """

    def __init__(
        self,
        model_name: str = "buffalo_l",
        det_size: tuple[int, int] = (640, 640),
        providers: list[str] | None = None,
    ) -> None:
        self._model_name = model_name
        self._det_size = det_size
        self._providers = providers or [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        self.tolerance = _DEFAULT_COSINE_TOLERANCE
        self.embedding_dim = _EMBEDDING_DIM
        self._app: Any = None  # lazy-initialised on first use

    @property
    def available(self) -> bool:
        try:
            import insightface  # noqa: F401

            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_app(self) -> Any:
        """Return the FaceAnalysis app, initialising it on first call."""
        if self._app is None:
            from insightface.app import FaceAnalysis  # type: ignore[import]

            app = FaceAnalysis(
                name=self._model_name,
                providers=self._providers,
            )
            app.prepare(ctx_id=0, det_size=self._det_size)
            self._app = app
        return self._app

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_single(self, image_bytes: bytes) -> list[float]:
        """Extract the embedding for the one face in the image (for enrollment)."""
        if not self.available:
            raise ImportError("insightface is not installed. Run: pip install cctvql[insightface]")
        img_array = _bytes_to_bgr_array(image_bytes)
        faces = self._get_app().get(img_array)
        if len(faces) == 0:
            raise ValueError(
                "No face detected in the enrollment image. "
                "Please provide a clear, well-lit frontal photo."
            )
        if len(faces) > 1:
            raise ValueError(
                f"{len(faces)} faces detected. "
                "Enrollment requires a photo containing exactly one person."
            )
        return _normalise(faces[0].embedding)

    def detect_and_embed(self, image_bytes: bytes) -> list[list[float]]:
        """Detect all faces and return one embedding per face."""
        if not self.available:
            raise ImportError("insightface is not installed. Run: pip install cctvql[insightface]")
        img_array = _bytes_to_bgr_array(image_bytes)
        try:
            faces = self._get_app().get(img_array)
        except Exception as exc:
            logger.warning("InsightFace.get failed: %s", exc)
            return []
        return [_normalise(f.embedding) for f in faces]

    def compare(
        self,
        known_embeddings: list[list[float]],
        query_embedding: list[float],
    ) -> list[float]:
        """
        Compute cosine distances between *known_embeddings* and *query_embedding*.

        Cosine distance = 1 - cosine_similarity, so 0.0 is a perfect match
        and 1.0 is maximally dissimilar.
        """
        if not known_embeddings:
            return []
        import numpy as np

        known = np.array(known_embeddings, dtype=np.float32)
        query = np.array(query_embedding, dtype=np.float32)

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


def _bytes_to_bgr_array(image_bytes: bytes) -> Any:
    """Decode raw bytes to a numpy BGR array that InsightFace expects."""
    import numpy as np
    from PIL import Image

    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    rgb = np.array(pil_img)
    # InsightFace uses OpenCV BGR convention
    return rgb[:, :, ::-1]


def _normalise(embedding: Any) -> list[float]:
    """Return a plain list[float] with L2-normalised values."""
    import numpy as np

    arr = np.array(embedding, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()
