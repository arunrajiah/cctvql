"""
cctvQL pluggable face recognition backends.

Backends expose a uniform interface for embedding extraction and distance
comparison, allowing face recognition to work with different libraries
(dlib / face_recognition, DeepFace, InsightFace) without changing FaceRegistry.

Usage
-----
    from cctvql.core.face_backends import get_backend
    backend = get_backend("deepface")          # or "dlib" (default)
    embedding = backend.embed_single(image_bytes)
    distances = backend.compare([known_emb], query_emb)
"""

from __future__ import annotations

from cctvql.core.face_backends.base import BaseFaceBackend
from cctvql.core.face_backends.deepface_backend import DeepFaceBackend
from cctvql.core.face_backends.dlib_backend import DlibBackend

_REGISTRY: dict[str, type[BaseFaceBackend]] = {
    "dlib": DlibBackend,
    "deepface": DeepFaceBackend,
}


def get_backend(name: str = "dlib") -> BaseFaceBackend:
    """
    Return an instantiated face backend by name.

    Args:
        name: ``"dlib"`` (default) or ``"deepface"``.

    Raises:
        ValueError: If the backend name is not recognised.
    """
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown face backend '{name}'. Available: {list(_REGISTRY)}"
        )
    return cls()


__all__ = ["BaseFaceBackend", "DlibBackend", "DeepFaceBackend", "get_backend"]
