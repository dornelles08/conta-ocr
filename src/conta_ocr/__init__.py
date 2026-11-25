import uvicorn


def main() -> None:
    uvicorn.run("conta_ocr.app:app", host="127.0.0.1", port=8000, reload=True)
