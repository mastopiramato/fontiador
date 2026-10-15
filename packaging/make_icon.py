"""Genera el icono de Fontiador (una 'A' sobre la linea base de la rejilla).

    py packaging/make_icon.py

Escribe packaging/icons/fontiador.png (256), fontiador-512.png y fontiador.ico.
Se dibuja con contornos rellenos y no con trazos, para que las uniones de la
"A" queden prolijas a cualquier tamano.
"""

import math
import os

from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(AQUI, "icons")

FONDO = (20, 20, 20, 255)
BORDE = (74, 74, 74, 255)
VERDE = (123, 212, 75, 255)
ROSA = (240, 111, 192, 255)
TEXTO = (240, 240, 240, 255)

ESCALA = 4  # sobremuestreo para suavizar


def _puntas(desde, hasta, ancho):
    """Cuadrilatero que representa un trazo grueso con extremos redondeados.

    Se arma el contorno con dos extremos semicirculares, asi ninguna union
    queda con el corte recto que se ve feo en las diagonales.
    """
    (x1, y1), (x2, y2) = desde, hasta
    dx, dy = x2 - x1, y2 - y1
    largo = math.hypot(dx, dy) or 1.0
    ux, uy = dx / largo, dy / largo          # direccion
    px, py = -uy, ux                          # perpendicular
    r = ancho / 2.0
    pts = [(x1 + px * r, y1 + py * r), (x2 + px * r, y2 + py * r)]
    # Semicirculo en el extremo final
    for i in range(1, 13):
        a = math.pi * i / 12.0
        pts.append((x2 + (px * math.cos(a) + ux * math.sin(a)) * r,
                    y2 + (py * math.cos(a) + uy * math.sin(a)) * r))
    pts.append((x1 - px * r, y1 - py * r))
    # Semicirculo en el extremo inicial
    for i in range(1, 13):
        a = math.pi * i / 12.0
        pts.append((x1 - (px * math.cos(a) + ux * math.sin(a)) * r,
                    y1 - (py * math.cos(a) + uy * math.sin(a)) * r))
    return pts


def dibujar(lado):
    n = lado * ESCALA
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    m = int(n * 0.055)
    d.rounded_rectangle([m, m, n - m - 1, n - m - 1], radius=int(n * 0.205),
                        fill=FONDO, outline=BORDE, width=max(1, int(n * 0.011)))

    ancho = n * 0.108
    apex = (n * 0.485, n * 0.175)
    izq = (n * 0.215, n * 0.735)
    der = (n * 0.775, n * 0.735)
    for a, b in ((apex, izq), (apex, der)):
        d.polygon(_puntas(a, b, ancho), fill=TEXTO)

    # Travesano de la A
    ty = n * 0.555
    d.polygon(_puntas((n * 0.305, ty), (n * 0.665, ty), ancho * 0.85), fill=TEXTO)

    # Linea base verde
    by = n * 0.795
    d.polygon(_puntas((n * 0.135, by), (n * 0.865, by), n * 0.030), fill=VERDE)

    # Punto rosa: la marca de las tildes
    r = n * 0.046
    cx, cy = n * 0.735, n * 0.235
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ROSA)

    return img.resize((lado, lado), Image.LANCZOS)


def main():
    os.makedirs(DESTINO, exist_ok=True)
    for lado, nombre in ((256, "fontiador.png"), (512, "fontiador-512.png")):
        p = os.path.join(DESTINO, nombre)
        dibujar(lado).save(p)
        print("escrito:", p)

    # El .ico necesita un solo archivo con varios tamanos; se arma del de 256.
    ico = os.path.join(DESTINO, "fontiador.ico")
    base = dibujar(256)
    base.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("escrito:", ico)


if __name__ == "__main__":
    main()
