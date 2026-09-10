"""Testes da camada Evidence & Verification do ALPHA.

Cobre: modelo Evidence/EvidenceKind, VerificationResult, VerificationPolicy,
VerificationService, e cenários de SUCCESS/FAILED/UNCERTAIN com retry e
políticas obrigatórias/opcionais.
"""
from __future__ import annotations

import pytest

from app.evidence import (
    Evidence,
    EvidenceKind,
    VerificationResult,
    VerificationPolicy,
    VerificationService,
)


# ---- 1. Modelagem Evidence/EvidenceKind ----------------------------------------------------------------------------


def test_evidence_kind_enum():
    assert EvidenceKind.TOOL_RESULT.value == "tool_result"
    assert EvidenceKind.DOM_STATE.value == "dom_state"
    assert EvidenceKind.ACCESSIBILITY_STATE.value == "accessibility_state"
    assert EvidenceKind.SCREENSHOT.value == "screenshot"
    assert EvidenceKind.OCR.value == "ocr"
    assert EvidenceKind.FILESYSTEM_STATE.value == "filesystem_state"
    assert EvidenceKind.APPLICATION_STATE.value == "application_state"
    assert EvidenceKind.API_RESPONSE.value == "api_response"


def test_evidence_construction():
    e = Evidence(kind=EvidenceKind.TOOL_RESULT, tool_result={"success": True, "data": "ok"})
    assert e.kind == EvidenceKind.TOOL_RESULT
    assert e.tool_result == {"success": True, "data": "ok"}
    assert e.dom_state is None
    assert e.screenshot is None


def test_evidence_all_kinds():
    e = Evidence(
        kind=EvidenceKind.SCREENSHOT,
        screenshot="/tmp/print.png",
        ocr={"text": "Enviar", "confidence": 0.97},
    )
    assert e.kind == EvidenceKind.SCREENSHOT
    assert e.screenshot == "/tmp/print.png"
    assert e.ocr == {"text": "Enviar", "confidence": 0.97}


# ---- 2. VerificationResult ---------------------------------------------------------------------------------------


def test_verification_result_values():
    assert VerificationResult.SUCCESS.value == 1
    assert VerificationResult.FAILED.value == 2
    assert VerificationResult.UNCERTAIN.value == 3


def test_verification_result_meaning():
    assert VerificationResult.SUCCESS.name == "SUCCESS"
    assert VerificationResult.FAILED.name == "FAILED"
    assert VerificationResult.UNCERTAIN.name == "UNCERTAIN"


# ---- 3. VerificationPolicy ---------------------------------------------------------------------------------------


def test_verification_policy_defaults():
    policy = VerificationPolicy()
    assert policy.mandatory == frozenset()
    assert policy.optional == frozenset()
    assert policy.require_evidence is True


def test_verification_policy_custom():
    policy = VerificationPolicy(
        mandatory={"run_code", "file_delete"},
        optional={"browser_text"},
        require_evidence=False,
    )
    assert "run_code" in policy.mandatory
    assert "file_delete" in policy.mandatory
    assert "browser_text" in policy.optional
    assert policy.require_evidence is False


# ---- 4. VerificationService --------------------------------------------------------------------------------------

service = VerificationService()


def _make_evidence(kind: EvidenceKind, **kwargs) -> Evidence:
    """Constrói um Evidence com os campos relevantes."""
    fields: dict[str, Any] = {"kind": kind}
    fields.update(kwargs)
    return Evidence(**fields)


# ---- 4.1 Sucessos determinísticos --------------------------------------------------------------------------------


def test_service_verifies_tool_result_success():
    ev = _make_evidence(EvidenceKind.TOOL_RESULT, tool_result={"success": True, "result": "ok"})
    result = service.verify(ev)
    assert result == VerificationResult.SUCCESS


def test_service_verifies_tool_result_failed():
    ev = _make_evidence(EvidenceKind.TOOL_RESULT, tool_result={"success": False, "error": "timeout"})
    result = service.verify(ev)
    assert result == VerificationResult.FAILED


def test_service_checks_dom_state_success():
    ev = _make_evidence(EvidenceKind.DOM_STATE, dom_state={"success": True})
    result = service.verify(ev)
    assert result == VerificationResult.SUCCESS


def test_service_checks_dom_state_failed():
    ev = _make_evidence(EvidenceKind.DOM_STATE, dom_state={"error": True})
    result = service.verify(ev)
    assert result == VerificationResult.FAILED


def test_service_checks_accessibility_state():
    ev = _make_evidence(
        EvidenceKind.ACCESSIBILITY_STATE,
        accessibility_state={"role": "pushbutton", "state": {"checked": True}},
    )
    result = service.verify(ev)
    assert result == VerificationResult.SUCCESS


def test_service_checks_filesystem_state():
    ev = _make_evidence(
        EvidenceKind.FILESYSTEM_STATE,
        filesystem_state={"ok": True, "path": "/tmp/test"},
    )
    result = service.verify(ev)
    assert result == VerificationResult.SUCCESS


