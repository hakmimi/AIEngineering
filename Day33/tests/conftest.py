import pytest

from config import settings


@pytest.fixture
def settings_override():
    """Temporarily change fields of the frozen settings object; always restored."""
    saved = {}

    def apply(**changes):
        for key, value in changes.items():
            saved.setdefault(key, getattr(settings, key))
            object.__setattr__(settings, key, value)

    yield apply
    for key, value in saved.items():
        object.__setattr__(settings, key, value)
