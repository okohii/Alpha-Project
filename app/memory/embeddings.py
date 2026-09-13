from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod

_TOKEN_RE = re.compile(r"[a-zA-Z\u00C0-\u017F0-9]+")


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class LocalEmbeddingProvider(EmbeddingProvider):
    """Embedding local determinístico baseado em hashing de tokens e n-grams.

    A computação CPU-bound roda no executor padrão para não bloquear o event
    loop durante buscas de memória ou indexação de documentos.
    """

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_sync, text)

    def _embed_sync(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN_RE.findall((text or "").lower())
        if not tokens:
            return vector
        for token in tokens:
            self._add_hashed(vector, token)
        for index in range(len(tokens) - 1):
            self._add_hashed(vector, f"{tokens[index]} {tokens[index + 1]}")
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    @staticmethod
    def _slot(token: str, dimensions: int) -> int:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "little") % dimensions

    def _add_hashed(self, vector: list[float], token: str) -> None:
        slot = self._slot(token, self.dimensions)
        vector[slot] += 1.0
