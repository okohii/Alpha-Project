from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class VerificationResult(IntEnum):
    SUCCESS = 1
    FAILED = 2
    UNCERTAIN = 3


class EvidenceKind(StrEnum):
    TOOL_RESULT = "tool_result"
    DOM_STATE = "dom_state"
    ACCESSIBILITY_STATE = "accessibility_state"
    SCREENSHOT = "screenshot"
    OCR = "ocr"
    FILESYSTEM_STATE = "filesystem_state"
    APPLICATION_STATE = "application_state"
    API_RESPONSE = "api_response"


@dataclass(slots=True)
class Evidence:
    """Structured observation produced by an execution or perception step."""

    kind: EvidenceKind
    tool_result: Any | None = None
    dom_state: Any | None = None
    accessibility_state: Any | None = None
    screenshot: Any | None = None
    ocr: Any | None = None
    filesystem_state: Any | None = None
    application_state: Any | None = None
    api_response: Any | None = None
    # ``verified`` is metadata about this observation, not proof of success.
    verified: bool = False


@dataclass(slots=True)
class VerificationPolicy:
    mandatory: frozenset[str] = field(default_factory=frozenset)
    optional: frozenset[str] = field(default_factory=frozenset)
    require_evidence: bool = True


class VerificationService:
    """Conservative verifier: absence of proof is never treated as success."""

    def __init__(self, policy: VerificationPolicy | None = None) -> None:
        self.policy = policy or VerificationPolicy()

    @staticmethod
    def _check_tool_result(evidence: Evidence) -> VerificationResult | None:
        if evidence.kind != EvidenceKind.TOOL_RESULT:
            return None
        result = evidence.tool_result
        if not isinstance(result, dict) or "success" not in result:
            return None
        return VerificationResult.SUCCESS if result.get("success") is True else VerificationResult.FAILED

    @staticmethod
    def _check_dom_state(evidence: Evidence) -> VerificationResult | None:
        if evidence.kind != EvidenceKind.DOM_STATE or not isinstance(evidence.dom_state, dict):
            return None
        state = evidence.dom_state
        if state.get("success") is True:
            return VerificationResult.SUCCESS
        if state.get("error") is True:
            return VerificationResult.FAILED
        return None

    @staticmethod
    def _check_accessibility_state(evidence: Evidence) -> VerificationResult | None:
        if evidence.kind != EvidenceKind.ACCESSIBILITY_STATE or not isinstance(evidence.accessibility_state, dict):
            return None
        state = evidence.accessibility_state
        if state.get("success") is True:
            return VerificationResult.SUCCESS
        if state.get("error") is True:
            return VerificationResult.FAILED
        return None

    @staticmethod
    def _check_filesystem_state(evidence: Evidence) -> VerificationResult | None:
        if evidence.kind != EvidenceKind.FILESYSTEM_STATE or not isinstance(evidence.filesystem_state, dict):
            return None
        state = evidence.filesystem_state
        if state.get("ok") is True:
            return VerificationResult.SUCCESS
        if state.get("error") is not None:
            return VerificationResult.FAILED
        return None

    @staticmethod
    def _check_application_state(evidence: Evidence) -> VerificationResult | None:
        if evidence.kind != EvidenceKind.APPLICATION_STATE or not isinstance(evidence.application_state, dict):
            return None
        state = evidence.application_state
        if state.get("success") is True:
            return VerificationResult.SUCCESS
        if state.get("error") is True:
            return VerificationResult.FAILED
        return None

    @staticmethod
    def _check_api_response(evidence: Evidence) -> VerificationResult | None:
        if evidence.kind != EvidenceKind.API_RESPONSE or not isinstance(evidence.api_response, dict):
            return None
        response = evidence.api_response
        status = response.get("status")
        if isinstance(status, int) and 200 <= status < 300:
            return VerificationResult.SUCCESS
        if response.get("error") is not None:
            return VerificationResult.FAILED
        return None

    def _verify_with_vision(self, evidence: Evidence) -> VerificationResult:
        """No heuristic visual success: real vision verification is required."""
        # A screenshot/OCR being non-empty proves only that an observation
        # exists; it does not prove the requested goal was achieved.
        return VerificationResult.UNCERTAIN

    def verify(self, evidence: Evidence) -> VerificationResult:
        for checker in (
            self._check_tool_result,
            self._check_dom_state,
            self._check_accessibility_state,
            self._check_filesystem_state,
            self._check_application_state,
            self._check_api_response,
        ):
            result = checker(evidence)
            if result is not None:
                return result
        return self._verify_with_vision(evidence)

    def verify_with_policy(self, evidence: Evidence, action_name: str = "") -> VerificationResult:
        result = self.verify(evidence)
        if self.policy.require_evidence and result == VerificationResult.UNCERTAIN:
            return VerificationResult.UNCERTAIN
        if action_name in self.policy.mandatory and result != VerificationResult.SUCCESS:
            return result
        return result


__all__ = ["VerificationResult", "Evidence", "EvidenceKind", "VerificationPolicy", "VerificationService"]
