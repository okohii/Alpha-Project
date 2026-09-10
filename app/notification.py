from __future__ import annotations

import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.notification")


def play_notification_sound() -> None:
    """Reproduz um som de notificação alto, em sequência, para chamar atenção."""
    try:
        system = platform.system()
        if system == "Windows":
            import winsound
            # Sequência de bipes altos e repetidos (alarme clássico)
            _winsound_alarm(winsound)
        elif system == "Darwin":
            # macOS - repete o som para ficar mais audível
            for _ in range(2):
                subprocess.run(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    capture_output=True,
                    check=False,
                )
        else:
            # Linux - tenta usar paplay ou aplay
            sound_file = "/usr/share/sounds/freedesktop/stereo/bell.oga"
            if not Path(sound_file).exists():
                sound_file = "/usr/share/sounds/freedesktop/stereo/complete.oga"
            if Path(sound_file).exists():
                for _ in range(2):
                    subprocess.run(
                        ["paplay", sound_file],
                        capture_output=True,
                        check=False,
                    )
            else:
                # Fallback: beep simples
                print("\a", end="", flush=True)
    except Exception as exc:
        logger.debug("Falha ao reproduzir som: %s", exc)
        # Fallback: beep simples
        print("\a", end="", flush=True)


def _winsound_alarm(winsound: Any) -> None:
    """Reproduz uma sequência de bipes altos (padrão de alarme).

    Usa o winsound.Beep que toca no alto-falante do sistema,
    de forma perceptível mesmo com volume baixo.
    """
    pattern = ((1200, 200), (600, 200), (1200, 400))
    for freq, duration in pattern:
        try:
            winsound.Beep(freq, duration)
        except RuntimeError:
            # Ambiente sem suporte a Beep (ex.: WSL) - cai no beep do sistema
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        time.sleep(0.05)


def show_notification(title: str, message: str) -> None:
    """Mostra uma notificação no sistema."""
    try:
        system = platform.system()
        if system == "Windows":
            # Windows toast notification
            try:
                from app.notification_windows import show_toast
                show_toast(title, message)
            except ImportError:
                # Fallback: usa PowerShell
                ps_cmd = f"""
                [Windows.UI.Notifications.ToastNotificationManager, `
                 Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                [Windows.Data.Xml.Dom.XmlDocument, `
                 Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
                $template = @"
                <toast>
                    <visual>
                        <binding template="ToastGeneric">
                            <text>{title}</text>
                            <text>{message}</text>
                        </binding>
                    </visual>
                </toast>
                "@
                $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
                $xml.LoadXml($template)
                $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
                [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("ALPHA").Show($toast)
                """
                subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    capture_output=True,
                    check=False,
                )
        elif system == "Darwin":
            # macOS
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{message}" with title "{title}"',
                ],
                capture_output=True,
                check=False,
            )
        else:
            # Linux
            subprocess.run(
                ["notify-send", title, message],
                capture_output=True,
                check=False,
            )
    except Exception as exc:
        logger.debug("Falha ao mostrar notificação: %s", exc)
