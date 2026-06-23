"""Abstract base class for all cctvQL face recognition backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseFaceBackend(ABC):
    """
    Common interface for face embedding and comparison.

    Every backend must implement:
      - embed_single    — enrolment: one face per image
      - detect_and_embed — recognition: all faces in an image
      - compare         — distance between a batch of known embeddings and one query
      - available       — True when the underlying library is installed

    The distance metric is backend-specific:
      - DlibBackend uses Euclidean distance (lower = more similar)
      - DeepFaceBackend uses cosine distance (lower = more similar)

    ``tolerance`` is the maximum distance to count as a match.
    ``embedding_dim`` is informational only.
    """

    #: Default distance threshold for a "match".
    tolerance: float = 0.6

    #: Dimensionality of the embedding vectors produced by this backend.
    embedding_dim: int = 128

    @property
    @abstractmethod
    def available(self) -> bool:
        """True if the underlying library is installed and usable."""
        ...

    @abstractmethod
    def embed_single(self, image_bytes: bytes) -> list[float]:
        """
        Compute the embedding for the one face in *image_bytes*.

        Raises:
            ImportError: If the required library is not installed.
            ValueError:  If zero or more than one face is detected.
        """
        ...

    @abstractmethod
    def detect_and_embed(self, image_bytes: bytes) -> list[list[float]]:
        """
        Detect all faces in *image_bytes* and return one embedding per face.

        Returns an empty list when no faces are found.

        Raises:
            ImportError: If the required library is not installed.
        """
        ...

    @abstractmethod
    def compare(
        self,
        known_embeddings: list[list[float]],
        query_embedding: list[float],
    ) -> list[float]:
        """
        Compute pairwise distances between *known_embeddings* and *query_embedding*.

        Returns:
            A list of distances, one per known embedding.
            Lower is more similar.
        """
        ...
