from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.speech.delivery import ChunkStrategy
from app.speech.emotion import Emotion, EmotionController, EmotionState


class TestEmotionState:
    def test_valid_emotions_are_accepted(self):
        for name in ("neutral", "happy", "excited", "curious", "concerned", "empathetic", "sad"):
            state = EmotionState(emotion=name, intensity=0.5, confidence=0.8)
            assert state.emotion == Emotion(name)
            assert state.intensity == 0.5
            assert state.confidence == 0.8

    def test_intensity_clamped_above_max(self):
        assert EmotionState(emotion="happy", intensity=999).intensity == 1.0

    def test_intensity_clamped_below_zero(self):
        assert EmotionState(emotion="happy", intensity=-5).intensity == 0.0

    def test_confidence_clamped(self):
        state = EmotionState(emotion="happy", intensity=0.8, confidence=500)
        assert state.confidence == 1.0

    def test_intensity_non_numeric_falls_back(self):
        assert EmotionState(emotion="happy", intensity="abc").intensity == 0.0

    def test_invalid_emotion_falls_back_to_neutral(self):
        assert EmotionState(emotion="SUPER_HAPPY!!!!!").emotion == Emotion.neutral
        assert EmotionState(emotion=None, intensity=0.5).emotion == Emotion.neutral
        assert EmotionState(emotion="SUPER_SAD!!!!!").emotion == Emotion.neutral
        # "sad" é membro válido da allowlist desde a camada de emoção explícita.
        assert EmotionState(emotion="sad").emotion == Emotion.sad

    def test_whitespace_in_emotion_is_normalized(self):
        assert EmotionState(emotion=" happy ").emotion == Emotion.happy

    def test_neutral_default(self):
        state = EmotionState()
        assert state.emotion == Emotion.neutral
        assert state.intensity == 0.0
        assert state.confidence == 0.0

    def test_to_dict_and_from_dict_roundtrip(self):
        state = EmotionState(emotion="happy", intensity=0.8, confidence=0.9)
        assert EmotionState.from_dict(state.to_dict()) == state
        assert EmotionState.from_dict(None) == EmotionState()
        invalid = {"emotion": "SUPER_HAPPY!!!!!", "intensity": 5}
        assert EmotionState.from_dict(invalid) == EmotionState(intensity=1.0)


class TestEmotionControllerProfiles:
    def controller(self) -> EmotionController:
        return EmotionController()

    def test_neutral_profile_matches_current_behavior(self):
        profile = self.controller().build_profile(EmotionState())
        assert profile.speed == get_settings().tts_speed
        assert profile.pause_scale == 1.0
        assert profile.chunk_strategy == ChunkStrategy.relaxed
        assert profile.voice is None

    def test_happy_profile(self):
        profile = self.controller().build_profile(EmotionState(emotion="happy", intensity=0.7))
        assert 1.03 <= profile.speed <= 1.07
        assert profile.pause_scale < 1.0

    def test_excited_profile(self):
        profile = self.controller().build_profile(EmotionState(emotion="excited", intensity=0.9))
        assert 1.08 <= profile.speed <= 1.12
        assert profile.chunk_strategy == ChunkStrategy.paused
        assert profile.pause_scale == pytest.approx(0.90)

    def test_intensity_scales_speed_toward_high_range(self):
        controller = self.controller()
        low = controller.build_profile(EmotionState(emotion="happy", intensity=0.1)).speed
        high = controller.build_profile(EmotionState(emotion="happy", intensity=1.0)).speed
        assert high >= low

    def test_curious_profile(self):
        profile = self.controller().build_profile(EmotionState(emotion="curious", intensity=0.6))
        assert 0.98 <= profile.speed <= 1.02
        assert profile.pause_scale > 1.0

    def test_concerned_profile(self):
        profile = self.controller().build_profile(EmotionState(emotion="concerned", intensity=0.7))
        assert 0.90 <= profile.speed <= 0.96
        assert profile.pause_scale > 1.0
        assert profile.chunk_strategy == ChunkStrategy.paused

    def test_empathetic_profile(self):
        profile = self.controller().build_profile(EmotionState(emotion="empathetic", intensity=0.7))
        assert 0.93 <= profile.speed <= 0.98
        assert profile.pause_scale > 1.0

    def test_profile_without_state_defaults_to_neutral(self):
        assert self.controller().build_profile().speed == get_settings().tts_speed


class TestEmotionDetection:
    def controller(self) -> EmotionController:
        return EmotionController()

    def test_neutral_text(self):
        state = self.controller().detect("O relatório está na pasta documentos.")
        assert state.emotion == Emotion.neutral
        assert state.intensity == 0.0

    def test_empty_text(self):
        state = self.controller().detect("")
        assert state.emotion == Emotion.neutral
        assert state.intensity == 0.0

    def test_happy_text(self):
        state = self.controller().detect("Boa! Conseguimos resolver tudo.")
        assert state.emotion == Emotion.happy
        assert state.intensity > 0.5
        assert state.confidence > 0.5

    def test_excited_text(self):
        state = self.controller().detect("Finalmente! Agora sim, vamos lá!")
        assert state.emotion == Emotion.excited
        assert state.intensity > 0.6

    def test_curious_text(self):
        text = "Onde está o arquivo que você mencionou? Será que encontramos?"
        state = self.controller().detect(text)
        assert state.emotion == Emotion.curious
        assert state.intensity > 0.5

    def test_concerned_text(self):
        state = self.controller().detect("Cuidado. Precisamos verificar antes de continuar.")
        assert state.emotion == Emotion.concerned
        assert state.intensity > 0.5

    def test_empathetic_text(self):
        state = self.controller().detect("Sinto muito. Vamos resolver juntos, vai dar certo.")
        assert state.emotion == Emotion.empathetic
        assert state.intensity > 0.5

    def test_detection_is_deterministic(self):
        text = "Boa! Conseguimos resolver tudo."
        first = self.controller().detect(text)
        second = self.controller().detect(text)
        assert first == second


class TestEmotionDecay:
    def test_linear_decay(self):
        state = EmotionState(emotion="happy", intensity=0.8)
        controller = EmotionController()
        assert controller.decay(state, 24).intensity == pytest.approx(0.4, abs=0.01)
        assert controller.decay(state, 48).emotion == Emotion.neutral

    def test_no_decay_for_neutral_or_negative_elapsed(self):
        controller = EmotionController()
        neutral = EmotionState()
        assert controller.decay(neutral, 100) == neutral
        assert controller.decay(EmotionState(emotion="happy", intensity=0.8), -10) == (
            EmotionState(emotion="happy", intensity=0.8)
        )

    def test_decay_reaches_neutral(self):
        controller = EmotionController()
        assert controller.decay(
            EmotionState(emotion="excited", intensity=1.0), 600
        ).emotion == Emotion.neutral


class TestResolveWithDefaultEmotion:
    def test_default_neutral_is_noop(self):
        controller = EmotionController()
        assert controller.resolve("O relatório está na pasta documentos.") == EmotionState()

    def test_custom_default_emotion_applies_when_nothing_detected(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "tts_default_emotion", "happy")
        controller = EmotionController()
        state = controller.resolve("O relatório está na pasta documentos.")
        assert state.emotion == Emotion.happy
        assert state.intensity == 0.0

    def test_detected_emotion_wins_over_default(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "tts_default_emotion", "happy")
        controller = EmotionController()
        assert controller.resolve(
            "Cuidado. Precisamos verificar antes de continuar."
        ).emotion == Emotion.concerned