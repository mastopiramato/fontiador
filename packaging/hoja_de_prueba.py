"""Dibuja una hoja de prueba de la fuente demo, para revisarla a ojo.

    py packaging/hoja_de_prueba.py

Escribe build/prueba-fuente-demo.png

Se rasteriza a mano con la regla par-impar en vez de rellenar cada anillo por
separado: si no, los contrapunzones (el agujero de la O, la panza de la a) salen
rellenos y la fuente parece un desastre aunque esté bien.
"""

import os
import sys

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTE = os.path.join(RAIZ, "templates", "FontiadorDemo-Regular.otf")
SALIDA = os.path.join(RAIZ, "build", "prueba-fuente-demo.png")

ESCALA = 0.085
LINEAS = [
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    ".,;:!¡?¿()[]{}'\"«»",
    "-–—_/\\|+=*&%$#@~^<>°",
    "ÁÉÍÓÚÑáéíóúñ ı˙",
]
TEXTO = ["Handgloves 2026", "El veloz murciélago hindú", "¿Qué? ¡Fontiador!"]


class Aplanador(BasePen):
    """Convierte el glifo en anillos de puntos."""

    def __init__(self, glifo):
        super().__init__(glifo)
        self.anillos, self.actual = [], []

    def _moveTo(self, p):
        if self.actual:
            self.anillos.append(self.actual)
        self.actual = [p]

    def _lineTo(self, p):
        self.actual.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.actual[-1]
        for i in range(1, 13):
            t = i / 12.0
            mt = 1 - t
            self.actual.append((
                mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))

    def _closePath(self):
        if self.actual:
            self.anillos.append(self.actual)
            self.actual = []

    def _endPath(self):
        if self.actual:
            self.anillos.append(self.actual)
            self.actual = []


def dentro(x, y, anillos):
    """Regla par-impar: cuenta cuántos anillos encierran el punto."""
    cruces = 0
    for anillo in anillos:
        n = len(anillo)
        for i in range(n):
            x1, y1 = anillo[i]
            x2, y2 = anillo[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < xi:
                    cruces += 1
    return cruces % 2 == 1


def dibujar_glifo(capas, font, ch, x, y_base):
    """Rasteriza el glifo sobre una capa de máscara y devuelve su avance."""
    cmap = font.getBestCmap()
    if ord(ch) not in cmap:
        return font["head"].unitsPerEm * 0.5 * ESCALA
    nombre = cmap[ord(ch)]
    avance = font["hmtx"][nombre][0]

    pen = Aplanador(font.getGlyphSet())
    font.getGlyphSet()[nombre].draw(pen)
    anillos = []
    for a in pen.anillos:
        # En la fuente la Y crece hacia arriba y en la imagen hacia abajo: por eso
        # se SUMA. Restando, el texto sale espejado verticalmente.
        pts = [(x + px * ESCALA, y_base + py * ESCALA) for px, py in a]
        if len(pts) >= 3:
            anillos.append(pts)
    if not anillos:
        return avance * ESCALA

    xs = [p[0] for a in anillos for p in a]
    ys = [p[1] for a in anillos for p in a]
    ancho_img, alto_img = capas.size
    x0 = max(0, int(min(xs)) - 1)
    x1 = min(ancho_img, int(max(xs)) + 2)
    y0 = max(0, int(min(ys)) - 1)
    y1 = min(alto_img, int(max(ys)) + 2)
    for py in range(y0, y1):
        for px in range(x0, x1):
            if dentro(px + 0.5, py + 0.5, anillos):
                capas.putpixel((px, py), 0)
    return avance * ESCALA


def main():
    if not os.path.exists(FUENTE):
        raise SystemExit("No existe la fuente demo. Ejecutá packaging/generar_fuente_demo.py")
    font = TTFont(FUENTE)
    em = font["head"].unitsPerEm
    alto_linea = em * ESCALA * 1.85
    ancho, margen = 1180, 40
    alto = int(margen * 2 + alto_linea * (len(LINEAS) + len(TEXTO) + 2))

    # Se dibuja sobre una máscara "L" y después se compone en blanco y negro.
    mascara = Image.new("L", (ancho, alto), 255)
    y = margen + alto_linea

    for texto in LINEAS:
        x = margen
        for ch in texto:
            x += 280 * ESCALA if ch == " " else dibujar_glifo(mascara, font, ch, x, y)
        y += alto_linea

    y += alto_linea * 0.5
    for texto in TEXTO:
        x = margen
        for ch in texto:
            x += 280 * ESCALA if ch == " " else dibujar_glifo(mascara, font, ch, x, y)
        y += alto_linea

    img = Image.merge("RGB", (mascara, mascara, mascara))
    d = ImageDraw.Draw(img)
    d.line([(margen, margen + alto_linea * 1.05), (ancho - margen, margen + alto_linea * 1.05)],
           fill=(220, 180, 210), width=1)

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    img.save(SALIDA)
    print("escrito:", SALIDA, "(%dx%d)" % img.size)


if __name__ == "__main__":
    main()
