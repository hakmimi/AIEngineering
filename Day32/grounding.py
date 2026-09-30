"""Check that model-written text does not invent numbers (same idea as Month 1's output guard).

Every number with >= 2 digits or a decimal in the text must appear in the source material the model was given.
Formats are normalised (84 == 84.0, 1,000 == 1000) and percentages of known fractions are accepted (0.75 == 75%).
"""
import re

_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def _canonical(token: str) -> str:
    value = float(token)
    return str(int(value)) if value.is_integer() else repr(round(value, 6))


def numbers_in(text: str) -> set[str]:
    found = set()
    for raw in _NUMBER.findall(text):
        token = raw.replace(",", "").rstrip(".")
        if token and (len(token.replace(".", "")) >= 2 or "." in token):
            found.add(_canonical(token))
    return found


def _with_percent_forms(numbers: set[str]) -> set[str]:
    """0.75 in the source may be written as 75% (or 75.0%) in prose, and vice versa."""
    extra = set()
    for n in numbers:
        value = float(n)
        extra.add(_canonical(str(round(value * 100, 6))))
        extra.add(_canonical(str(round(value / 100, 6))))
    return numbers | extra


def ungrounded_numbers(text: str, source: str) -> list[str]:
    """Numbers in `text` that appear nowhere in `source` (empty list = grounded)."""
    return sorted(numbers_in(text) - _with_percent_forms(numbers_in(source)), key=float)
