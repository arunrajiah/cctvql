"""
cctvQL Face Registry
--------------------
Enroll known faces and recognise them across CCTV event snapshots.

The registry stores per-person face embeddings in SQLite and uses a
pluggable backend for embedding extraction and comparison:

  - ``dlib``     (default) — face_recognition library; 128-d Euclidean space
  - ``deepface`` — DeepFace library; ArcFace 512-d cosine space, GPU support

Install backends:
  pip install cctvql[face]      # dlib (default)
  pip install cctvql[deepface]  # DeepFace / ArcFace

Typical flow:
  1. Operator enrolls a face:
        await registry.enroll("Alice", image_bytes)
  2. An event fires with a snapshot URL.
  3. Caller fetches the snapshot bytes and calls:
        matches = await registry.recognise_image(image_bytes)
        # → [Match(face_id=..., name="Alice", confidence=0.92), ...]
  4. Event metadata is enriched with the matched names.

When no backend library is installed, enrolment stores the raw image and
all recognise_* calls return an empty list with a clear error message.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from cctvql.core.face_backends import BaseFaceBackend, DlibBackend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data-classes
# ---------------------------------------------------------------------------


@dataclass
class FaceEnrollment:
    """A stored face record."""

    face_id: str
    name: str
    label: str  # optional free-text label / role (e.g. "employee", "resident")
    created_at: str
    image_b64: str  # base64-encoded JPEG thumbnail stored for reference


@dataclass
class FaceMatch:
    """A single recognition hit returned by ``recognise_image``."""

    face_id: str
    name: str
    label: str
    confidence: float  # 0.0 – 1.0; higher is better


@dataclass
class RecognitionResult:
    """Full result for one call to ``recognise_image``."""

    matches: list[FaceMatch] = field(default_factory=list)
    face_count: int = 0  # how many faces the detector found in the image
    recognition_available: bool = True


# ---------------------------------------------------------------------------
# FaceRegistry
# ---------------------------------------------------------------------------


class FaceRegistry:
    """
    Async facade for face enrolment and recognition backed by SQLite.

    Args:
        db:      An open ``cctvql.core.database.Database`` instance.
        backend: A ``BaseFaceBackend`` instance.  Defaults to ``DlibBackend``
                 (uses the ``face_recognition`` library).  Pass a
                 ``DeepFaceBackend`` instance for GPU-accelerated ArcFace
                 recognition.
    """

    def __init__(self, db: Any, backend: BaseFaceBackend | None = None) -> None:
        self._db = db
        self._backend: BaseFaceBackend = backend or DlibBackend()
        # In-memory cache: face_id → (name, label, embedding | None)
        self._cache: dict[str, tuple[str, str, list[float] | None]] = {}
        self._cache_loaded = False

    @property
    def backend(self) -> BaseFaceBackend:
        return self._backend

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_cache(self) -> None:
        """Load all enrollments (with embeddings) from the database into memory."""
        rows = await self._db.list_face_enrollments()
        self._cache.clear()
        for row in rows:
            embedding: list[float] | None = None
            if row.get("embedding"):
                try:
                    embedding = json.loads(row["embedding"])
                except Exception:
                    pass
            self._cache[row["face_id"]] = (row["name"], row["label"], embedding)
        self._cache_loaded = True
        logger.debug(
            "FaceRegistry cache loaded: %d enrollment(s) [backend=%s].",
            len(self._cache),
            type(self._backend).__name__,
        )

    # ------------------------------------------------------------------
    # Enrolment
    # ------------------------------------------------------------------

    async def enroll(
        self,
        name: str,
        image_bytes: bytes,
        label: str = "",
        content_type: str = "image/jpeg",
    ) -> FaceEnrollment:
        """
        Enrol a new face.

        Args:
            name:         Human-readable name (e.g. "Alice Smith").
            image_bytes:  Raw image bytes (JPEG or PNG) containing exactly one face.
            label:        Optional free-text label (e.g. "resident", "employee").
            content_type: MIME type of the image bytes.

        Returns:
            The newly created FaceEnrollment.

        Raises:
            ValueError: If no face is detected, or more than one face is present.
        """
        embedding: list[float] | None = None

        if self._backend.available:
            try:
                embedding = self._backend.embed_single(image_bytes)
            except ValueError:
                raise  # propagate "no face / multiple faces" errors
            except Exception as exc:
                logger.warning("embed_single failed (%s), storing image only.", exc)

        face_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        image_b64 = _to_b64(image_bytes, content_type)

        await self._db.save_face_enrollment(
            face_id=face_id,
            name=name,
            label=label,
            image_b64=image_b64,
            embedding=_embedding_to_json(embedding),
            created_at=now,
        )

        self._cache[face_id] = (name, label, embedding)
        logger.info("Enrolled face '%s' (id=%s, backend=%s).", name, face_id, type(self._backend).__name__)

        return FaceEnrollment(
            face_id=face_id,
            name=name,
            label=label,
            created_at=now,
            image_b64=image_b64,
        )

    async def delete_enrollment(self, face_id: str) -> bool:
        """
        Remove a face enrollment by ID.

        Returns:
            True if the record existed and was deleted, False otherwise.
        """
        existed = await self._db.delete_face_enrollment(face_id)
        self._cache.pop(face_id, None)
        if existed:
            logger.info("Deleted face enrollment %s.", face_id)
        return existed

    async def list_enrollments(self) -> list[FaceEnrollment]:
        """Return all enrolled faces (without embeddings — embeddings are large)."""
        rows = await self._db.list_face_enrollments()
        return [
            FaceEnrollment(
                face_id=row["face_id"],
                name=row["name"],
                label=row["label"],
                created_at=row["created_at"],
                image_b64=row["image_b64"],
            )
            for row in rows
        ]

    async def get_enrollment(self, face_id: str) -> FaceEnrollment | None:
        """Fetch a single enrollment by ID, or None if not found."""
        row = await self._db.get_face_enrollment(face_id)
        if row is None:
            return None
        return FaceEnrollment(
            face_id=row["face_id"],
            name=row["name"],
            label=row["label"],
            created_at=row["created_at"],
            image_b64=row["image_b64"],
        )

    # ------------------------------------------------------------------
    # Recognition
    # ------------------------------------------------------------------

    async def recognise_image(
        self,
        image_bytes: bytes,
        tolerance: float | None = None,
    ) -> RecognitionResult:
        """
        Find enrolled faces in the given image.

        Args:
            image_bytes: Raw image bytes (JPEG or PNG).
            tolerance:   Maximum distance to count as a match. Falls back to
                         the backend's default if not supplied.

        Returns:
            RecognitionResult with matches sorted by confidence (highest first).
        """
        if not self._backend.available:
            logger.warning(
                "Face recognition backend '%s' is not available. "
                "Install the required library (see pyproject.toml optional deps).",
                type(self._backend).__name__,
            )
            return RecognitionResult(recognition_available=False)

        if not self._cache_loaded:
            await self.load_cache()

        tol = tolerance if tolerance is not None else self._backend.tolerance

        # Build known-faces arrays from cache (skip entries with no embedding)
        known_ids: list[str] = []
        known_names: list[str] = []
        known_labels: list[str] = []
        known_embeddings: list[list[float]] = []

        for fid, (name, label, emb) in self._cache.items():
            if emb is not None:
                known_ids.append(fid)
                known_names.append(name)
                known_labels.append(label)
                known_embeddings.append(emb)

        if not known_embeddings:
            return RecognitionResult(recognition_available=True)

        # Detect all faces in the query image
        try:
            query_embeddings = self._backend.detect_and_embed(image_bytes)
        except Exception as exc:
            logger.warning("detect_and_embed failed: %s", exc)
            return RecognitionResult(recognition_available=True)

        face_count = len(query_embeddings)
        if face_count == 0:
            return RecognitionResult(face_count=0, recognition_available=True)

        matches: list[FaceMatch] = []
        seen: set[str] = set()  # deduplicate per face_id within this image

        for query_emb in query_embeddings:
            distances = self._backend.compare(known_embeddings, query_emb)
            for i, dist in enumerate(distances):
                if dist <= tol:
                    fid = known_ids[i]
                    if fid in seen:
                        continue
                    seen.add(fid)
                    confidence = float(np.clip(1.0 - dist / tol, 0.0, 1.0))
                    matches.append(
                        FaceMatch(
                            face_id=fid,
                            name=known_names[i],
                            label=known_labels[i],
                            confidence=round(confidence, 3),
                        )
                    )

        matches.sort(key=lambda m: m.confidence, reverse=True)
        return RecognitionResult(
            matches=matches,
            face_count=face_count,
            recognition_available=True,
        )

    async def recognise_url(
        self,
        image_url: str,
        tolerance: float | None = None,
    ) -> RecognitionResult:
        """
        Fetch an image by URL and run recognition on it.

        Args:
            image_url: Publicly reachable (or LAN-reachable) URL.
            tolerance: Matching threshold; defaults to backend's tolerance.

        Returns:
            RecognitionResult, or RecognitionResult(recognition_available=False)
            on fetch failure.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                image_bytes = resp.content
        except Exception as exc:
            logger.warning("Failed to fetch image for recognition from %s: %s", image_url, exc)
            return RecognitionResult(recognition_available=self._backend.available)

        return await self.recognise_image(image_bytes, tolerance=tolerance)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_b64(image_bytes: bytes, content_type: str) -> str:
    """Return a data-URI base64 string for thumbnail storage."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{content_type};base64,{b64}"


def _embedding_to_json(embedding: list[float] | None) -> str | None:
    """Serialise an embedding to a compact JSON string for SQLite storage."""
    if embedding is None:
        return None
    return json.dumps(embedding, separators=(",", ":"))
