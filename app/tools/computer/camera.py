"""Detecção de objetos em tempo real por câmera (YOLO).

Mantém a funcionalidade do Detector.py da branch main integrada ao ALPHA.
Carrega o modelo YOLO sob demanda e degrada de forma elegante quando a
dependência (ultralytics/torch/opencv) ou a câmera não estiverem disponíveis.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult

logger = logging.getLogger("app.tools.computer.camera")

_MODEL: Any | None = None
_MODEL_NAME = ""
_LOAD_ERROR: str | None = None


def _load_model(model_name: str = "yolov8n.pt") -> Any | None:
    """Carrega (uma vez) o modelo YOLO. Retorna None se a dependência faltar."""
    global _MODEL, _MODEL_NAME, _LOAD_ERROR
    if _MODEL is not None and _MODEL_NAME == model_name:
        return _MODEL
    try:
        from ultralytics import YOLO
    except Exception as exc:  # pragma: no cover - dependência opcional
        _LOAD_ERROR = f"ultralytics não instalado: {exc}"
        return None
    try:
        _MODEL = YOLO(model_name)
        _MODEL_NAME = model_name
        _LOAD_ERROR = None
        return _MODEL
    except Exception as exc:
        _LOAD_ERROR = f"não foi possível carregar o modelo {model_name}: {exc}"
        return None


def _capture_frame(source: Any = 0, timeout: float = 8.0) -> tuple[Any | None, int, int]:
    """Captura um frame da câmera. Retorna (frame, largura, altura) ou (None, 0, 0)."""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - dependência opcional
        raise RuntimeError(f"opencv (cv2) não instalado: {exc}") from exc
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"Não foi possível abrir a câmera: {source}")
    try:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        deadline = time.monotonic() + timeout
        frame = None
        while time.monotonic() < deadline:
            ok, current = capture.read()
            if ok and current is not None:
                frame = current
                break
            time.sleep(0.1)
        if frame is None:
            raise RuntimeError("A câmera não entregou frames a tempo.")
        height, width = frame.shape[:2]
        return frame, int(width), int(height)
    finally:
        capture.release()


def detect_objects(
    source: Any = 0, model_name: str = "yolov8n.pt", confidence: float = 0.5
) -> dict[str, Any]:
    """Detecta objetos num frame da câmera e devolve rótulos + coordenadas."""
    model = _load_model(model_name)
    if model is None:
        raise RuntimeError(_LOAD_ERROR or "Modelo YOLO indisponível")

    frame, width, height = _capture_frame(source)
    results = model(frame, verbose=False, conf=confidence)
    detections: list[dict[str, Any]] = []
    if results and len(results) > 0:
        boxes = results[0].boxes
        names = model.names
        for det in (boxes or []):
            if det.conf.item() < confidence:
                continue
            x1, y1, x2, y2 = det.xyxy[0].cpu().numpy()
            label = str(names[int(det.cls.item())])
            detections.append(
                {
                    "label": label,
                    "confidence": round(float(det.conf.item()), 3),
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "center_x": int((float(x1) + float(x2)) / 2),
                    "center_y": int((float(y1) + float(y2)) / 2),
                }
            )
    frame_shape = (width, height) if frame is not None else None
    return {
        "detections": detections,
        "count": len(detections),
        "model": model_name,
        "frame_size": frame_shape,
    }


class DetectCameraTool(Tool):
    name = "detect_camera"
    description = (
        "Detecta objetos em tempo real pela câmera usando YOLO e devolve a lista "
        "de objetos encontrados com coordenadas (bbox) e confiança. "
        "Ex.: 'veja o que tem na minha frente' -> detect_camera."
    )
    permission = ToolPermission.write

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            data = detect_objects(
                source=kwargs.get("source", 0),
                model_name=str(kwargs.get("model", "yolov8n.pt")),
                confidence=float(kwargs.get("confidence", 0.5)),
            )
            return ToolResult(name=self.name, success=True, data=data)
        except (RuntimeError, OSError, ValueError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Origem da câmera (índice/device path; padrão: câmera 0)",
                },
                "model": {
                    "type": "string",
                    "description": "Modelo YOLO (padrão: yolov8n.pt)",
                },
                "confidence": {
                    "type": "number",
                    "description": "Limiar de confiança entre 0 e 1 (padrão 0.5)",
                },
            },
        }