from __future__ import annotations

import re
from dataclasses import dataclass

# A extração é DETERMINÍSTICA e conservadora: NUNCA inventa entidade. Se um
# slot não puder ser preenchido a partir do texto, a entidade fica não
# resolvida (``resolved=False``) e o Facilitator pede esclarecimento — em
# vez de chutar valores (req: não inventar entidades).

BROWSERS = {
    "chrome": "Chrome",
    "edge": "Microsoft Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "safari": "Safari",
}

# Apps conhecidos (desktop ou web) — extraídos só quando citados literalmente.
KNOWN_APPS = {
    "whatsapp": "WhatsApp",
    "teams": "Teams",
    "slack": "Slack",
    "discord": "Discord",
    "telegram": "Telegram",
    "zoom": "Zoom",
    "skype": "Skype",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "twitter": "Twitter",
    "x.com": "X",
    "linkedin": "LinkedIn",
    "gmail": "Gmail",
    "outlook": "Outlook",
    "netflix": "Netflix",
    "spotify": "Spotify",
    "twitch": "Twitch",
    "youtube": "YouTube",
    "prime video": "Prime Video",
    "primevideo": "Prime Video",
    "google drive": "Google Drive",
    "drive.google": "Google Drive",
}

# Termos que indicam SITES (intent navegação, não busca).
SITE_MARKERS = (
    "github", "youtube", "youtu.be", "web.whatsapp", "teams.microsoft",
    "teams.live", "x.com", "netflix", "prime video", "primevideo", "spotify",
    "twitch", "linkedin", "instagram", "facebook", "gmail", "outlook",
    "drive.google",
)

# Termos que marcam um referente NÃO RESOLVIDO — palavras déicticas que só
# funcionam se o contexto da conversa fornecer o valor (ex.: "isso").
UNRESOLVED_REFERENTS = (
    "isso aí",
    "aquilo lá",
    "isto",
    "isso",
    "aquilo",
    "aí",
)

_CONTACT_HINT = re.compile(r"(?:para|ao|à|pro|pra)\s+o\s+(\w[\wÀ-ú-]*)\b", re.IGNORECASE)


@dataclass(slots=True)
class Entity:
    """Entidade extraída do Request (ou resolvida via contexto).

    ``resolved=False`` significa que o valor exige confirmação humana; o
    Facilitator NUNCA preenche esse slot por conta própria.
    """

    name: str
    value: str
    confidence: float = 1.0
    resolved: bool = True
    source: str = "request"  # request | contexto | resposta

    def to_dict(self) -> dict[str, str | float | bool]:
        return {
            "name": self.name,
            "value": self.value,
            "confidence": self.confidence,
            "resolved": self.resolved,
            "source": self.source,
        }


class EntityExtractor:
    """Extrai entidades determinísticas do texto. Nunca inventa valores."""

    def extract(self, text: str) -> dict[str, Entity]:
        entities: dict[str, Entity] = {}
        lowered = text.lower()

        browser = self._find_browser(lowered)
        if browser is not None:
            entities["browser"] = Entity("browser", browser)

        app = self._find_app(lowered)
        if app is not None:
            entities["app"] = Entity("app", app)

        query = self._find_query(text, lowered)
        if query:
            entities["query"] = Entity("query", query)

        referent = self._find_unresolved_referent(lowered)
        if referent is not None:
            entities["referent"] = Entity(
                "referent", referent, resolved=False, source="request"
            )

        contact = self._find_contact(text)
        if contact is not None:
            entities["contact"] = Entity("contact", contact, resolved=False)

        return entities

    @staticmethod
    def _find_browser(lowered: str) -> str | None:
        for alias, name in BROWSERS.items():
            if re.search(rf"\b{alias}\b", lowered):
                return name
        return None

    @staticmethod
    def _find_app(lowered: str) -> str | None:
        matches = [(alias, name) for alias, name in KNOWN_APPS.items() if alias in lowered]
        if not matches:
            return None
        matches.sort(key=lambda item: len(item[0]), reverse=True)
        return matches[0][1]

    @staticmethod
    def _find_query(text: str, lowered: str) -> str | None:
        markers = (
            "pesquisar por", "pesquisando por", "procurar por", "procurando por",
            "busque por", "procure por", "pesquisar sobre", "procurar sobre",
            "notícias sobre", "noticias sobre", "informações sobre", "informacoes sobre",
            "buscar na internet por", "pesquisar",
        )
        for marker in markers:
            idx = lowered.find(marker)
            if idx == -1:
                continue
            start = idx + len(marker)
            tail = text[start:].strip(" .:;,").strip()
            if tail:
                # Remove resquícios de "no google"/"no site" ao final.
                tail = re.split(r"\s+no\s+(google|site)", tail, flags=re.IGNORECASE)[0].strip()
                if tail:
                    return tail
        # "pesquise X", "procure X", "busque X"
        for verb in ("pesquise", "procure", "busque", "pesquisa"):
            match = re.match(rf"^\s*{verb}\s+(.+)$", text, flags=re.IGNORECASE)
            if match and " no google" not in match.group(1):
                return match.group(1).strip().strip(". ")
        return None

    @staticmethod
    def _find_unresolved_referent(lowered: str) -> str | None:
        # Retorna o termo LITERAL citado (ex.: "isso", "isso aí") para que a
        # pergunta de esclarecimento faça sentido para o usuário.
        for token in sorted(UNRESOLVED_REFERENTS, key=len, reverse=True):
            if token == "aí":
                if re.search(r"\b(aí|ai)\b", lowered):
                    return "aí"
                continue
            if token in lowered:
                return token
        return None

    @staticmethod
    def _find_contact(text: str) -> str | None:
        normalized = re.sub(r"[àáâãä]", "a", text)
        match = _CONTACT_HINT.search(normalized)
        if match:
            name = match.group(1).strip().strip(".,:;")
            if name:
                return name
        return None