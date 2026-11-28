import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "kenyan" / "fixtures"


def load_fixture(name: str):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def fixture_loader():
    return load_fixture
