from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# VerificationResult — resultado da verificação de uma ação.
# ---------------------------------------------------------------------------

class VerificationResult(IntEnum):
    """Resultado da verificação de uma ação ALPHA.

    • SUCCESS — a ação foi bem-sucedida e as evidências corroboram.
    • FAILED — a ação falhou ou as evidências indicam falha.
    • UNCERTAIN — não há evidências suficientes para afirmar sucesso ou falha;
      o agente deve repetir, refletir ou pedir esclarecimento.
    """

    SUCCESS = 1
    FAILED = 2
    UNCERTAIN = 3


# ---------------------------------------------------------------------------
# Evidence — representação estruturada de "o que foi observado" após uma
# ação.  É um tipo discriminado: cada subtipo tem um ``kind`` e um ``data``
# que depende do tipo.
# ---------------------------------------------------------------------------

class EvidenceKind(StrEnum):
    """Categorias de evidence que o ALPHA pode observar."""

    TOOL_RESULT = "tool_result"       # resultado bruto de uma tool execution
    DOM_STATE = "dom_state"           # estado do DOM após ação GUI
    ACCESSIBILITY_STATE = "accessibility_state"  # estado de accessibility tree
    SCREENSHOT = "screenshot"         # captura de tela (pasta/bytes/uri)
    OCR = "ocr"                       # texto extraído de captura de tela
    FILESYSTEM_STATE = "filesystem_state"  # estado de pastas/arquivos
    APPLICATION_STATE = "application_state"  # estado de apps abertos/ativos
    API_RESPONSE = "api_response"     # resposta de API REST/GraphQL


@dataclass(slots=True)
class Evidence:
    """Evidence observada após uma ação do ALPHA.

    A instância concretiza um ``EvidenceKind`` e preenche os campos
    correspondentes.  Campos de outros kinds são ``None`` (ou omitidos) para
    manter o registro enxuto — o agente pode inspecionar o ``kind`` e
    acessar apenas o subtipo relevante.
    """

    kind: EvidenceKind
    # Dados específicos de cada kind (os demais são ``None``).
    tool_result: Any | None = None  # ExecutionEvidence-like dict
    dom_state: Any | None = None    # dict with node info, selectors, etc.
    accessibility_state: Any | None = None  # dict with role, name, state, etc.
    screenshot: Any | None = None   # path, uri, or in-memory image data
    ocr: Any | None = None          # dict {text, confidence, bounding_box} or str
    filesystem_state: Any | None = None  # dict with cwd, listed, mounted, etc.
    application_state: Any | None = None  # dict with open windows, pid, etc.
    api_response: Any | None = None  # dict with status, body, headers, etc.


# ---------------------------------------------------------------------------
# VerificationResult — já definido em evidence.py (IntEnum), mas reexportado
# para conveniência na superfície pública.
# ---------------------------------------------------------------------------

__all__ = ["VerificationResult", "Evidence", "EvidenceKind"]  # type: ignore


# ---------------------------------------------------------------------------
# VerificationPolicy — determina quando a verificação é obrigatória,
# opcional ou dispensada.
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class VerificationPolicy:
    """Política de verificação que dita quais ações exigem confirmação
    de evidência antes de serem consideradas concluídas.

    A política é deliberadamente conservadora: verifica-se o que é barato
    (estado determinístico, resultado da tool, DOM, accessibility) e recorre
    a visão (OCR/screenshot) apenas quando a informação estruturada não
    for suficiente.
    """

    # Ações para as quais a verificação SEMPRE é obrigatória, independentemente
    # de serem "simples".  Estas correspondem a:
    # - ações sensíveis (código, shell, escritura de arquivo)
    # - ações destrutivas (exclusão, formatação de disco)
    # - mudanças importantes (cadastrar usuário, alterar configurações críticas)
    # - ações GUI ambíguas (clique em botão "Enviar" sem texto ao lado, etc.)
    # - pós-condições explicitamente marcadas como importantes pelo usuário.
    mandatory: frozenset[str] = field(
        default_factory=frozenset
        # Exemplo de uso futuro: frozenset({"run_code", "file_delete", "task_register_path"})
    )

    # Ações para as quais a verificação é opcional — o agente pode pular se
    # considerar a ação simples e determinística, mas deve registrar o
    # resultado da verificação (ou falta dela) no evidence.
    optional: frozenset[str] = field(
        default_factory=frozenset
        # Exemplo de uso futuro: frozenset({"browser_text", "system_status"})
    )

    # Quando ``True``, qualquer ação que não tenha evidência suficiente
    # resulta em ``VerificationResult.UNCERTAIN`` ao invés de SUCCESS.
    require_evidence: bool = True