def test_service_checks_api_response():
    ev = _make_evidence(
        EvidenceKind.API_RESPONSE,
        api_response={"status": 200, "body": "ok"},
    )
    result = service.verify(ev)
    assert result == VerificationResult.SUCCESS


# ---- 4.2 Falha determinística ------------------------------------------------------------------------------------


def test_service_fails_on_tool_error():
    ev = _make_evidence(EvidenceKind.TOOL_RESULT, tool_result={"success": False, "error": "timeout"})
    result = service.verify(ev)
    assert result == VerificationResult.FAILED


def test_fails_on_dom_error():
    ev = _make_evidence(EvidenceKind.DOM_STATE, dom_state={"error": True})
    result = service.verify(ev)
    assert result == VerificationResult.FAILED


# ---- 4.3 Fallback de visão -------------------------------------------------------------------------------------


def test_service_fallsback_to_vision_with_screenshot_and_ocr():
    ev = _make_evidence(
        EvidenceKind.SCREENSHOT,
        screenshot="/tmp/img.png",
        ocr={"text": "Enviar", "confidence": 0.95},
    )
    result = service.verify(ev)
    assert result == VerificationResult.SUCCESS


def test_service_fallsback_to_vision_with_ocr_only():
    ev = _make_evidence(EvidenceKind.OCR, ocr={"text": "Salvar", "confidence": 0.9})
    result = service.verify(ev)
    assert result == VerificationResult.SUCCESS


def test_service_uncertain_when_no_evidence():
    ev = _make_evidence(EvidenceKind.SCREENSHOT, screenshot=None)
    result = service.verify(ev)
    assert result == VerificationResult.UNCERTAIN


def test_uncertain_when_ocr_empty():
    ev = _make_evidence(EvidenceKind.OCR, ocr={"text": "", "confidence": 0.1})
    result = service.verify(ev)
    assert result == VerificationResult.UNCERTAIN


# ---- 4.4 verify_with_policy ------------------------------------------------------------------------------------


def test_verify_with_policy_mandatory_keeps_uncertain():
    policy = VerificationPolicy(
        mandatory={"run_code"},
        require_evidence=True,
    )
    svc = VerificationService(policy)
    ev = _make_evidence(EvidenceKind.TOOL_RESULT, tool_result={})  # sem success claro
    result = svc.verify_with_policy(ev, action_name="run_code")
    assert result == VerificationResult.UNCERTAIN


def test_verify_with_policy_optional_does_not_force_uncertain():
    policy = VerificationPolicy(optional={"browser_text"}, require_evidence=True)
    svc = VerificationService(policy)
    ev = _make_evidence(EvidenceKind.TOOL_RESULT, tool_result={"success": True})
    result = svc.verify_with_policy(ev, action_name="browser_text")
    assert result == VerificationResult.SUCCESS


# ---- 5. Integração com o fluxo ACT→OBSERVE→EVIDENCE→VERIFY→DONE ----------------------------------------------------------------------------


def test_evidence_collected_during_agent_execution():
    """Simula o agente coletando evidence durante o loop ACT↔OBSERVE.

    O agente executa uma tool, o ExecutionEvidence é criado e, em seguida,
    converte-se para o modelo Evidence para verificação.
    """
    # Simula um ExecutionEvidence (existente em app/llm/base.py)
    execution_evidence = type(
        "ExecutionEvidence",
        (),  # dyn. class
        {
            "action_id": "a1",
            "tool": "browser_click",
            "arguments": {"x": 10, "y": 20},
            "executed_at": "2026-01-01T12:00:00",
            "success": True,
            "result": {"clicked": "button"},
            "error": None,
            "verified": False,
        },
    )()

    # Converte para o novo modelo Evidence (os campos em comum são mapeados)
    evidence = Evidence(
        kind=EvidenceKind.TOOL_RESULT,
        tool_result={
            "action_id": execution_evidence.action_id,
            "tool": execution_evidence.tool,
            "arguments": execution_evidence.arguments,
            "success": execution_evidence.success,
            "result": execution_evidence.result,
            "error": execution_evidence.error,
        },
    )
    result = service.verify(evidence)
    assert result == VerificationResult.SUCCESS


def test_evidence_insufficient_triggers_uncertain():
    """Quando não há evidência suficiente, o verificationService retorna UNCERTAIN,
    nunca SUCCESS falso."""
    # Evidence sem nenhum dado concreto
    ev = Evidence(kind=EvidenceKind.TOOL_RESULT, tool_result={})
    result = service.verify(ev)
    assert result == VerificationResult.UNCERTAIN

    # Evidence de screenshot sem OCR também
    ev2 = Evidence(kind=EvidenceKind.SCREENSHOT, screenshot=None)
    result2 = service.verify(ev2)
    assert result2 == VerificationResult.UNCERTAIN