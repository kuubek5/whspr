"""Контрактний тест формату ліцензійних ключів KuubWave (whspr).

Ключі з tests/fixtures/license_contract.json видає сервіс kuub.win (підписані
ПУБЛІЧНИМ тестовим ключем). Тест підміняє LICENSE_PUBKEY_HEX і викликає власний
verify_key продукту. Див. LICENSE_CONTRACT.md.

Запуск: pytest tests/test_license_contract.py  (потрібні pytest + cryptography)
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import licensing  # noqa: E402

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "license_contract.json").read_text("utf-8"))


@pytest.fixture(autouse=True)
def _test_key(monkeypatch):
    monkeypatch.setattr(licensing, "LICENSE_PUBKEY_HEX", VECTORS["test_public_hex"])


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["payload"]["e"])
def test_service_key_verifies(case):
    assert licensing.verify_key(case["key"]) == case["payload"]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["payload"]["e"])
def test_tampered_key_rejected(case):
    key = case["key"]
    i = len(key) - 10  # символ у підписній частині (після крапки)
    assert i > key.index(".")
    flipped = "A" if key[i] != "A" else "B"
    with pytest.raises(Exception):
        licensing.verify_key(key[:i] + flipped + key[i + 1:])
