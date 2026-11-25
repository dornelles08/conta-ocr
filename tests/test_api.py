from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conta_ocr.app import app

client = TestClient(app)
FIXTURES = Path(__file__).parent / "fixtures"


def test_formato_invalido():
    r = client.post("/extrair", files={"file": ("x.txt", b"ola", "text/plain")})
    assert r.status_code == 415


@pytest.mark.skipif(not (FIXTURES / "energia.pdf").exists(), reason="sem fixture")
def test_energia_pdf():
    data = (FIXTURES / "energia.pdf").read_bytes()
    r = client.post(
        "/extrair", files={"file": ("energia.pdf", data, "application/pdf")}
    )
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "revisar"}
