"""Camada de emoção vocal determinística.

Separa o *estado emocional* (``EmotionState``) da *entrega vocal*
(``DeliveryProfile``). A emoção é derivada do texto de forma determinística
(léxico + prosódia textual), sempre validada contra uma *allowlist*, e nunca
chega crua ao TTS — o Kokoro recebe apenas parâmetros reais (velocidade, voz,
segmentação).

Nenhum modelo de IA extra é usado; o LLM não envia parâmetros ao TTS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.config import get_settings
from app.speech.delivery import ChunkStrategy, DeliveryProfile


class Emotion(StrEnum):
    """Allowlist de emoções suportadas.

    Valores inválidos vindos de fora caem em ``neutral`` (fallback seguro).
    Estender com novos membros não quebra o TTS: os parâmetros do Kokoro são
    derivados por tabela no ``EmotionController``.
    """

    neutral = "neutral"
    happy = "happy"
    excited = "excited"
    curious = "curious"
    concerned = "concerned"
    empathetic = "empathetic"
    sad = "sad"


_KEY_RE = re.compile(r"[^a-z0-9_]+")


def _sanitize_emotion(value: Any) -> Emotion:
    """Normaliza uma entrada arbitrária para um membro válido de ``Emotion``.

    Ex.: ``"SUPER_HAPPY!!!!!"`` → ``neutral``; ``" happy "`` → ``happy``.
    """
    if isinstance(value, Emotion):
        return value
    if value is None:
        return Emotion.neutral
    cleaned = _KEY_RE.sub("", str(value).strip().lower())
    try:
        return Emotion(cleaned)
    except ValueError:
        return Emotion.neutral


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


@dataclass(slots=True)
class EmotionState:
    """Estado emocional tipado, válido e clampado.

    - ``emotion``: membro de ``Emotion``; entradas inválidas caem em ``neutral``.
    - ``intensity``: ``0.0`` a ``tts_emotion_max_intensity`` (clamp automático).
    - ``confidence``: grau de certeza da detecção, ``0.0`` a ``1.0``.
    - ``source``: origem da emoção — ``"explicit"`` (pedido direto do usuário)
      ou ``"derived"`` (heurística sobre o texto).
    """

    emotion: Emotion | str = Emotion.neutral
    intensity: float = 0.0
    confidence: float = 0.0
    source: str = "derived"

    def __post_init__(self) -> None:
        max_intensity = get_settings().tts_emotion_max_intensity
        self.emotion = _sanitize_emotion(self.emotion)
        self.intensity = min(max(0.0, _to_float(self.intensity)), max(max_intensity, 0.0))
        self.confidence = min(max(0.0, _to_float(self.confidence)), 1.0)
        if self.source not in ("explicit", "derived"):
            self.source = "derived"

    def to_dict(self) -> dict[str, Any]:
        return {
            "emotion": self.emotion.value,
            "intensity": self.intensity,
            "confidence": self.confidence,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EmotionState:
        if not data:
            return EmotionState()
        return cls(
            emotion=data.get("emotion"),
            intensity=data.get("intensity", 0.0),
            confidence=data.get("confidence", 0.0),
            source=data.get("source", "derived"),
        )


# Pistas positivas/negativas por emoção (gramaticalidade preservada: a
# detecção é apenas para a entrega vocal; o texto não é alterado).
_CUES: dict[str, tuple[str, ...]] = {
    Emotion.happy: (
        "ótimo",
        "ótima",
        "excelente",
        "perfeito",
        "maravilhos",
        "incrível",
        "conseguimos",
        "legal",
        "uau",
        "show",
        "sucesso",
        "adoro",
        "adorei",
        "amo",
        "top",
        "sensacional",
        "que alegria",
        "bom demais",
        "boa",
    ),
    Emotion.excited: (
        "finalmente",
        "demais",
        "agora mesmo",
        "isso agora",
        "vamos lá",
        "vamos ver",
        "uau",
        "inacreditável",
        "espetacular",
        "mandou bem",
        "arrasou",
        "na hora",
        "sensacional",
    ),
    Emotion.curious: (
        "será",
        "vamos descobrir",
        "descobrir",
        "investigar",
        "averiguar",
        "como funciona",
        "onde está",
        "qual é",
        "o que é",
        "por quê",
        "me diga mais",
        "deixa eu ver",
        "vamos entender",
        "curioso",
        "curiosa",
        "interessante",
    ),
    Emotion.concerned: (
        "atenção",
        "cuidado",
        "preocupado",
        "preocupada",
        "problema",
        "não encontrei",
        "não consegui",
        "falhou",
        "erro",
        "risco",
        "com calma",
        "devagar",
        "verificar antes",
        "antes de continuar",
        "vamos verificar",
        "suspeito",
        "cautela",
        "algo estranho",
        "cuidadoso",
    ),
    Emotion.empathetic: (
        "sinto muito",
        "lamento",
        "entendo",
        "compreendo",
        "fique tranquilo",
        "tranquilo",
        "vai dar certo",
        "estou aqui",
        "vamos resolver juntos",
        "juntos",
        "desculpa",
        "perdão",
        "força",
        "respira",
        "pode contar",
        "deve estar sendo difícil",
    ),
    Emotion.sad: (
        "infelizmente",
        "que pena",
        "que triste",
        "lamentável",
        "lamentavel",
        "estou triste",
        "fiquei triste",
        "me entristece",
        "pena",
        "não deu",
        "não deu certo",
        "falha",
        "uma pena",
    ),
}

_CAPS_RE = re.compile(r"\b([A-ZÀ-Ú]{3,})\b")
_DOUBLE_EXCLAMATION = re.compile(r"!!")
_MIXED_EXCLAMATION = re.compile(r"!\?|\?!")


def _cue_points(text_lower: str, emotion: Emotion) -> int:
    return sum(1 for cue in _CUES[emotion] if cue in text_lower)


def _excitement_bonus(text: str) -> int:
    caps = len(_CAPS_RE.findall(text))
    bonus = min(caps, 2)
    if _DOUBLE_EXCLAMATION.search(text):
        bonus += 2
    if _MIXED_EXCLAMATION.search(text):
        bonus += 1
    return bonus


def _curiosity_question_bonus(text: str) -> int:
    return min(text.count("?"), 2)


def _intensity(cue_count: int, bonus: int) -> float:
    if cue_count <= 0:
        return 0.0
    base = 0.5 + 0.4 * (cue_count / (cue_count + 1.5))
    adjusted = base + 0.05 * bonus
    return min(max(adjusted, 0.0), 1.0)


def _confidence(cue_count: int) -> float:
    if cue_count <= 0:
        return 0.0
    return round(min(0.99, 0.55 + 0.1 * cue_count), 2)


class EmotionController:
    """Converte emoção em entrega vocal.

    Responsável por:
    - detectar a emoção do texto (determinístico, sem IA extra);
    - resolver o estado em ``DeliveryProfile`` (parâmetros reais do Kokoro);
    - aplicar *decay* simples e previsível entre turnos.

    Não sintetiza áudio, não conhece o agente e não executa ferramentas.
    """

    _SPEED_RANGE: dict[Emotion, tuple[float, float]] = {
        Emotion.neutral: (1.0, 1.0),
        Emotion.happy: (1.03, 1.07),
        Emotion.excited: (1.08, 1.12),
        Emotion.curious: (0.98, 1.02),
        Emotion.concerned: (0.90, 0.96),
        Emotion.empathetic: (0.93, 0.98),
        Emotion.sad: (0.86, 0.92),
    }
    _PAUSE_SCALE: dict[Emotion, float] = {
        Emotion.neutral: 1.0,
        Emotion.happy: 0.96,
        Emotion.excited: 0.90,
        Emotion.curious: 1.05,
        Emotion.concerned: 1.15,
        Emotion.empathetic: 1.10,
        Emotion.sad: 1.20,
    }
    _CHUNK_STRATEGY: dict[Emotion, ChunkStrategy] = {
        Emotion.neutral: ChunkStrategy.relaxed,
        Emotion.happy: ChunkStrategy.standard,
        Emotion.excited: ChunkStrategy.paused,
        Emotion.curious: ChunkStrategy.standard,
        Emotion.concerned: ChunkStrategy.paused,
        Emotion.empathetic: ChunkStrategy.standard,
        Emotion.sad: ChunkStrategy.paused,
    }

    def __init__(self) -> None:
        self._settings = get_settings()

    def detect(self, text: str) -> EmotionState:
        """Deriva ``EmotionState`` do texto de forma determinística."""
        if not text or not text.strip():
            return EmotionState()
        cleaned = " ".join(text.split()).strip()
        lowered = cleaned.lower()

        best_emotion: Emotion = Emotion.neutral
        best_points = 0
        for emotion in Emotion:
            if emotion == Emotion.neutral:
                continue
            points = _cue_points(lowered, emotion)
            if emotion == Emotion.excited:
                points += _excitement_bonus(cleaned)
            elif emotion == Emotion.curious:
                points += _curiosity_question_bonus(cleaned)
            if points > best_points:
                best_emotion = emotion
                best_points = points

        if best_points <= 0 or best_emotion == Emotion.neutral:
            return EmotionState()

        state = EmotionState(
            emotion=best_emotion,
            intensity=round(_intensity(best_points, _excitement_bonus(cleaned)), 2),
            confidence=_confidence(best_points),
        )
        return state

    def resolve(self, text: str) -> EmotionState:
        """Detecta e aplica a emoção padrão quando nada é detectado."""
        state = self.detect(text)
        if state.emotion != Emotion.neutral:
            return state
        default = _sanitize_emotion(self._settings.tts_default_emotion)
        if default == Emotion.neutral:
            return state
        return EmotionState(emotion=default, intensity=0.0)

    def build_profile(self, state: EmotionState | None = None) -> DeliveryProfile:
        """Converte o estado emocional em parâmetros reais de entrega.

        As faixas de velocidade são apenas pontos iniciais — números finos a
        partir do comportamento real do Kokoro local.
        """
        current = state or EmotionState()
        range_low, range_high = self._SPEED_RANGE[current.emotion]
        intensity = min(self._settings.tts_emotion_max_intensity, max(0.0, current.intensity))
        factor = range_low + (range_high - range_low) * intensity
        speed = round(factor * self._settings.tts_speed, 2)
        return DeliveryProfile(
            speed=speed,
            pause_scale=self._PAUSE_SCALE[current.emotion],
            chunk_strategy=self._CHUNK_STRATEGY[current.emotion],
            voice=None,
        )

    def decay(self, current: EmotionState, elapsed_seconds: float) -> EmotionState:
        """Decaimento linear e previsível da intensidade emocional.

        ``tts_emotion_decay_seconds`` é o tempo para zerar: com 60s, uma
        intensidade 0.8 cai para 0.4 após 24s e para 0 (neutral) após 48s.
        """
        if current.emotion == Emotion.neutral or elapsed_seconds <= 0:
            return current
        remaining = current.intensity - (
            elapsed_seconds / max(self._settings.tts_emotion_decay_seconds, 0.001)
        )
        if remaining <= 0:
            return EmotionState()
        return EmotionState(
            emotion=current.emotion,
            intensity=round(remaining, 3),
            confidence=current.confidence,
        )


# ── emoção explícita pedida pelo usuário ─────────────────────────────────────

# Marcadores de "tom" na fala do usuário. A detecção exige um marcador de tom
# perto da palavra de emoção — evita que "não fique triste" (pedido de
# neutralidade) seja lido como "tom triste". "fale/falar <emoção>" também é um
# pedido explícito de tom (ex.: "fale feliz", "agora fale triste").
_TONE_MARKER_RE = re.compile(
    r"\b(?:tom|jeito|estilo|fale|falas|fala|falar)\b|"
    r"de forma|de um jeito|desse jeito|num jeito|num tom"
)

# Negação próxima a um pedido de tom ("não fale triste", "nunca fale assim")
# invalida a detecção explícita — o usuário está pedindo para EVITAR o tom.
_NEGATION_NEAR_TONE_RE = re.compile(r"\b(?:n[aã]o|nunca|jamais)\b")

# Palavras de emoção aceitas quando o usuário pede explicitamente um tom.
_EXPLICIT_EMOTION_WORDS: dict[str, tuple[str, ...]] = {
    Emotion.sad: ("triste", "tristeza", "melancólico", "melancolica", "deprimente"),
    Emotion.happy: ("alegre", "alegria", "feliz", "felicidade", "contente", "divertido"),
    Emotion.excited: (
        "empolgado",
        "eufórico",
        "entusiasmado",
        "animadíssimo",
        "bola cheia",
    ),
    Emotion.curious: ("curioso", "curiosa", "curiosidade", "investigativo"),
    Emotion.concerned: ("preocupado", "preocupada", "preocupação", "cauteloso"),
    Emotion.empathetic: ("empático", "empatica", "acolhedor", "consolador", "solidário"),
}

_TONE_WINDOW_CHARS = 40


def detect_explicit_emotion(text: str | None) -> EmotionState | None:
    """Detecta um pedido explícito de tom de voz (determinístico, sem LLM).

    Ex.: "Agora eu quero um tom bem triste." → ``EmotionState(sad, 0.8, 1.0)``.
    "fale feliz" → ``EmotionState(happy, 0.8, 1.0)``. Sem marcador de tom
    (``tom``/``jeito``/``estilo``/``fale``...) ou sem palavra de emoção próxima,
    retorna ``None`` — a heurística do texto segue valendo.
    """
    if not text or not text.strip():
        return None
    lowered = " ".join(text.split()).lower()
    markers = [match.start() for match in _TONE_MARKER_RE.finditer(lowered)]
    if not markers:
        return None
    best: tuple[str, int] | None = None
    for emotion_name, words in _EXPLICIT_EMOTION_WORDS.items():
        for word in words:
            index = lowered.find(word)
            if index == -1:
                continue
            if not any(abs(index - marker) <= _TONE_WINDOW_CHARS for marker in markers):
                continue
            # Negação perto da palavra de emoção: não é um pedido de TOM.
            window_start = max(0, index - _TONE_WINDOW_CHARS)
            if _NEGATION_NEAR_TONE_RE.search(lowered[window_start:index]):
                continue
            if best is None or index < best[1]:
                best = (emotion_name, index)
    if best is None:
        return None
    return EmotionState(emotion=best[0], intensity=0.8, confidence=1.0, source="explicit")