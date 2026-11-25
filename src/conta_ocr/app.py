from fastapi import FastAPI, HTTPException, UploadFile

from .extract import extract_text
from .parsers import pick

app = FastAPI(title="conta-ocr")
MAX_BYTES = 15 * 1024 * 1024


@app.post("/extrair")
def extrair(file: UploadFile):
    data = file.file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Arquivo muito grande")
    try:
        res = extract_text(data)
    except ValueError as e:
        raise HTTPException(415, str(e))

    parser = pick(res.text)
    base = {"fonte_texto": res.source, "confianca_ocr": res.confidence}
    if parser is None:
        return {**base, "status": "empresa_desconhecida", "texto_bruto": res.text}

    campos, avisos = parser.parse(res.text)
    precisa_revisao = bool(avisos) or (
        res.confidence is not None and res.confidence < 75
    )
    return {
        **base,
        "status": "revisar" if precisa_revisao else "ok",
        "empresa": parser.name,
        "tipo": parser.tipo,
        "campos": campos,
        "avisos": avisos,
        "texto_bruto": res.text,  # essencial para depurar regex
    }
