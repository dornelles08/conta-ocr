from pathlib import Path

import pytest

from conta_ocr.parsers.igua import IguaParser

DATA = Path(__file__).parent / "data"

CASOS = {
    "igua_2026_10.txt": {
        "referencia": "2026-10",
        "vencimento": "2026-10-29",
        "total": "212.39",
        "consumo_faturado_m3": 16,
        "agua": "115.39",
        "esgoto": "92.31",
        "multa": "4.20",
        "juros": "0.49",
        "pis": "3.50",
        "cofins": "16.14",
    },
    "igua_2026_11.txt": {
        "referencia": "2026-11",
        "vencimento": "2026-11-30",
        "total": "325.63",
        "consumo_faturado_m3": 21,
        "agua": "176.22",
        "esgoto": "140.97",
        "multa": "4.25",
        "juros": "0.71",
        "correcao": "3.48",
        "pis": "5.26",
        "cofins": "24.42",
        "cbs": "2.90",
    },
}


@pytest.mark.parametrize("arquivo, esperado", CASOS.items())
def test_igua(arquivo, esperado):
    texto = (DATA / arquivo).read_text(encoding="utf-8")
    parser = IguaParser()
    assert parser.matches(texto)
    campos, avisos = parser.parse(texto)
    assert avisos == []
    for chave, valor in esperado.items():
        assert campos[chave] == valor, chave


def test_erro_de_ocr_vira_aviso():
    texto = (
        (DATA / "igua_2026_10.txt")
        .read_text(encoding="utf-8")
        .replace("92,31", "92,81")
    )
    _, avisos = IguaParser().parse(texto)
    assert avisos  # a soma e o percentual de esgoto não fecham mais
