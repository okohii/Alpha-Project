"""Preparação de texto e perfil de entrega vocal.

``DeliveryProfile`` descreve COMO o texto deve ser falado, em parâmetros que o
Kokoro realmente suporta. ``DeliveryProcessor`` prepara o texto para a síntese
sem alterar o significado, removendo markup interno e agrupando em chunks por
sentença (nunca cortando palavras).

Kokoro 0.9.4 não expõe parâmetro de pausa nativo: as pausas são controladas
pela estratégia de segmentação (cada segmento ganha a pausa acústica natural
entre sentenças). ``pre_pause_s``/``post_pause_s`` ficam reservados para UIs
futuras (avatar), não sendo aplicados na síntese.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.speech.cleaning import clean_markdown_artifacts


class ChunkStrategy(StrEnum):
    """Estratégia de segmentação enviada ao Kokoro.

    - ``relaxed``: um único segmento (comportamento atual); o Kokoro divide
      internamente textos longos por fronteira de sentença (~400 chars).
    - ``standard``: quebra por sentença, agrupando frases curtas.
    - ``paused``: quebra por sentença E dois-pontos/ponto-e-vírgula (frases
      menores, mais pausas entre segmentos).
    """

    relaxed = "relaxed"
    standard = "standard"
    paused = "paused"


_INTERNAL_TAG_RE = re.compile(r"\[[^\]]*\]")
_WHITESPACE_RE = re.compile(r"\s+")

# Fronteira de sentença: pontuação final seguida de espaço. Âncoras evitam
# quebrar abreviações como "Sr." quando não seguidas de espaço (finais).
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[:;])\s+")

# Sentenças tão curtas que ficam mais naturais anexadas à próxima
# (ex.: "Sim.", "Entendi."). Aplicado apenas em ``standard``.
_SHORT_MERGE_THRESHOLD = 18
_HARD_SEGMENT_CAP = 460
_RELAXED_SINGLE_CAP = 380


@dataclass(slots=True)
class DeliveryProfile:
    """Como o texto deve ser falado (parâmetros reais do Kokoro).

    Campos efetivamente aplicados na síntese: ``speed``, ``voice`` e
    ``chunk_strategy`` (via segmentos enviados ao pipeline). ``pause_scale``
    orienta o ``DeliveryProcessor``; os campos ``pre_pause_s``/``post_pause_s``
    são reservados para consumo futuro por avatar/UI.
    """

    speed: float = 1.0
    pause_scale: float = 1.0
    chunk_strategy: ChunkStrategy | str = ChunkStrategy.relaxed
    voice: str | None = None
    pre_pause_s: float = 0.0
    post_pause_s: float = 0.0

    def __post_init__(self) -> None:
        try:
            self.speed = float(self.speed)
        except (TypeError, ValueError):
            self.speed = 1.0
        if self.speed <= 0 or self.speed != self.speed:
            self.speed = 1.0
        try:
            self.pause_scale = float(self.pause_scale)
        except (TypeError, ValueError):
            self.pause_scale = 1.0
        self.pause_scale = min(max(self.pause_scale, 0.5), 2.0)
        try:
            self.chunk_strategy = ChunkStrategy(str(self.chunk_strategy))
        except ValueError:
            self.chunk_strategy = ChunkStrategy.relaxed
        self.pre_pause_s = max(0.0, float(self.pre_pause_s or 0.0))
        self.post_pause_s = max(0.0, float(self.post_pause_s or 0.0))
        self.voice = str(self.voice) if self.voice else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed": self.speed,
            "pause_scale": self.pause_scale,
            "chunk_strategy": self.chunk_strategy.value,
            "voice": self.voice,
            "pre_pause_s": self.pre_pause_s,
            "post_pause_s": self.post_pause_s,
        }


class DeliveryProcessor:
    """Prepara o texto e segmenta por sentença, preservando significado."""

    def prepare(self, text: str) -> str:
        """Remove markup interno e normaliza o texto para a fala.

        - remove tags internas como ``[happy]`` (nunca devem chegar ao TTS);
        - remove artefatos de markdown (``**``, ``#``, backticks, links);
        - preserva acentuação, pontuação relevante e o significado.
        """
        if not text:
            return ""
        cleaned = clean_markdown_artifacts(text)
        cleaned = _INTERNAL_TAG_RE.sub(" ", cleaned)
        cleaned = _WHITESPACE_RE.sub(" ", cleaned)
        return cleaned.strip()

    def chunk(self, text: str, profile: DeliveryProfile | None = None) -> list[str]:
        """Segmenta o texto preparado conforme a estratégia do perfil.

        Nunca divide no meio de palavras nem descarta pontuação final. No modo
        ``relaxed`` (padrão), o texto volta como um único segmento, mantendo o
        comportamento atual de síntese.

        - ``standard``: um chunk por sentença (frases muito curtas são
          anexadas à seguinte para não gerar cortes artificiais).
        - ``paused``: um chunk por oração (sentença dividida também em
          dois-pontos e ponto-e-vírgula → mais pausas entre segmentos).
        """
        profile = profile or DeliveryProfile()
        prepared = self.prepare(text)
        if not prepared:
            return []
        if profile.chunk_strategy == ChunkStrategy.relaxed:
            if len(prepared) <= _RELAXED_SINGLE_CAP:
                return [prepared]
            strategy = ChunkStrategy.standard
        else:
            strategy = profile.chunk_strategy

        units = self._split_sentences(prepared)
        if strategy == ChunkStrategy.paused:
            units = self._split_clauses(units)

        chunks: list[str] = []
        pending = ""
        index = 0
        while index < len(units):
            unit = units[index].strip()
            index += 1
            if not unit:
                continue
            if len(unit) > _HARD_SEGMENT_CAP:
                chunks.append(unit)
                continue
            if strategy == ChunkStrategy.standard and len(unit) <= _SHORT_MERGE_THRESHOLD:
                pending = unit
                continue
            if pending:
                unit = f"{pending} {unit}"
                pending = ""
            chunks.append(unit)
        if pending:
            if chunks:
                chunks[-1] = f"{chunks[-1]} {pending}"
            else:
                chunks.append(pending)
        return chunks

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        segments = re.split(r"\n+", text.strip())
        sentences: list[str] = []
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            sentences.extend(_SENTENCE_BOUNDARY_RE.split(segment))
        return sentences

    @staticmethod
    def _split_clauses(units: list[str]) -> list[str]:
        clauses: list[str] = []
        for unit in units:
            clauses.extend(_CLAUSE_BOUNDARY_RE.split(unit))
        return clauses

    def prepare_and_chunk(
        self, text: str, profile: DeliveryProfile | None = None
    ) -> tuple[str, list[str]]:
        """Atalho: retorna o texto preparado e os chunks já segmentados."""
        prepared = self.prepare(text)
        profile = profile or DeliveryProfile()
        return prepared, self.chunk(prepared, profile)