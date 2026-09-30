"""Deterministic guardrails - cheap, testable, run BEFORE and AFTER the model.

Input side  (check_input):  reject text the assistant must not process - unintelligible input and
                            attempts to override its instructions / extract its prompt.
Output side (check_output): validate the model's answer against a contract and against the evidence -
                            shape, length, prompt leakage, and *numbers that are not in the sources*.

Design choices
* Rules, not another LLM: free, ~0 ms, explainable, and unit-testable. Their weakness is coverage
  (paraphrases, other languages) - measured in scripts/guardrail_eval.py, not hidden.
* Patterns are deliberately narrow: a false positive blocks a legitimate user, which is worse than a
  missed attack on a system whose worst case is a refusal (retrieval + grounded prompt are the next layers).
"""
import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# --- input -----------------------------------------------------------------------------------------------
_INJECTION_PATTERNS = [
    ("override_instructions", r"\b(ignore|disregard|forget|bypass|override)\b.{0,25}\b(instructions?|rules?|prompts?|guidelines?|guardrails?|safety)\b"),
    ("extract_prompt", r"\b(reveal|show|print|display|repeat|output|leak|tell me|give me)\b.{0,25}\b(system|initial|hidden|developer|original|secret)\s+(prompt|instructions?|message|rules?)\b"),
    ("system_prompt_mention", r"\bsystem\s+prompt\b"),
    ("special_mode", r"\b(developer|debug|god|admin|jailbreak|sudo)\s+mode\b"),
    ("role_override", r"\byou\s+are\s+now\s+(in|a|an|the|no longer)\b"),
    ("pretend", r"\bpretend\s+(to\s+be|you\s+are|that\s+you)\b"),
    ("dan", r"\b(DAN|do anything now)\b"),
    ("act_unrestricted", r"\bact\s+as\s+(if\s+you\s+have\s+no|an?\s+(unrestricted|unfiltered|jailbroken|evil))\b"),
]
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE if name != "dan" else 0)) for name, pattern in _INJECTION_PATTERNS]


@dataclass(frozen=True)
class InputCheck:
    blocked: bool
    category: str | None = None   # unintelligible | prompt_injection
    reason: str | None = None


def check_input(text: str) -> InputCheck:
    stripped = (text or "").strip()
    letters = [c for c in stripped if unicodedata.category(c).startswith(("L", "N"))]
    if not letters:
        return InputCheck(True, "unintelligible", "no letters or digits (punctuation/emoji only)")
    if len(stripped) >= 20 and len(letters) / len(stripped) < 0.3:
        return InputCheck(True, "unintelligible", "mostly non-alphanumeric characters")
    if re.search(r"(.)\1{19,}", stripped):
        return InputCheck(True, "unintelligible", "long run of one repeated character")
    words = stripped.lower().split()
    if len(words) >= 12 and len(set(words)) <= 2:
        return InputCheck(True, "unintelligible", "the same word repeated")
    for name, pattern in _COMPILED:
        if pattern.search(stripped):
            return InputCheck(True, "prompt_injection", name)
    return InputCheck(False)


# --- output -----------------------------------------------------------------------------------------------
class AnswerContract(BaseModel):
    """What a valid answer looks like before it may leave the system."""
    model_config = ConfigDict(str_strip_whitespace=True)     # "   " must count as empty
    answer: str = Field(..., min_length=1, max_length=2000)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


_LEAK_MARKERS = ("<context>", "</context>", "answer from the context only", "rules:", "system prompt", "conversation so far")
_CITATION = re.compile(r"\[\s*\d[^\]]*\]")   # any bracket group that starts with a digit: [1:0]  [1:0|Masada]  [2:0,2:1; 5:0]
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def _canonical(token: str) -> str:
    """84 == 84.0 == 84.00 (so '84.' in prose matches a tool result of 84.0)."""
    value = float(token)
    return str(int(value)) if value.is_integer() else repr(value)


def _numbers(text: str) -> set[str]:
    """Numbers worth checking: >= 2 digits or decimals (so '1.' list markers and 'one/two' don't cause noise)."""
    found = set()
    for raw in _NUMBER.findall(_CITATION.sub(" ", text)):
        token = raw.replace(",", "").rstrip(".")
        if token and (len(token.replace(".", "")) >= 2 or "." in token):
            found.add(_canonical(token))
    return found


@dataclass
class OutputCheck:
    ok: bool
    answer: str
    confidence: float
    issues: list[str] = field(default_factory=list)


def check_output(answer, confidence, allowed_text: str) -> OutputCheck:
    """allowed_text = everything the answer may legitimately quote numbers from (context, question, tool result)."""
    issues: list[str] = []
    try:
        contract = AnswerContract(answer=answer if isinstance(answer, str) else "", confidence=confidence or 0.0)
    except ValidationError as exc:
        return OutputCheck(False, "", 0.0, [f"contract:{exc.errors()[0]['loc'][0]}"])

    lowered = contract.answer.lower()
    if any(marker in lowered for marker in _LEAK_MARKERS):
        issues.append("prompt_leak")
    unsupported = sorted(_numbers(contract.answer) - _numbers(allowed_text))
    if unsupported:
        issues.append("unsupported_numbers:" + ",".join(unsupported))
    return OutputCheck(not issues, contract.answer, contract.confidence, issues)
