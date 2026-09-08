from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = text.lower().split()
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for index in range(0, len(digest), 2):
                slot = int.from_bytes(digest[index:index + 2], "little") % self.dimensions
                vector[slot] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
