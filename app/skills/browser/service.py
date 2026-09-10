"""Driver de controle de navegador via CDP (Chrome/Edge/Brave).

Permite ao agente navegar, ler o DOM, executar JavaScript e clicar em elementos
por meio do protocolo DevTools (Remote Debugging Protocol), sem depender de
Playwright. Roda em cima do websockets (já presente no projeto).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import time
from typing import Any

import httpx
import websockets
from websockets.protocol import State

logger = logging.getLogger("app.skills.browser")


class BrowserError(Exception):
    pass


class BrowserNotAvailableError(BrowserError):
    pass


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser_exe() -> str:
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    raise BrowserNotAvailableError("Navegador compatível com CDP (Chrome/Edge) não foi encontrado.")


class BrowserDriver:
    """Controla uma aba do navegador via CDP.

    O navegador é aberto (se necessário) com a porta de debugging e cada instância
    conecta à aba ativa. Use um `connect()` por operação ou mantenha uma sessão
    aberta para várias chamadas.
    """

    def __init__(self, port: int = 9222, root_url: str | None = None) -> None:
        self.port = port
        self.root_url = root_url or f"http://127.0.0.1:{port}"
        self._ws: Any = None
        self._listener: Any = None
        self._consecutive_failures = 0

    # ---- lifecycle ----

    def _chrome_alive(self) -> bool:
        return _is_port_open(self.port)

    async def start_browser(self, url: str | None = None) -> dict[str, Any]:
        if self._chrome_alive():
            return {"started": False, "already_running": True, "port": self.port}
        exe = find_browser_exe()
        # Perfil dedicado: sem isso, uma instância regular do Chrome que já está
        # aberta "engole" o processo novo e a porta de debug nunca é exposta.
        profile_dir = os.path.join(tempfile.gettempdir(), "alpha_cdp_profile")
        args = [
            exe,
            f"--remote-debugging-port={self.port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            str(url) if url else "about:blank",
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if os.name == "nt":
            creationflags |= 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(args, creationflags=creationflags)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self._chrome_alive():
                return {"started": True, "already_running": False, "port": self.port}
            await asyncio.sleep(0.3)
        raise BrowserNotAvailableError("O navegador não abriu a porta de debugging a tempo.")

    async def _get_targets(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{self.root_url}/json")
            resp.raise_for_status()
            targets = resp.json()
        pages = [
            target
            for target in targets
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl")
        ]
        if not pages:
            raise BrowserNotAvailableError("Nenhuma aba de página disponível no navegador.")
        return pages

    async def _ws_url(self) -> str:
        pages = await self._get_targets()
        for page in pages:
            if page.get("title"):
                return page["webSocketDebuggerUrl"]
        return pages[0]["webSocketDebuggerUrl"]

    async def connect(self) -> None:
        if self._ws is not None and self._ws.state is State.OPEN:
            return
        url = await self._ws_url()

        self._ws = await websockets.connect(url, max_size=20 * 1024 * 1024)
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listener = asyncio.create_task(self._receiver())

    async def _receiver(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                msg_id = message.get("id")
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if not future.done():
                        future.set_result(message)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(BrowserError("Conexão de debug encerrada."))
            self._pending.clear()
        except Exception:  # noqa: BLE001 - loop de leitura termina em desconexão
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(BrowserNotAvailableError("Conexão de debug caiu."))
            self._pending.clear()

    async def _call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 20.0
    ) -> dict[str, Any]:
        await self.connect()
        self._msg_id += 1
        message = {"id": self._msg_id, "method": method, "params": params or {}}
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[self._msg_id] = future
        try:
            await self._ws.send(json.dumps(message))
        except Exception as exc:  # noqa: BLE001
            self._pending.pop(self._msg_id, None)
            raise BrowserNotAvailableError(str(exc)) from exc
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            self._pending.pop(self._msg_id, None)
            raise BrowserError(f"Timeout no comando CDP: {method}") from exc
        if "error" in response:
            raise BrowserError(f"Erro CDP em {method}: {response['error']}")
        return response.get("result", {})

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            self._listener = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    # ---- navegação e avaliação ----

    async def _enable(self) -> None:
        await self._call("Page.enable", timeout=5)
        await self._call("Runtime.enable", timeout=5)

    async def navigate(self, url: str, wait_for: float = 10.0) -> dict[str, Any]:
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            url = "https://" + url
        await self._enable()
        await self._call("Page.navigate", {"url": url}, timeout=30)
        # Espera condicional por estado (DOM pronto), não por tempo fixo.
        await self._wait_ready(wait_for)
        return {"url": url, "title": await self.get_title()}

    async def _wait_ready(self, timeout: float) -> None:
        deadline = asyncio.get_event_loop().time() + max(float(timeout), 0.0)
        while True:
            try:
                ready = await self._evaluate("document.readyState === 'complete'")
                if ready:
                    return
            except (BrowserError, BrowserNotAvailableError):
                pass
            if asyncio.get_event_loop().time() >= deadline:
                return
            await asyncio.sleep(0.2)

    async def get_title(self) -> str:
        result = await self._evaluate("document.title")
        return str(result or "")

    async def _evaluate(self, expression: str) -> Any:
        result = await self._call(
            "Runtime.evaluate", {"expression": expression, "returnByValue": True}
        )
        value = result.get("result", {}).get("value")
        if result.get("result", {}).get("subtype") == "error":
            raise BrowserError(f"Erro no JavaScript da página: {value}")
        return value

    async def evaluate(self, expression: str) -> Any:
        await self._enable()
        return await self._evaluate(expression)

    async def get_text(self, partial: str | None = None, sel: str | None = None) -> str:
        await self._enable()
        if sel:
            expression = f"Array.from(document.querySelectorAll({json.dumps(sel)})).map(e=>e.innerText.trim()).join('\\n')"  # noqa: E501
        elif partial:
            parts = [p for p in str(partial).lower().split() if p]
            envelope = " && ".join(
                f"e.innerText.toLowerCase().includes({json.dumps(p)})" for p in parts
            )
            expression = f"Array.from(document.querySelectorAll('*')).filter(e=>{envelope}).map(e=>e.innerText.trim()).join('\\n---\\n')"  # noqa: E501
        else:
            expression = "document.body ? document.body.innerText : ''"
        return str(await self._evaluate(expression) or "")

    async def get_html(self, sel: str | None = None) -> str:
        await self._enable()
        if sel:
            expression = f"Array.from(document.querySelectorAll({json.dumps(sel)})).map(e=>e.outerHTML).join('\\n')"  # noqa: E501
        else:
            expression = "document.documentElement ? document.documentElement.outerHTML : ''"
        return str(await self._evaluate(expression) or "")

    async def find_elements(self, text: str, sel: str | None = None) -> list[dict[str, Any]]:
        await self._enable()
        selector = sel or "*"
        parts = [p for p in str(text).lower().split() if p]
        if not parts:
            raise ValueError("Informe um texto para procurar na página.")
        conditions = " && ".join(
            f"(e.innerText||'').toLowerCase().includes({json.dumps(p)})" for p in parts
        )
        expression = (
            f"Array.from(document.querySelectorAll({json.dumps(selector)})).filter(e=>{conditions})"
            ".map((e,i)=>{const r=e.getBoundingClientRect();"
            "return {index:i, tag:e.tagName, text:(e.innerText||'').trim().slice(0,80), "
            "id:e.id||null, className:(typeof e.className==='string'?e.className:''), "
            "x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), visible:!!(r.width&&r.height)}}) "  # noqa: E501
            ".filter(e=>e.visible)"
        )
        value = await self._evaluate(expression)
        return value if isinstance(value, list) else []

    async def click(self, text: str, sel: str | None = None) -> dict[str, Any]:
        await self._enable()
        selector = sel or "*"
        parts = [p for p in str(text).lower().split() if p]
        target_text = " ".join(parts)
        if not parts:
            raise ValueError("Informe o texto do elemento a clicar.")
        conditions = " && ".join(
            f"(e.innerText||'').toLowerCase().includes({json.dumps(p)})" for p in parts
        )
        expression = (
            f"(()=>{{const text={json.dumps(target_text)};"
            f"const els=Array.from(document.querySelectorAll({json.dumps(selector)}))"
            f".filter(e=>{conditions} && e.getClientRects().length);"
            "if(!els.length)return {clicked:false,match:0,text:'',selected:''};"
            "const norm=e=>(e.innerText||'').trim().replace(/\\s+/g,' ');"
            "const ranked=els.map((e,i)=>{const t=norm(e).toLowerCase();let score=0;"
            "if(t===text)score+=100;"
            "if(/^(button|a|input|summary|[a-z]+button)$/i.test(e.tagName))score+=30;"
            "score-=Math.min(t.length/10,40);return {e,score,t};})"
            ".sort((a,b)=>b.score-a.score);"
            "const target=ranked[0];const e=target.e;"
            "if(typeof e.click==='function')e.click();"
            "else e.dispatchEvent(new MouseEvent('click',{bubbles:true,view:window}));"
            "return {clicked:true,match:els.length,text:target.t,selected:norm(e)};}})()"
        )
        value = await self._evaluate(expression)
        if isinstance(value, dict):
            return value
        return {"clicked": bool(value), "match": 1, "text": target_text, "selected": target_text}

    async def click_point(self, x: int, y: int) -> None:
        await self._enable()
        await self._call(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        await self._call(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        )

    async def fill(self, sel: str, value: str) -> bool:
        await self._enable()
        expression = (
            f"(()=>{{const el=document.querySelector({json.dumps(sel)});"
            f"if(!el)return false; const setter=Object.getOwnPropertyDescriptor("
            f"el.tagName==='TEXTAREA'||el.tagName==='INPUT'?HTMLInputElement.prototype:"
            f"HTMLTextAreaElement.prototype,'value').set;"
            f"setter.call(el,{json.dumps(value)});"
            f"el.dispatchEvent(new Event('input',{{bubbles:true}}));"
            f"el.dispatchEvent(new Event('change',{{bubbles:true}}));return true;}})()"
        )
        return bool(await self._evaluate(expression))

    async def press_enter(self, sel: str | None = None) -> None:
        await self._enable()
        if sel:
            await self._evaluate(
                f"(()=>{{const el=document.querySelector({json.dumps(sel)});"
                "if(!el)return false; el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));"  # noqa: E501
                "el.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));return true;})()"  # noqa: E501
            )
        await self._call(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
        )
        await self._call(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
        )

    async def wait_for_text(self, text: str, timeout: float = 15.0) -> bool:
        expression = f"document.body && document.body.innerText.toLowerCase().includes({json.dumps(text.lower())})"  # noqa: E501
        return bool(await self._wait_for(expression, timeout))

    async def _wait_for(self, expression: str, timeout: float) -> Any:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            value = await self._evaluate(expression)
            if value:
                return value
            if asyncio.get_event_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.4)

    async def extract_links(self, sel: str = "a") -> list[dict[str, str]]:
        await self._enable()
        expression = (
            f"Array.from(document.querySelectorAll({json.dumps(sel)})).slice(0,60)"
            ".map(a=>({text:(a.innerText||'').trim().slice(0,80), href:a.href}))"
            ".filter(l=>l.href && l.text)"
        )
        links = await self._evaluate(expression)
        return links if isinstance(links, list) else []

    async def screenshot(self, path: str | None = None) -> str:
        """Captura a página atual (PNG base64). Retorna base64 ou salva em `path`."""
        await self._enable()
        result = await self._call("Page.captureScreenshot", {"format": "png"})
        data = result.get("data", "")
        if path:
            import base64

            with open(path, "wb") as fh:
                fh.write(base64.b64decode(data))
        return data