# ---------------------------------------------------------------------------
# VerificationService — responsável por decidir se uma ação foi bem-sucedida
# ou falhou com base nas evidências observadas.
# ---------------------------------------------------------------------------

class VerificationService:
    """Serviço de verificação que decide se uma ação do ALPHA foi bem-sucedida.

    A estratégia é:
    1. Verificar evidências determinísticas primeiro (resultado da tool, DOM,
       accessibility, filesystem, API response).
    2. Recorrer a visão (OCR/screenshot) apenas quando a informação
       estruturada não for suficiente para afirmar SUCCESS ou FAILED.
    3. Se nem mesmo após visão houver evidência suficiente, retornar
       UNCERTAIN — nunca inventar SUCCESS.

    A política de verificação é passada na construção do serviço e dita
    quais ações exigem verificação obrigatória vs opcional.
    """

    def __init__(self, policy: VerificationPolicy | None = None) -> None:
        self.policy = policy or VerificationPolicy()

    # -----------------------------------------------------------------
    # Avaliação determinística — usada como primeira linha de verificação.
    # -----------------------------------------------------------------

    @staticmethod
    def _check_tool_result(evidence: Evidence) -> VerificationResult | None:
        """Verifica baseando-se no resultado da tool (success boolean + result).

        Retorna None quando o dicionário não contém informação suficiente
        para afirmar SUCCESS ou FAILED (ex.: dicionário vazio ou sem a chave
        ``success``), permitindo que a verificação caia para o próximo nível.
        """
        if evidence.kind != EvidenceKind.TOOL_RESULT:
            return None
        tr = evidence.tool_result
        if not isinstance(tr, dict) or not tr:
            # Dicionário vazio ou não-dict: sem informação concreta.
            return None
        success = tr.get("success")
        if success is None:
            # Chave ausente ou None → indeterminado.
            return None
        if success:
            return VerificationResult.SUCCESS
        return VerificationResult.FAILED

    @staticmethod
    def _check_dom_state(evidence: Evidence) -> VerificationResult | None:
        """Verifica baseando-se no estado do DOM após ação GUI."""
        if evidence.kind != EvidenceKind.DOM_STATE:
            return None
        ds = evidence.dom_state
        if not isinstance(ds, dict):
            return None
        # Critérios simplificados: se há indicativo de sucesso (ex.: mensagem,
        # classe de sucesso, novo elemento esperado), consideramos SUCCESS.
        # Caso contrário, FAILED.  Se não houver informação clara, retorna None
        # para que a verificação caia para o próximo nível.
        if ds.get("success") is True:
            return VerificationResult.SUCCESS
        if ds.get("error") is True:
            return VerificationResult.FAILED
        return None

    @staticmethod
    def _check_accessibility_state(evidence: Evidence) -> VerificationResult | None:
        """Verifica baseando-se no state da accessibility tree."""
        if evidence.kind != EvidenceKind.ACCESSIBILITY_STATE:
            return None
        as_ = evidence.accessibility_state
        if not isinstance(as_, dict):
            return None
        # Exemplo: role="pushbutton" state=checked => SUCCESS para toggle;
        # ausência de role/state conhecida => FAILED ou None.
        if as_.get("role") == "pushbutton" and as_.get("state", {}).get("checked") is True:
            return VerificationResult.SUCCESS
        if as_.get("role") == "pushbutton" and as_.get("state", {}).get("checked") is False:
            return VerificationResult.FAILED
        return None

    @staticmethod
    def _check_filesystem_state(evidence: Evidence) -> VerificationResult | None:
        """Verifica baseando-se no estado de filesystem."""
        if evidence.kind != EvidenceKind.FILESYSTEM_STATE:
            return None
        fs = evidence.filesystem_state
        if not isinstance(fs, dict):
            return None
        # Se o resultado da operação for "ok" ou o caminho existir, SUCCESS;
        # se houver mensagem de erro, FAILED.
        if fs.get("ok") is True or fs.get("exists") is True:
            return VerificationResult.SUCCESS
        if fs.get("error") is not None:
            return VerificationResult.FAILED
        return None

    @staticmethod
    def _check_api_response(evidence: Evidence) -> VerificationResult | None:
        """Verifica baseando-se em resposta de API."""
        if evidence.kind != EvidenceKind.API_RESPONSE:
            return None
        ar = evidence.api_response
        if not isinstance(ar, dict):
            return None
        if ar.get("status") in (200, 201):
            return VerificationResult.SUCCESS
        if ar.get("error") is not None:
            return VerificationResult.FAILED
        return None

    # -----------------------------------------------------------------
    # Verificação com visão (OCR/screenshot) — chamada apenas quando as
    # verificações determinísticas retornarem None (evidência insuficiente).
    # -----------------------------------------------------------------

    def _verify_with_vision(self, evidence: Evidence) -> VerificationResult:
        """Tenta verificação via visão.  Neste release a implementação é
        placeholder — em um release futuro integraria o OllamaVisionVerifier.

        Por agora, se a evidence tiver screenshot/ocr preenchidos, simulamos
        um resultado baseado nesses dados; caso contrário retornamos
        UNCERTAIN.
        """
        if evidence.kind == EvidenceKind.SCREENSHOT and evidence.screenshot is not None:
            # Placeholder: considera sucesso se screenshot existir eocr text for
            # não-vazio.  Em release futuro chamaria OllamaVisionVerifier.
            ocr_val = evidence.ocr
            if ocr_val and (isinstance(ocr_val, str) and ocr_val.strip() or
                           (isinstance(ocr_val, dict) and ocr_val.get("text", "").strip())):
                return VerificationResult.SUCCESS
            return VerificationResult.UNCERTAIN
        if evidence.kind == EvidenceKind.OCR and evidence.ocr is not None:
            ocr_val = evidence.ocr
            if isinstance(ocr_val, str) and ocr_val.strip():
                return VerificationResult.SUCCESS
            if isinstance(ocr_val, dict) and ocr_val.get("text", "").strip():
                return VerificationResult.SUCCESS
            return VerificationResult.UNCERTAIN
        return VerificationResult.UNCERTAIN

    # -----------------------------------------------------------------
    # API pública: verify — recebe Evidence e retorna VerificationResult.
    # -----------------------------------------------------------------

    def verify(self, evidence: Evidence) -> VerificationResult:
        """Executa o fluxo completo de verificação.

        Ordem:
        1. Verificações determinísticas (tool result, DOM, accessibility,
           filesystem, API response).
        2. Se todas retornarem None, tentativa de visão (OCR/screenshot).
        3. Se nada concreta for obtido, UNCERTAIN.
        """
        # 1. Verificações determinísticas
        for checker in (
            self._check_tool_result,
            self._check_dom_state,
            self._check_accessibility_state,
            self._check_filesystem_state,
            self._check_api_response,
        ):
            result = checker(evidence)
            if result is not None:
                return result

        # 2. Visão (fallback)
        vision_result = self._verify_with_vision(evidence)
        if vision_result is not None:
            return vision_result

        # 3. Nada suficiente → incerto
        return VerificationResult.UNCERTAIN

    # -----------------------------------------------------------------
    # Helper: aplicar política e decidir se a ação como um todo foi
    # bem-sucedida, considerando também a política de mandatory/optional.
    # -----------------------------------------------------------------

    def verify_with_policy(self, evidence: Evidence, action_name: str = "") -> VerificationResult:
        """Aplica a ``VerificationPolicy`` e devolve o resultado.

        Se a ação figurar na ``policy.mandatory`` e a verificação retornar
        ``UNCERTAIN``, o resultado permanece ``UNCERTAIN`` (não há SUCCESS
        automático por falta de verificação).

        Se a ação figurar na ``policy.optional`` e a verificação retornar
        ``SUCCESS``, o agente pode considerar a ação concluída sem exigir
        confirmação adicional (mas o evidence ainda registra o resultado).

        Em todos os casos, o método devolve o ``VerificationResult`` bruto
        calculado a partir das evidências.
        """
        result = self.verify(evidence)

        # Regra de política: se mandatory e incerto, mantém incerto.
        if self.policy.mandatory and action_name and action_name in self.policy.mandatory:
            if result == VerificationResult.UNCERTAIN:
                return VerificationResult.UNCERTAIN

        # Política opcional não altera o resultado calculado, mas o agente
        # pode usar o resultado para decidir se continua ou pede confirmação.
        return result