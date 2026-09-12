from __future__ import annotations

from app.speech.delivery import ChunkStrategy, DeliveryProcessor, DeliveryProfile

STANDARD = DeliveryProfile(chunk_strategy=ChunkStrategy.standard)
PAUSED = DeliveryProfile(chunk_strategy=ChunkStrategy.paused)
RELAXED = DeliveryProfile(chunk_strategy=ChunkStrategy.relaxed)


class TestPrepare:
    def setup_method(self):
        self.processor = DeliveryProcessor()

    def test_removes_internal_tags(self):
        assert self.processor.prepare("[happy] Boa! Consegui resolver tudo.") == (
            "Boa! Consegui resolver tudo."
        )

    def test_preserves_accents(self):
        prepared = self.processor.prepare("Não encontro a ação na pasta")
        assert prepared == "Não encontro a ação na pasta"

    def test_preserves_meaning_and_punctuation(self):
        text = "Calma. Vamos verificar isso antes de continuar, certo?"
        assert self.processor.prepare(text) == text

    def test_removes_markdown_artifacts(self):
        expected = "ótima resposta ao problema"
        assert self.processor.prepare("**ótima** resposta ao problema") == expected

    def test_collapses_whitespace(self):
        assert self.processor.prepare("Boa!    Tudo certo.   ") == "Boa! Tudo certo."

    def test_empty_text(self):
        assert self.processor.prepare("") == ""
        assert self.processor.prepare(None) == ""


class TestChunking:
    def setup_method(self):
        self.processor = DeliveryProcessor()

    def test_standard_chunks_by_sentence(self):
        text = "Boa! Encontrei a macro que você pediu. Ela está agendada para amanhã."
        assert self.processor.chunk(text, STANDARD) == [
            "Boa! Encontrei a macro que você pediu.",
            "Ela está agendada para amanhã.",
        ]

    def test_relaxed_keeps_single_segment(self):
        text = "Boa! Encontrei a macro que você pediu. Ela está agendada para amanhã."
        assert self.processor.chunk(text, RELAXED) == [text]

    def test_paused_splits_on_colon_and_semicolon(self):
        text = "Atenção: precisamos verificar. O prazo vence amanhã."
        chunks = self.processor.chunk(text, PAUSED)
        assert chunks == ["Atenção:", "precisamos verificar.", "O prazo vence amanhã."]

    def test_short_sentences_merge_forward(self):
        assert self.processor.chunk("Sim. Vamos continuar com o plano.", STANDARD) == [
            "Sim. Vamos continuar com o plano."
        ]
        assert self.processor.chunk("Entendi.", STANDARD) == ["Entendi."]

    def test_empty_chunking(self):
        assert self.processor.chunk("", STANDARD) == []
        assert self.processor.chunk("  ", PAUSED) == []

    def test_long_text_falls_back_out_of_relaxed(self):
        sentence = "Bom dia, tudo certo. "
        text = sentence * 20
        chunks = self.processor.chunk(text, RELAXED)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.endswith(".")
            assert " " in chunk

    def test_never_splits_mid_word(self):
        text = (
            "Primeira informação importante sobre o projeto. "
            "Segunda informação com detalhes adicionais para conferência. "
            "Terceira informação relevante e complementar."
        )
        chunks = self.processor.chunk(text, STANDARD)
        recombined = " ".join(chunks)
        original_normalized = " ".join(text.split())
        assert recombined == original_normalized
        for chunk in chunks:
            assert chunk == chunk.strip()