from __future__ import annotations

from pathlib import Path
from unittest import mock


class FakeSessionCM:
    def __init__(self) -> None:
        self.session = object()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


class FakeSessionFactory:
    def __call__(self):
        return FakeSessionCM()


class FakeAgent:
    def __init__(self, *args, **kwargs) -> None:
        self.events = []

    async def chat(self, message: str, conversation_id: str | None = None):
        return {
            "response": f"ec: {message}",
            "conversation_id": conversation_id or "conv-1",
            "memory_created": False,
        }


class FakeOllama:
    async def health(self) -> bool:
        return True


class FakeVoicePipeline:
    def __init__(self, *args, **kwargs) -> None:
        self.speak_calls: list[str] = []

    async def speak(self, text: str):
        self.speak_calls.append(text)
        return {"status": "ok", "audio_path": str(Path("C:/tmp/fake-speech.wav"))}

    async def process(self, audio_path):
        return {"transcription": "olá do microfone", "language": "pt", "segments": []}


class FakeTranscription:
    text = "olá do microfone"
    language = "pt"
    segments = []


class FakeMemoryItem:
    def __init__(self, content: str) -> None:
        self.content = content

    def model_dump(self) -> dict:
        return {
            "id": "m1",
            "content": self.content,
            "memory_type": "semantic",
            "source": "manual",
            "importance": 1.0,
            "embedding": None,
            "metadata": {},
        }


class FakeMemoryService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def save_memory(self, **kwargs):
        return FakeMemoryItem(kwargs.get("content", ""))

    async def list_memories(self):
        return [FakeMemoryItem("Memória persistida")]

    async def delete_memory(self, memory_id: str):
        return None


async def _noop_init():
    return None


async def _fake_build_agent(*args, **kwargs):
    return FakeAgent()


def _patch_cli(monkeypatch) -> None:
    monkeypatch.setattr("app.cli.initialize_database", _noop_init)
    monkeypatch.setattr("app.cli.AsyncSessionLocal", FakeSessionFactory())


def _patch_voice(monkeypatch) -> FakeVoicePipeline:
    fake_pipeline = FakeVoicePipeline()
    monkeypatch.setattr("app.cli.VoicePipeline", lambda *a, **k: fake_pipeline)
    monkeypatch.setattr("app.cli.audio_io.play_wav", mock.Mock())
    return fake_pipeline


def test_main_without_command_starts_interactive_chat(monkeypatch):
    from app.cli import main

    _patch_cli(monkeypatch)
    calls: list[mock.Mock] = []

    async def fake_cmd_chat(args):
        calls.append(args)
        return 0

    monkeypatch.setattr("app.cli._cmd_chat", fake_cmd_chat)

    code = main([])

    assert code == 0
    assert len(calls) == 1


