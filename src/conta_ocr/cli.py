"""Uso: uv run python -m conta_ocr.cli tests/fixtures/*.jpg"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv

from .extract import detect_kind, extract_text
from .imagem import recortar_papel
from .parsers import pick


def main() -> None:
    for arq in sys.argv[1:]:
        p = Path(arq)
        data = p.read_bytes()
        if detect_kind(data) == "image":
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            cv2.imwrite(str(p.with_name(p.stem + "_recorte.png")), recortar_papel(img))
        res = extract_text(data)
        p.with_suffix(".txt").write_text(res.text, encoding="utf-8")
        print(f"== {p.name} | fonte={res.source} | confiança={res.confidence}")
        parser = pick(res.text)
        if parser is None:
            print("empresa desconhecida; veja o .txt")
            continue
        campos, avisos = parser.parse(res.text)
        print(json.dumps(campos, indent=2, ensure_ascii=False))
        print("avisos:", avisos or "nenhum")


if __name__ == "__main__":
    load_dotenv()
    main()
