"""
cctvQL Face Registry
--------------------
Enroll known faces and recognise them across CCTV event snapshots.

The registry stores per-person face embeddings (128-d vectors) in SQLite.
Recognition is performed by the ``face_recognition`` library (optional
dependency — ``pip install cctvql[face]``).  When the library is not
installed the module degrades gracefully: enrolment stores the raw image
bytes and all ``recognise_*`` calls return an empty list with a logged
warning.

Typical flow:
  1. Operator enrolls a face:
        await registry.enroll("Alice", image_bytes)
  2. An event fires with a snapshot URL.
  3. Caller fetches the snapshot bytes and calls:
        matches = await registry.recognise_image(image_bytes)
        # → [Match(face_id=..., name="Alice", confidence=0.92), ...]
  4. Event metadata is enriched with the matched names.
"""

from __future__ import annotations

import base64
import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependency
# ---------------------------------------------------------------------------

try:
    import face_recognition as _fr  # type: ignore[import]

    _FR_AVAILABLE = True
    logger.debug("face_recognition library loaded — recognition enabled.")
except ImportError:
    _fr = None  # type: ignore[assignment]
    _FR_AVAILABLE = False
    logger.warning(
        "face_recognition library not installed. "
        "Install it with: pip install cctvql[face]\n"
        "Face enrolment will store images but recognition will return no matches."
    )


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
    recognition_available: bool = _FR_AVAILABLE


# ---------------------------------------------------------------------------
# FaceRegistry
# ---------------------------------------------------------------------------


class FaceRegistry:
    """
    Async facade for face enrolment and recognition backed by SQLite.

    Args:
        db: An open ``cctvql.core.database.Database`` instance.
            The registry uses it for persistent storage of enrollments
            and their embeddings.
    """

    # Default Euclidean-distance threshold (face_recognition uses distance,
    # not similarity; 0.6 is the library's recommended default).
    DEFAULT_TOLERANCE: float = 0.6

    def __init__(self, db: Any) -> None:
        self._db = db
        # In-memory cache: face_id → (name, label, embedding | None)
        self._cache: dict[str, tuple[str, str, list[float] | None]] = {}
        self._cache_loaded = False

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
                import json

                try:
                    embedding = json.loads(row["embedding"])
                except Exception:
                    pass
            self._cache[row["face_id"]] = (row["name"], row["label"], embedding)
        self._cache_loaded = True
        logger.debug("FaceRegistry cache loaded: %d enrollment(s).", len(self._cache))

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
            ValueError: If no face is detected in the image, or if more than
                        one face is present and the library is available.
        """
        embedding: list[float] | None = None

        if _FR_AVAILABLE:
            embedding = _extract_embedding(image_bytes)

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

        # Update cache
        self._cache[face_id] = (name, label, embedding)
        logger.info("Enrolled face '%s' (id=%s).", name, face_id)

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
        tolerance: float = DEFAULT_TOLERANCE,
    ) -> RecognitionResult:
        """
        Find enrolled faces in the given image.

        Args:
            image_bytes: Raw image bytes (JPEG or PNG).
            tolerance:   Maximum face distance to count as a match.
                         Lower = stricter (default 0.6 per face_recognition docs).

        Returns:
            RecognitionResult with a list of FaceMatch objects sorted by
            confidence (highest first).
        """
        if not _FR_AVAILABLE:
            return RecognitionResult(recognition_available=False)

        if not self._cache_loaded:
            await self.load_cache()

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

        # Detect faces in the query image
        try:
            img_array = _load_image(image_bytes)
        except Exception as exc:
            logger.warning("Could not decode image for recognition: %s", exc)
            return RecognitionResult(recognition_available=True)

        face_locations = _fr.face_locations(img_array, model="hog")
        face_count = len(face_locations)

        if face_count == 0:
            return RecognitionResult(face_count=0, recognition_available=True)

        query_embeddings = _fr.face_encodings(img_array, face_locations)

        matches: list[FaceMatch] = []
        seen: set[str] = set()  # deduplicate per face_id within this image

        import numpy as np  # numpy is a face_recognition transitive dep

        for query_emb in query_embeddings:
            distances = _fr.face_distance(known_embeddings, query_emb)
            for i, dist in enumerate(distances):
                if dist <= tolerance:
                    fid = known_ids[i]
                    if fid in seen:
                        continue
                    seen.add(fid)
                    confidence = float(np.clip(1.0 - dist / tolerance, 0.0, 1.0))
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
        tolerance: float = DEFAULT_TOLERANCE,
    ) -> RecognitionResult:
        """
        Fetch an image by URL and run recognition on it.

        Args:
            image_url: Publicly reachable (or LAN-reachable) URL.
            tolerance: Matching threshold (default 0.6).

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
            return RecognitionResult(recognition_available=_FR_AVAILABLE)

        return await self.recognise_image(image_bytes, tolerance=tolerance)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_embedding(image_bytes: bytes) -> list[float]:
    """
    Compute the 128-d face embedding for the dominant face in the image.

    Raises:
        ValueError: If no face is found or more than one face is present.
    """
    img = _load_image(image_bytes)
    locations = _fr.face_locations(img, model="hog")
    if len(locations) == 0:
        raise ValueError(
            "No face detected in the enrollment image. "
            "Please provide a clear, well-lit frontal photo."
        )
    if len(locations) > 1:
        raise ValueError(
            f"{len(locations)} faces detected in the enrollment image. "
            "Please provide a photo containing exactly one person."
        )
    encodings = _fr.face_encodings(img, locations)
    return [float(v) for v in encodings[0]]


def _load_image(image_bytes: bytes):  # type: ignore[return]
    """Decode raw bytes into a numpy array suitable for face_recognition."""
    from PIL import Image  # Pillow — transitive dep of face_recognition

    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    import numpy as np

    return np.array(pil_img)


def _to_b64(image_bytes: bytes, content_type: str) -> str:
    """Return a data-URI base64 string for thumbnail storage."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{content_type};base64,{b64}"


def _embedding_to_json(embedding: list[float] | None) -> str | None:
    """Serialise an embedding to a compact JSON string for SQLite storage."""
    if embedding is None:
        return None
    import json

    return json.dumps(embedding, separators=(",", ":"))
