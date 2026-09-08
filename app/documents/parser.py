from __future__ import annotations

from pathlib import Path

_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".csv",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".xml",
}


class DocumentParser:
    def extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in _TEXT_SUFFIXES:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except Exception as exc:  # pragma: no cover
                raise RuntimeError("pypdf não disponível") from exc
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".docx":
            try:
                import docx
            except Exception as exc:  # pragma: no cover
                raise RuntimeError("python-docx não disponível") from exc
            document = docx.Document(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        raise ValueError(f"Formato não suportado: {suffix}")
