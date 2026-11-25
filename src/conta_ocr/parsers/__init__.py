from .igua import IguaParser

PARSERS = [IguaParser()]


def pick(text: str):
    return next((p for p in PARSERS if p.matches(text)), None)
