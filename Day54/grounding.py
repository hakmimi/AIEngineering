"""Check that model-written text does not invent numbers (same idea as Month 1's output guard).

Every number with >= 2 digits or a decimal in the text must be *derivable* from the source material the model was given:
  * exactly (84 == 84.0, 1,000 == 1000), or
  * as a percentage (0.75 in the source, "75%" in the text, and the other way round), or
  * by ordinary rounding to the precision the text uses ("92%" for a source value of 0.9235, "1.7" for 1.72).
Numbers that cannot be derived (a "97%" when the data says 0.75) are reported.
"""
import re

_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _numbers(text: str) -> list[str]:
    found = []
    for raw in _NUMBER.findall(text):
        token = raw.replace(",", "").rstrip(".")
        if token and (len(token.replace(".", "")) >= 2 or "." in token):
            found.append(token)
    return found


def numbers_in(text: str) -> set[str]:
    return {str(int(float(t))) if float(t).is_integer() else repr(round(float(t), 6)) for t in _numbers(text)}


def _derivable(token: str, source_values: list[float]) -> bool:
    value, places = float(token), _decimals(token)
    for s in source_values:
        for candidate in (s, s * 100, s / 100):
            if round(candidate, places) == round(value, places) or abs(candidate - value) < 1e-9:
                return True
    return False


def ungrounded_numbers(text: str, source: str) -> list[str]:
    """Numbers in `text` that cannot be derived from `source` (empty list = grounded)."""
    source_values = [float(t) for t in re.findall(r"\d[\d,]*\.?\d*", source.replace(",", "")) if t.rstrip(".")]
    bad = {t for t in _numbers(text) if not _derivable(t, source_values)}
    return sorted((str(int(float(t))) if float(t).is_integer() else t for t in bad), key=float)
