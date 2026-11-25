import os
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
import pymupdf
import pytesseract

from .imagem import recortar_papel

MIN_TEXT_CHARS = 80  # abaixo disso, o PDF provavelmente é escaneado
ENGINE = os.getenv("OCR_ENGINE", "paddle")  # "paddle" | "tesseract"
PADDLE_V3 = bool(os.getenv("PADDLE_V3", "True"))


@dataclass
class TextResult:
    text: str
    source: str  # "pdf-text" | "ocr-paddle" | "ocr-tesseract"
    confidence: float | None  # 0-100, só para OCR


def detect_kind(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image"
    raise ValueError("Formato não suportado (use PDF, JPG ou PNG)")


# ---------- Tesseract (mantido para comparação) ----------
def _preprocess(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if max(gray.shape) < 2000:
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )


def ocr_tesseract(img: np.ndarray) -> tuple[str, float]:
    proc = _preprocess(img)
    cfg = "--psm 6"
    text = pytesseract.image_to_string(proc, lang="por", config=cfg)
    d = pytesseract.image_to_data(
        proc, lang="por", config=cfg, output_type=pytesseract.Output.DICT
    )
    confs = [
        float(c) for w, c in zip(d["text"], d["conf"]) if w.strip() and float(c) >= 0
    ]
    return text, (sum(confs) / len(confs) if confs else 0.0)


# ---------- PaddleOCR ----------
@lru_cache(maxsize=1)
def _paddle():
    from paddleocr import PaddleOCR  # import tardio: o Paddle é pesado

    if PADDLE_V3:
        print(os.getenv("PADDLE_LANG"))
        print(os.getenv("PADDLE_V3"))
        idioma = {"lang": os.environ["PADDLE_LANG"]} if os.getenv("PADDLE_LANG") else {}
        return PaddleOCR(
            **idioma,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_limit_type="max",
            text_det_limit_side_len=4000,
            enable_mkldnn=False,
        )

    return PaddleOCR(
        lang="pt",  # se reclamar do idioma, use "latin"
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_det_limit_type="max",  # não reduz a tira; se der erro de argumento, remova
        text_det_limit_side_len=4000,  # esta linha e a de cima
        enable_mkldnn=False,  # bug do oneDNN no PaddlePaddle 3.3 em CPU
    )


def _linhas(polys, textos) -> str:
    """Caixas soltas -> linhas de texto (de cima para baixo, da esquerda para a direita)."""
    itens = []
    for p, t in zip(polys, textos):
        p = np.asarray(p, dtype=float)
        itens.append((p[:, 1].mean(), p[:, 0].min(), p[:, 1].max() - p[:, 1].min(), t))
    if not itens:
        return ""
    altura = float(np.median([i[2] for i in itens]))
    linhas: list[list] = []
    for item in sorted(itens):
        if linhas and abs(item[0] - np.mean([i[0] for i in linhas[-1]])) < 0.6 * altura:
            linhas[-1].append(item)
        else:
            linhas.append([item])
    return "\n".join(
        " ".join(i[3] for i in sorted(l, key=lambda i: i[1])) for l in linhas
    )


def ocr_paddle(img: np.ndarray) -> tuple[str, float]:
    res = _paddle().predict(img)[0]
    scores = res["rec_scores"]
    conf = float(np.mean(scores)) * 100 if len(scores) else 0.0
    return _linhas(res["rec_polys"], res["rec_texts"]), conf


def ocr_image(img: np.ndarray) -> tuple[str, float]:
    print(f"ENGINE: {ENGINE}")
    return ocr_tesseract(img) if ENGINE == "tesseract" else ocr_paddle(img)


def extract_text(data: bytes) -> TextResult:
    fonte = f"ocr-{ENGINE}"
    if detect_kind(data) == "pdf":
        doc = pymupdf.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        if len(text.strip()) >= MIN_TEXT_CHARS:
            return TextResult(text, "pdf-text", None)
        textos, confs = [], []
        for page in doc:  # PDF escaneado: rasteriza cada página
            png = page.get_pixmap(dpi=300).tobytes("png")
            img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
            t, c = ocr_image(img)
            textos.append(t)
            confs.append(c)
        return TextResult("\n".join(textos), fonte, sum(confs) / len(confs))

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Não foi possível abrir a imagem")
    text, conf = ocr_image(recortar_papel(img))
    return TextResult(text, fonte, conf)
