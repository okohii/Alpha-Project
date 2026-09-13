from __future__ import annotations

from app.agent.serialized import SerializedAgentCore
from app.evidence import Evidence, EvidenceKind, VerificationResult, VerificationService
from app.llm.base import ExecutionEvidence


def _core() -> SerializedAgentCore:
    # Os testes deste arquivo exercitam apenas a camada determinística de
    # verificação; não inicializam LLM, banco ou ferramentas reais.
    return object.__new__(SerializedAgentCore)


def test_tool_result_success_is_verifiable_at_tool_level():
    verifier = VerificationService()
    evidence = Evidence(
        kind=EvidenceKind.TOOL_RESULT,
        tool_result={"success": True, "response": {"ok": True}},
    )
    assert verifier.verify(evidence) is VerificationResult.SUCCESS


def test_screenshot_alone_is_not_goal_verification():
    verifier = VerificationService()
    evidence = Evidence(
        kind=EvidenceKind.SCREENSHOT,
        screenshot="screen.png",
        ocr={"text": "WhatsApp"},
    )
    assert verifier.verify(evidence) is VerificationResult.UNCERTAIN


def test_strict_gui_claim_is_rejected_without_postcondition():
    core = _core()
    execution = ExecutionEvidence(
        action_id="a1",
        tool="browser_click",
        arguments={"text": "Enviar"},
        executed_at="now",
        success=True,
        result={},
        verified=False,
        status="executed_unverified",
    )
    result = core._apply_honesty_gate(
        "Enviei a mensagem com sucesso.",
        [execution],
    )
    assert "não consegui verificar" in result.lower()
    assert "concluída" in result.lower()


def test_verified_postcondition_allows_success_claim():
    core = _core()
    execution = ExecutionEvidence(
        action_id="a1",
        tool="browser_click",
        arguments={"text": "Enviar"},
        executed_at="now",
        success=True,
        result={"postcondition_verified": True},
        verified=True,
        status="verified",
    )
    result = core._apply_honesty_gate(
        "Enviei a mensagem com sucesso.",
        [execution],
    )
    assert result == "Enviei a mensagem com sucesso."


def test_visual_verification_does_not_promote_unrelated_strict_action():
    """H9: prova visual de UMA ação não promove OUTRAS strict actions.

    Uma evidência só valida a propriedade que ela realmente suporta.
    """
    action = ExecutionEvidence(
        action_id="a1",
        tool="mouse_click",
        arguments={"x": 100, "y": 100},
        executed_at="now",
        success=True,
        result={"clicked": True},
        verified=False,
        status="executed_unverified",
    )
    visual = ExecutionEvidence(
        action_id="a2",
        tool="verify_screen",
        arguments={"goal": "o botão Enviar está ativo"},
        executed_at="now",
        success=True,
        result={"achieved": True},
        verified=True,
        status="verified",
    )

    # Sem generalização: a ação estrita permanece UNVERIFIED.
    assert action.verified is False
    assert action.status == "executed_unverified"
    assert visual.verified is True
