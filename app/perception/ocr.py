from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class OCRResult:
    text: str
    confidence: float
    bounding_box: dict[str, int] | None = None
    page: int | None = None


@dataclass(slots=True)
class OCRResultPage:
    page_number: int
    full_text: str
    lines: list[dict[str, Any]] | None = None
    success: bool = True


@dataclass(slots=True)
class OCRResultFull:
    overall_text: str
    pages: list[OCRResultPage] | None = None
    success: bool = True


@dataclass(slots=True)
class OCREvidence:
    kind: str = "ocr"
    result: OCRResult | OCRResultFull | None = None
    image_path: str | None = None
    success: bool = True


class OCRPerceptor:
    """OCR real opcional via Tesseract, sem inventar evidência."""

    def __init__(self, executable: str | None = None, language: str = "por+eng") -> None:
        self.executable = executable or shutil.which("tesseract")
        self.language = language

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def perceive(self, image_path: str | None = None, *, text: str | None = None) -> OCREvidence:
        if text is not None:
            return OCREvidence(result=OCRResult(text=text, confidence=1.0), image_path=image_path, success=True)
        if not image_path or not self.available:
            return OCREvidence(result=None, image_path=image_path, success=False)
        path = Path(image_path)
        if not path.exists():
            return OCREvidence(result=None, image_path=image_path, success=False)
        try:
            result = self._run_tesseract(path)
        except (OSError, subprocess.SubprocessError):
            return OCREvidence(result=None, image_path=image_path, success=False)
        return OCREvidence(result=result, image_path=image_path, success=True)

    async def aperceive(self, image_path: str | None = None, *, text: str | None = None) -> OCREvidence:
        """Versão assíncrona para não bloquear o event loop com OCR pesado."""
        return await asyncio.to_thread(self.perceive, image_path, text=text)

    def _run_tesseract(self, image_path: Path) -> OCRResultFull:
        assert self.executable is not None
        command = [self.executable, str(image_path), "stdout", "-l", self.language, "--psm", "6"]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode != 0:
            raise subprocess.SubprocessError(completed.stderr.strip() or "Tesseract falhou")
        text = completed.stdout.strip()
        tsv = subprocess.run(
            [self.executable, str(image_path), "stdout", "-l", self.language, "--psm", "6", "tsv"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        lines: list[dict[str, Any]] = []
        if tsv.returncode == 0:
            header, *rows = tsv.stdout.splitlines()
            columns = header.split("\t") if header else []
            for row in rows:
                values = row.split("\t")
                if len(values) != len(columns):
                    continue
                item = dict(zip(columns, values, strict=False))
                token = item.get("text", "").strip()
                if not token:
                    continue
                try:
                    confidence = max(0.0, min(1.0, float(item.get("conf", "-1")) / 100.0))
                    bbox = {"left": int(item.get("left", 0)), "top": int(item.get("top", 0)), "width": int(item.get("width", 0)), "height": int(item.get("height", 0))}
                except (TypeError, ValueError):
                    continue
                lines.append({"text": token, "confidence": confidence, "bounding_box": bbox})
        page = OCRResultPage(page_number=1, full_text=text, lines=lines, success=True)
        return OCRResultFull(overall_text=text, pages=[page], success=True)

    def verify_action_text(self, before: dict[str, Any] | None, after: dict[str, Any] | None, action_name: str) -> dict[str, Any]:
        expected = action_name.lower()
        after_text = str(after.get("text", "")) if after else ""
        before_text = str(before.get("text", "")) if before else ""
        found = expected in after_text.lower() and expected not in before_text.lower()
        return {"action": action_name, "text_found": found, "expected": action_name, "after_text_snippet": after_text[:100], "before_text_snippet": before_text[:100]}


__all__ = ["OCRResult", "OCRResultPage", "OCRResultFull", "OCREvidence", "OCRPerceptor"]
