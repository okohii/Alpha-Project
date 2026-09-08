from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.speech.pipeline import VoicePipeline

router = APIRouter(prefix="/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)


class TranscribeResponse(BaseModel):
    text: str
    language: str = ""
    segments: list[dict] = []


async def _save_uploaded_audio(file: UploadFile) -> Path:
    if file.filename is None or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Arquivo de áudio inválido")

    suffix = Path(file.filename).suffix or ".wav"
    temp_dir = Path(tempfile.mkdtemp(prefix="alpha-voice-"))
    audio_path = temp_dir / f"upload{suffix}"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo de áudio vazio")
    audio_path.write_bytes(content)
    return audio_path


@router.post("/transcribe")
async def transcribe(file: UploadFile | None = File(default=None)) -> dict:
    if file is None:
        return {"text": "", "language": "", "segments": []}

    audio_path = await _save_uploaded_audio(file)
    pipeline = VoicePipeline()
    result = await pipeline.process(audio_path)
    return {
        "text": result.get("transcription", ""),
        "language": result.get("language", ""),
        "segments": result.get("segments", []),
    }


@router.post("/speak")
async def speak(payload: SpeakRequest) -> dict:
    pipeline = VoicePipeline()
    result = await pipeline.speak(payload.text)

    if result.get("status") == "ok":
        audio_path = Path(result["audio_path"])
        payload_bytes = audio_path.read_bytes() if audio_path.exists() else b""
        return {
            "status": "ok",
            "text": payload.text,
            "audio_base64": base64.b64encode(payload_bytes).decode("utf-8"),
            "mime_type": "audio/wav",
        }

    return {
        "status": result.get("status", "text_only"),
        "detail": result.get("detail"),
        "text": payload.text,
    }


@router.post("/process")
async def process_voice(file: UploadFile | None = File(default=None)) -> dict:
    if file is None:
        return {"status": "error", "detail": "arquivo de áudio não enviado"}

    audio_path = await _save_uploaded_audio(file)
    pipeline = VoicePipeline()
    return await pipeline.process(audio_path)
