import cv2
import numpy as np


def _ordenar(pts: np.ndarray) -> np.ndarray:
    """4 pontos -> topo-esq, topo-dir, base-dir, base-esq."""
    soma, dif = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[soma.argmin()], pts[dif.argmin()], pts[soma.argmax()], pts[dif.argmax()]],
        dtype="float32",
    )


def recortar_papel(img: np.ndarray) -> np.ndarray:
    """Acha a folha sobre a mesa e corrige a perspectiva.

    A folha é clara e pouco saturada; a mesa de madeira é mais saturada e
    cabos/telefone são escuros. Sem folha plausível, devolve a imagem original.
    """
    escala = 1000 / max(img.shape[:2])
    small = cv2.resize(img, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    hsv = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2HSV), (7, 7), 0)
    sat, val = hsv[..., 1], hsv[..., 2]
    _, pouco_saturado = cv2.threshold(
        sat, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    mask = cv2.bitwise_and(pouco_saturado, (val > 120).astype(np.uint8) * 255)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))

    contornos, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return img
    maior = max(contornos, key=cv2.contourArea)
    if cv2.contourArea(maior) < 0.2 * mask.shape[0] * mask.shape[1]:
        return img

    quad = cv2.approxPolyDP(maior, 0.02 * cv2.arcLength(maior, True), True)
    if len(quad) != 4:
        quad = cv2.boxPoints(cv2.minAreaRect(maior))
    tl, tr, br, bl = _ordenar(quad.reshape(4, 2).astype("float32") / escala)
    largura = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    altura = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if min(largura, altura) < 300:
        return img

    destino = np.array(
        [[0, 0], [largura - 1, 0], [largura - 1, altura - 1], [0, altura - 1]],
        dtype="float32",
    )
    origem = np.array([tl, tr, br, bl], dtype="float32")
    return cv2.warpPerspective(
        img, cv2.getPerspectiveTransform(origem, destino), (largura, altura)
    )
