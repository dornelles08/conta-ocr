import re
import unicodedata
from datetime import datetime
from decimal import Decimal


def br_decimal(s: str) -> Decimal:
    """'1.234,56' -> Decimal('1234.56')"""
    return Decimal(s.strip().replace(".", "").replace(",", "."))


def br_date(s: str) -> str:
    """'29/10/2026' -> '2026-10-29'"""
    return datetime.strptime(s, "%d/%m/%Y").date().isoformat()


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, espaços compactados e vírgula decimal colada."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r"(?<=\d) ?, ?(?=\d{2}\b)", ",", t)
    return re.sub(r"(?<=\d)\.(?=\d{2}\b)", ",", t)  # "325.63" -> "325,63"


def find(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.I | re.S)
    return m.group(1) if m else None