def test_cli_health_reports_services(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.llm.ollama.OllamaProvider", FakeOllama)

    code = main(["health"])

    assert code == 0
    captured = capsys.readouterr().out
    assert "ollama: ok" in captured


def test_cli_chat_single_message(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.build_agent", _fake_build_agent)
    _patch_voice(monkeypatch)

    code = main(["chat", "olá"])

    assert code == 0
    assert "ALPHA: ec: olá" in capsys.readouterr().out


def test_cli_chat_voice_speaks_reply(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.build_agent", _fake_build_agent)
    fake_pipeline = _patch_voice(monkeypatch)

    code = main(["chat", "--voice", "olá"])

    assert code == 0
    assert len(fake_pipeline.speak_calls) == 1
    assert fake_pipeline.speak_calls[0] == "ec: olá"


def test_cli_chat_no_voice_does_not_speak(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.build_agent", _fake_build_agent)
    fake_pipeline = _patch_voice(monkeypatch)

    code = main(["chat", "--no-voice", "olá"])

    assert code == 0
    assert fake_pipeline.speak_calls == []
    assert "ALPHA: ec: olá" in capsys.readouterr().out


def test_cli_chat_voice_fluid_loop_hears_and_replies(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.build_agent", _fake_build_agent)

    pipeline = FakeVoicePipeline()
    pipeline.process = mock.AsyncMock(
        side_effect=[
            {"transcription": "olá ALPHA", "language": "pt", "segments": []},
            {"transcription": "sair", "language": "pt", "segments": []},
        ]
    )

    def _stage_recorder(*args, **kwargs):
        if _stage_recorder.n < 1:
            _stage_recorder.n += 1
            return Path("C:/tmp/fake-recording.wav")
        on_onset = kwargs.get("on_speech_start")
        if on_onset is not None:
            on_onset()
        _stage_recorder.n += 1
        return Path("C:/tmp/fake-barge.wav")

    _stage_recorder.n = 0
    recorder = mock.Mock(side_effect=_stage_recorder)
    monkeypatch.setattr("app.cli.VoicePipeline", lambda: pipeline)
    monkeypatch.setattr("app.cli.audio_io.record_microphone_vad", recorder)
    play_wav_async = mock.Mock(return_value=("winsound", 16000, 160000))
    stop_wav_async = mock.Mock()
    monkeypatch.setattr("app.cli.audio_io.play_wav_async", play_wav_async)
    monkeypatch.setattr("app.cli.audio_io.stop_wav_async", stop_wav_async)

    code = main(["chat", "--voice"])

    assert code == 0
    assert recorder.call_count == 2
    out = capsys.readouterr().out
    assert "Você (voz): olá ALPHA" in out
    assert "[interrompido]" in out
    assert "Até logo!" in out
    assert pipeline.speak_calls == ["ec: olá ALPHA"]
    assert play_wav_async.call_count == 1
    assert stop_wav_async.call_count == 1


def test_cli_chat_voice_does_not_echo_playback(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.build_agent", _fake_build_agent)

    pipeline = FakeVoicePipeline()
    pipeline.process = mock.AsyncMock(
        side_effect=[
            {"transcription": "olá ALPHA", "language": "pt", "segments": []},
            {"transcription": "sair", "language": "pt", "segments": []},
        ]
    )

    def _stage_recorder(*args, **kwargs):
        if _stage_recorder.n < 1:
            _stage_recorder.n += 1
            return Path("C:/tmp/fake-recording.wav")
        if _stage_recorder.n == 1:
            _stage_recorder.n += 1
            return None
        _stage_recorder.n += 1
        return Path("C:/tmp/fake-recording.wav")

    _stage_recorder.n = 0
    recorder = mock.Mock(side_effect=_stage_recorder)
    monkeypatch.setattr("app.cli.VoicePipeline", lambda: pipeline)
    monkeypatch.setattr("app.cli.audio_io.record_microphone_vad", recorder)
    play_wav_async = mock.Mock(return_value=("winsound", 16000, 1))
    stop_wav_async = mock.Mock()
    monkeypatch.setattr("app.cli.audio_io.play_wav_async", play_wav_async)
    monkeypatch.setattr("app.cli.audio_io.stop_wav_async", stop_wav_async)

    code = main(["chat", "--voice"])

    assert code == 0
    assert recorder.call_count == 3
    out = capsys.readouterr().out
    assert "[interrompido]" not in out
    assert "Até logo!" in out
    assert pipeline.speak_calls == ["ec: olá ALPHA"]


def test_cli_chat_voice_exits_on_spoken_word(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.build_agent", _fake_build_agent)

    pipeline = FakeVoicePipeline()
    pipeline.process = mock.AsyncMock(
        return_value={"transcription": "sair", "language": "pt", "segments": []}
    )
    play_wav = mock.Mock()
    monkeypatch.setattr("app.cli.VoicePipeline", lambda: pipeline)
    monkeypatch.setattr("app.cli.audio_io.play_wav", play_wav)
    recorder = mock.Mock(return_value=Path("C:/tmp/fake-recording.wav"))
    monkeypatch.setattr("app.cli.audio_io.record_microphone_vad", recorder)

    code = main(["chat", "--voice"])

    assert code == 0
    assert recorder.call_count == 1
    assert play_wav.call_count == 0
    assert "Até logo!" in capsys.readouterr().out
    assert pipeline.speak_calls == []


def test_cli_memories_list_default(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.MemoryService", FakeMemoryService)

    code = main(["memories"])

    assert code == 0
    assert "Memória persistida" in capsys.readouterr().out


def test_cli_memories_add(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr("app.cli.MemoryService", FakeMemoryService)

    code = main(["memories", "add", "nova memória"])

    assert code == 0
    captured = capsys.readouterr().out
    assert "nova memória" in captured


def test_cli_settings_with_json(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    patched_repo = mock.Mock()
    patched_repo.list = mock.AsyncMock(return_value=[])
    monkeypatch.setattr("app.cli.ManagedPathRepository", mock.Mock(return_value=patched_repo))

    code = main(["--json", "settings"])

    assert code == 0
    captured = capsys.readouterr().out
    assert captured.lstrip().startswith("{")
    assert '"app_name"' in captured


def test_cli_tasks_list_default(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    fake_service = mock.AsyncMock()
    fake_service.list_tasks = mock.AsyncMock(return_value=[])
    fake_path_repo = mock.AsyncMock()
    fake_path_repo.list = mock.AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.cli._make_task_service",
        mock.AsyncMock(return_value=(fake_service, fake_path_repo)),
    )

    code = main(["tasks", "list"])

    assert code == 0
    assert "(vazio)" in capsys.readouterr().out


def test_cli_listen_transcribes_microphone(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    monkeypatch.setattr(
        "app.cli.audio_io.record_microphone",
        mock.Mock(return_value=Path("C:/tmp/fake-recording.wav")),
    )
    fake_stt = mock.Mock()
    fake_stt.transcribe = mock.AsyncMock(return_value=FakeTranscription())
    monkeypatch.setattr("app.cli.FasterWhisperSTT", mock.Mock(return_value=fake_stt))

    code = main(["listen"])

    assert code == 0
    assert "olá do microfone" in capsys.readouterr().out


def test_cli_speak_plays_by_default(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    _patch_voice(monkeypatch)
    play_wav = mock.Mock()
    monkeypatch.setattr("app.cli.audio_io.play_wav", play_wav)

    code = main(["speak", "oi"])

    assert code == 0
    assert play_wav.call_count == 1
    assert "Áudio gerado em:" in capsys.readouterr().out


def test_cli_speak_no_play_keeps_output(monkeypatch, capsys):
    from app.cli import main

    _patch_cli(monkeypatch)
    fake_pipeline = _patch_voice(monkeypatch)
    play_wav = mock.Mock()
    monkeypatch.setattr("app.cli.audio_io.play_wav", play_wav)

    code = main(["speak", "--no-play", "oi"])

    assert code == 0
    assert play_wav.call_count == 0
    assert fake_pipeline.speak_calls == ["oi"]
