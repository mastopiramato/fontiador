"""Genera la fuente de demostración que viene con Fontiador.

Es una sans serif geométrica ORIGINAL, dibujada acá con rectángulos, círculos y
curvas. **No es Arial ni una copia de Arial**: Arial es una tipografía con
licencia de Monotype y no se puede redistribuir. Esta fuente existe para que
quien abre la app por primera vez tenga algo para probar sin dibujar nada, y de
paso sirve como prueba de humo del constructor de fuentes: se arma con el mismo
fontiador_builder que usa la app.

    py packaging/generar_fuente_demo.py

Escribe templates/FontiadorDemo-Regular.otf
"""

import math
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from fontiador_builder import build_font  # noqa: E402
import fontiador_server as app            # noqa: E402  (para el orden de caracteres)

# ---------------------------------------------------------------- geometría
CAP = 700        # altura de mayúscula
XH = 500         # altura de x
ASC = 750        # ascendente
DESC = 200       # descendente (por debajo de la línea base)
STROKE = 96      # grosor de trazo
OVERSHOOT = 12   # las curvas se pasan un poco para que no parezcan chicas

W = 600          # avance típico de mayúscula
WL = 560         # avance típico de minúscula


def rect(a, b, y0, y1):
    """Rectángulo cerrado, en sentido antihorario."""
    return [["M", a, y0], ["L", b, y0], ["L", b, y1], ["L", a, y1], ["Z"]]


def barra(x, ancho, y0, y1):
    """Trazo vertical."""
    return rect(x, x + ancho, y0, y1)


def barra_h(a, b, y, alto):
    """Trazo horizontal."""
    return rect(a, b, y, y + alto)


def _puntos(anillo, muestras=12):
    """Aplana un anillo a una lista de puntos, para poder medir su orientación."""
    pts, actual = [], (0.0, 0.0)
    for c in anillo:
        if c[0] == "M":
            actual = (c[1], c[2])
            pts.append(actual)
        elif c[0] == "L":
            actual = (c[1], c[2])
            pts.append(actual)
        elif c[0] == "C":
            p1, p2, p3 = (c[1], c[2]), (c[3], c[4]), (c[5], c[6])
            for i in range(1, muestras + 1):
                t = i / float(muestras)
                mt = 1 - t
                pts.append((
                    mt**3 * actual[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
                    mt**3 * actual[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]))
            actual = p3
    return pts


def _area_signada(anillo):
    """Area con signo (fórmula del cordón). Positivo = horario."""
    pts = _puntos(anillo)
    if len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _invertir(cmds):
    """Recorre el contorno al revés.

    Se arma la lista de tramos (op, inicio, puntos...). Recorriéndolos al revés,
    cada tramo va desde el punto donde terminaba el siguiente hasta donde
    empezaba él: una Bézier de p0 a p3 con controles c1 y c2 es la misma curva
    que va de p3 a p0 con controles c2 y c1.
    """
    ops = [list(c) for c in cmds if c[0] != "Z"]
    if len(ops) < 2:
        return [["Z"]]

    tramos = []                     # (op, inicio, [controles...])
    principio = (ops[0][1], ops[0][2])
    inicio = principio
    fin_ultimo = principio
    for c in ops[1:]:
        if c[0] == "L":
            tramos.append(("L", inicio, [(c[1], c[2])]))
            inicio = (c[1], c[2])
        elif c[0] == "C":
            tramos.append(("C", inicio, [(c[1], c[2]), (c[3], c[4]), (c[5], c[6])]))
            inicio = (c[5], c[6])
        else:
            tramos.append((c[0], inicio, [(c[-2], c[-1])]))
            inicio = (c[-2], c[-1])
        fin_ultimo = inicio

    nueva = [["M", fin_ultimo[0], fin_ultimo[1]]]
    for op, ini, pts in reversed(tramos):
        # Recorriendo al revés, este tramo va desde donde terminaba el siguiente
        # hasta su propio punto de partida.
        if op == "L":
            nueva.append(["L", ini[0], ini[1]])
        elif op == "C":
            c1, c2, _fin = pts
            nueva.append(["C", c2[0], c2[1], c1[0], c1[1], ini[0], ini[1]])
    nueva.append(["Z"])
    return nueva


def _con_sentido(anillo, horario=True):
    """Fuerza el sentido de giro del anillo, midiendo el área de verdad.

    No alcanza con razonar sobre el orden de los puntos: con curvas de por medio
    es fácil equivocarse. Se mide el área con signo y se da vuelta sólo si hace
    falta. Los huecos van al revés que el contorno exterior: si no, la letra
    queda como un manchón relleno.
    """
    positivo = _area_signada(anillo) > 0
    if positivo == horario:
        return anillo
    return _invertir(anillo)


def circulo(cx, cy, r, horario=True):
    """Círculo con curvas Bézier."""
    k = 0.5522847498 * r
    cmds = [["M", cx, cy - r]]
    segs = [
        (cx + k, cy - r, cx + r, cy - k, cx + r, cy),
        (cx + r, cy + k, cx + k, cy + r, cx, cy + r),
        (cx - k, cy + r, cx - r, cy + k, cx - r, cy),
        (cx - r, cy - k, cx - k, cy - r, cx, cy - r),
    ]
    for c1x, c1y, c2x, c2y, px, py in segs:
        cmds.append(["C", c1x, c1y, c2x, c2y, px, py])
    cmds.append(["Z"])
    return _con_sentido(cmds, horario)


def anillo(cx, cy, r_ext, grosor):
    """Anillo: contorno exterior y hueco, con sentidos opuestos."""
    return [circulo(cx, cy, r_ext, True), circulo(cx, cy, r_ext - grosor, False)]


def _bezier_arco(cx, cy, r, a0, a1):
    """Tramo de círculo como curvas Bézier, de a0 a a1 (radianes)."""
    cmds = []
    n = max(1, int(abs(a1 - a0) / (math.pi / 2)) + 1)
    paso = (a1 - a0) / n
    for i in range(n):
        t0 = a0 + paso * i
        t1 = t0 + paso
        k = 4.0 / 3.0 * math.tan((t1 - t0) / 4.0)
        p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
        p3 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
        c1 = (p0[0] - k * r * math.sin(t0), p0[1] + k * r * math.cos(t0))
        c2 = (p3[0] + k * r * math.sin(t1), p3[1] - k * r * math.cos(t1))
        if i == 0:
            cmds.append(["M", p0[0], p0[1]])
        cmds.append(["C", c1[0], c1[1], c2[0], c2[1], p3[0], p3[1]])
    return cmds


def arco(cx, cy, r, desde, hasta, grosor):
    """Arco de círculo relleno, con curvas de verdad a los dos lados."""
    a0, a1 = math.radians(desde), math.radians(hasta)
    exterior = _bezier_arco(cx, cy, r, a0, a1)
    interior = _invertir(_bezier_arco(cx, cy, r - grosor, a0, a1))
    # Se recorre el exterior, se cruza al interior y se vuelve por él al principio.
    cuerpo = ([["M", exterior[0][1], exterior[0][2]]]
              + [c for c in exterior[1:]]
              + [["L", interior[0][1], interior[0][2]]]
              + [c for c in interior[1:]]
              + [["Z"]])
    return _con_sentido(cuerpo, True)


def triangulo(p1, p2, p3):
    return [["M", p1[0], p1[1]], ["L", p2[0], p2[1]], ["L", p3[0], p3[1]], ["Z"]]


def linea(x1, y1, x2, y2, grosor):
    """Segmento grueso."""
    dx, dy = x2 - x1, y2 - y1
    largo = math.hypot(dx, dy) or 1
    px, py = -dy / largo * grosor / 2, dx / largo * grosor / 2
    pts = [(x1 + px, y1 + py), (x2 + px, y2 + py), (x2 - px, y2 - py), (x1 - px, y1 - py)]
    cmds = [["M", pts[0][0], pts[0][1]]]
    for x, y in pts[1:]:
        cmds.append(["L", x, y])
    cmds.append(["Z"])
    return cmds


# ------------------------------------------------------------------ glifos
# Cada glifo es (ancho de avance, [lista de contornos]).
# El eje X va de 0 al ancho; la línea base es y=0 y las mayúsculas llegan a CAP.
G = {}


def g(ch, ancho, *contornos):
    G[ch] = (ancho, list(contornos))


# --- Mayúsculas ---
g("A", 680, triangulo((150, 0), (300, 700), (380, 700)), triangulo((300, 700), (530, 0), (450, 0)),
  barra_h(200, 480, 210, STROKE))
g("B", 620, barra(120, STROKE, 0, CAP),
  barra_h(120, 500, CAP - STROKE, STROKE), barra_h(120, 500, 340, STROKE), barra_h(120, 500, 0, STROKE),
  barra(500, STROKE, 350, CAP - STROKE), barra(500, STROKE, 0, 350))
g("C", 660, arco(330, 350, 290, 55, 305, STROKE))
g("D", 660, barra(120, STROKE, 0, CAP), barra_h(120, 380, CAP - STROKE, STROKE),
  barra_h(120, 380, 0, STROKE), barra(480, STROKE, 150, CAP - 150))
g("E", 580, barra(120, STROKE, 0, CAP), barra_h(120, 400, CAP - STROKE, STROKE),
  barra_h(120, 360, 320, STROKE), barra_h(120, 400, 0, STROKE))
g("F", 560, barra(120, STROKE, 0, CAP), barra_h(120, 400, CAP - STROKE, STROKE),
  barra_h(120, 340, 340, STROKE))
g("G", 680, arco(340, 350, 290, 55, 305, STROKE), barra(510, STROKE, 200, 350),
  barra_h(360, 270, 200, STROKE))
g("H", 660, barra(120, STROKE, 0, CAP), barra(450, STROKE, 0, CAP),
  barra_h(120, 426, 310, STROKE))
g("I", 300, barra(100, STROKE, 0, CAP))
g("J", 520, barra(380, STROKE, 170, CAP), arco(260, 170, 120, 180, 360, STROKE))
g("K", 640, barra(120, STROKE, 0, CAP), linea(520, CAP, 140, 300, STROKE),
  linea(250, 380, 540, 0, STROKE))
g("L", 520, barra(120, STROKE, 0, CAP), barra_h(120, 340, 0, STROKE))
g("M", 780, barra(120, STROKE, 0, CAP), barra(560, STROKE, 0, CAP),
  linea(168, CAP, 340, 320, STROKE), linea(512, CAP, 340, 320, STROKE))
g("N", 680, barra(120, STROKE, 0, CAP), barra(460, STROKE, 0, CAP),
  linea(168, CAP, 508, 0, STROKE))
g("O", 700, anillo(350, 350, 300 + OVERSHOOT, STROKE))
g("P", 620, barra(120, STROKE, 0, CAP), barra_h(120, 400, CAP - STROKE, STROKE),
  barra_h(120, 400, 330, STROKE), barra(430, STROKE, 330, CAP - STROKE))
g("Q", 700, anillo(350, 350, 300 + OVERSHOOT, STROKE),
  linea(420, 160, 580, -40, STROKE))
g("R", 640, barra(120, STROKE, 0, CAP), barra_h(120, 400, CAP - STROKE, STROKE),
  barra_h(120, 400, 330, STROKE), barra(430, STROKE, 330, CAP - STROKE),
  linea(300, 330, 560, 0, STROKE))
g("S", 620, arco(310, 520, 185, -30, 145, STROKE), arco(310, 190, 185, 150, 340, STROKE))
g("T", 600, barra_h(60, 480, CAP - STROKE, STROKE), barra(252, STROKE, 0, CAP))
g("U", 660, barra(120, STROKE, 200, CAP), barra(450, STROKE, 200, CAP),
  arco(310, 200, 194, 180, 360, STROKE))
g("V", 680, linea(150, CAP, 300, 0, STROKE), linea(454, CAP, 300, 0, STROKE))
g("W", 900, linea(140, CAP, 260, 0, STROKE), linea(378, CAP, 470, 130, STROKE),
  linea(562, CAP, 470, 130, STROKE), linea(700, CAP, 580, 0, STROKE))
g("X", 640, linea(130, CAP, 510, 0, STROKE), linea(510, CAP, 130, 0, STROKE))
g("Y", 640, linea(140, CAP, 300, 330, STROKE), linea(460, CAP, 300, 330, STROKE),
  barra(252, STROKE, 0, 330))
g("Z", 620, barra_h(110, 420, CAP - STROKE, STROKE), barra_h(110, 420, 0, STROKE),
  linea(510, CAP - STROKE // 2, 130, STROKE // 2, STROKE))

# --- Minúsculas ---
g("a", 560, anillo(280, 260, 240, STROKE), barra(424, STROKE, 20, 500))
g("b", 580, barra(120, STROKE, 0, 740), anillo(320, 260, 240, STROKE))
g("c", 540, arco(285, 260, 235, 50, 310, STROKE))
g("d", 580, anillo(260, 260, 240, STROKE), barra(404, STROKE, 0, 740))
g("e", 560, anillo(280, 260, 240, STROKE), barra_h(52, 456, 250, STROKE))
g("f", 340, barra(120, STROKE, 0, 620), arco(220, 620, 100, 0, 180, STROKE),
  barra_h(70, 260, 500, STROKE))
g("g", 580, anillo(280, 260, 240, STROKE), barra(424, STROKE, -180, 500),
  arco(280, -180, 240, 180, 360, STROKE))
g("h", 560, barra(120, STROKE, 0, 740), barra(400, STROKE, 0, 400),
  arco(280, 400, 168, 0, 180, STROKE))
g("i", 260, barra(82, STROKE, 0, XH), circulo(130, 660, STROKE // 2 + 14, 6))
g("j", 260, barra(82, STROKE, -140, XH), circulo(130, 660, STROKE // 2 + 14, 6),
  arco(82, -140, 100, 180, 360, STROKE))
g("k", 540, barra(120, STROKE, 0, 740), linea(430, XH, 160, 250, STROKE),
  linea(250, 320, 450, 0, STROKE))
g("l", 260, barra(82, STROKE, 0, 740))
g("m", 860, barra(120, STROKE, 0, 400), barra(360, STROKE, 0, 400),
  barra(600, STROKE, 0, 400), arco(240, 400, 168, 0, 180, STROKE),
  arco(480, 400, 168, 0, 180, STROKE))
g("n", 560, barra(120, STROKE, 0, 400), barra(400, STROKE, 0, 400),
  arco(280, 400, 168, 0, 180, STROKE))
g("o", 580, anillo(290, 255, 245, STROKE))
g("p", 580, barra(120, STROKE, -210, 500), anillo(320, 260, 240, STROKE))
g("q", 580, anillo(260, 260, 240, STROKE), barra(404, STROKE, -210, 500))
g("r", 380, barra(120, STROKE, 0, 500), arco(300, 400, 150, 0, 110, STROKE))
g("s", 520, arco(260, 375, 138, -20, 150, STROKE), arco(260, 135, 138, 160, 340, STROKE))
g("t", 360, barra(150, STROKE, 60, 660), barra_h(60, 280, 520, STROKE),
  arco(270, 60, 120, 180, 330, STROKE))
g("u", 560, barra(120, STROKE, 100, 500), barra(400, STROKE, 0, 500),
  arco(280, 100, 168, 180, 360, STROKE))
g("v", 540, linea(120, XH, 265, 0, STROKE), linea(410, XH, 265, 0, STROKE))
g("w", 740, linea(110, XH, 215, 0, STROKE), linea(320, XH, 370, 130, STROKE),
  linea(420, XH, 370, 130, STROKE), linea(525, XH, 630, 0, STROKE))
g("x", 540, linea(120, XH, 420, 0, STROKE), linea(420, XH, 120, 0, STROKE))
g("y", 540, linea(120, XH, 265, 60, STROKE), linea(410, XH, 200, -210, STROKE))

# La z se dibuja con los mismos trazos que la Z mayúscula, a altura de x
g("z", 520, barra_h(100, 340, XH - STROKE, STROKE), barra_h(100, 340, 0, STROKE),
  linea(420, XH - STROKE // 2, 110, STROKE // 2, STROKE))

# --- Acentos y marcas del template ---
g("ı", 260, barra(82, STROKE, 0, XH))               # palo de la i, sin punto
g("´", 300, linea(110, 700, 210, 830, 70))          # acento agudo
g("˙", 300, circulo(150, 700, 55))                  # punto de la i
g("°", 380, anillo(190, 620, 110, 60))
g("«", 560, triangulo((300, 250), (170, 110), (170, 390)),
  triangulo((300, 40), (170, -100), (170, 180)))
g("»", 560, triangulo((260, 250), (390, 110), (390, 390)),
  triangulo((260, 40), (390, -100), (390, 180)))

# --- Números ---
for ch, ancho in (("0", 620), ("1", 620), ("2", 620), ("3", 620), ("4", 620),
                  ("5", 620), ("6", 620), ("7", 620), ("8", 620), ("9", 620)):
    pass

g("0", 620, anillo(310, 345, 300, STROKE))
g("1", 620, barra(262, STROKE, 0, 690), linea(180, 560, 310, 690, STROKE),
  barra_h(160, 300, 0, STROKE))
g("2", 620, arco(310, 490, 195, 170, 350, STROKE), linea(160, 480, 460, 0, STROKE),
  barra_h(120, 390, 0, STROKE))
g("3", 620, arco(310, 505, 190, -60, 180, STROKE), arco(310, 185, 190, 180, 420, STROKE))
g("4", 620, linea(400, 690, 130, 240, STROKE), barra_h(110, 430, 240, STROKE),
  barra(370, STROKE, 0, 690))
g("5", 620, barra_h(150, 340, 630, STROKE), barra(150, STROKE, 320, 630),
  arco(310, 300, 250, -60, 180, STROKE))
g("6", 620, arco(310, 300, 250, 90, 330, STROKE), anillo(310, 245, 215, STROKE))
g("7", 620, barra_h(130, 380, 630, STROKE), linea(510, 690, 210, 0, STROKE))
g("8", 620, anillo(310, 505, 175, STROKE), anillo(310, 175, 215, STROKE))
g("9", 620, anillo(310, 445, 215, STROKE), arco(310, 390, 250, -150, 90, STROKE))

# --- Puntuación y símbolos ---
g(" ", 300)                                                   # espacio
g('"', 400, barra(110, 74, 520, 700), barra(240, 74, 520, 700))
g(",", 300, rect(110, 200, -40, 90), triangulo((110, 30), (200, 30), (120, -120)))
g(".", 300, rect(115, 205, 0, 90))
g("!", 300, barra(112, 76, 170, 700), rect(112, 188, 0, 90))
g("¡", 300, barra(112, 76, 0, 530), rect(112, 188, 610, 700))
g("¿", 560, arco(280, 190, 150, 20, 160, STROKE),
  linea(200, 330, 300, 470, STROKE), linea(300, 470, 300, 530, STROKE),
  rect(262, 350, 610, 700))
g("?", 560, arco(280, 520, 160, 200, 20, STROKE), linea(310, 380, 310, 330, STROKE),
  rect(262, 350, 0, 90))
g(":", 300, rect(112, 188, 290, 380), rect(112, 188, 0, 90))
g(";", 300, rect(112, 188, 290, 380), rect(110, 200, -40, 90),
  triangulo((110, 30), (200, 30), (120, -120)))
g("(", 360, arco(400, 350, 380, 120, 240, STROKE))
g(")", 360, arco(-40, 350, 380, -60, 60, STROKE))
g("{", 420, barra_h(200, 220, 660, 70), barra_h(200, 220, -10, 70),
  barra(240, 70, 300, 660), barra(240, 70, -10, 350),
  linea(240, 660, 140, 560, 70), linea(240, -10, 140, 90, 70),
  linea(140, 560, 140, 390, 70), linea(140, 280, 140, 90, 70),
  linea(140, 390, 130, 335, 70), linea(130, 275, 140, 220, 70))
g("}", 420, barra_h(-40, 220, 660, 70), barra_h(-40, 220, -10, 70),
  barra(110, 70, 300, 660), barra(110, 70, -10, 350),
  linea(110, 660, 210, 560, 70), linea(110, -10, 210, 90, 70),
  linea(210, 560, 210, 390, 70), linea(210, 280, 210, 90, 70),
  linea(210, 390, 220, 335, 70), linea(220, 275, 210, 220, 70))
g("-", 400, barra_h(90, 220, 300, 80))
g("_", 600, barra_h(40, 520, -110, 70))
g("–", 620, barra_h(100, 420, 300, 80))
g("—", 900, barra_h(90, 720, 300, 80))
g("&", 700, arco(300, 470, 150, 200, 40, STROKE), arco(280, 170, 170, 100, 20, STROKE),
  arco(430, 230, 130, 200, 300, STROKE), linea(240, 620, 560, 60, STROKE))
g("%", 780, anillo(230, 570, 130, 70), anillo(550, 130, 130, 70),
  linea(600, 700, 180, 0, 80))
g("$", 620, anillo(310, 345, 300, STROKE), barra(276, 70, -60, 760))
g("#", 700, barra(230, 70, 0, 700), barra(410, 70, 0, 700),
  barra_h(120, 460, 240, 70), barra_h(120, 460, 430, 70))
g("@", 800, anillo(400, 330, 330, STROKE), circulo(400, 330, 220 - STROKE, 8),
  barra(560, STROKE, 210, 450), barra_h(560, 190, 210, STROKE))
g("*", 500, linea(250, 700, 250, 420, 80), linea(130, 660, 370, 460, 80),
  linea(370, 660, 130, 460, 80))
g("+", 620, barra(272, 76, 130, 510), barra_h(90, 440, 282, 76))
g("=", 620, barra_h(90, 440, 200, 80), barra_h(90, 440, 370, 80))
g("/", 500, linea(390, 700, 110, -40, 90))
g("\\", 500, linea(110, 700, 390, -40, 90))
g("|", 300, barra(112, 76, -60, 700))
g("~", 620, linea(110, 300, 240, 390, 80), linea(240, 390, 380, 250, 80),
  linea(380, 250, 510, 340, 80))
g("^", 560, triangulo((280, 700), (140, 460), (420, 460)))
g("<", 560, linea(400, 500, 150, 300, STROKE), linea(150, 300, 400, 100, STROKE))
g(">", 560, linea(160, 500, 410, 300, STROKE), linea(410, 300, 160, 100, STROKE))
g("[", 380, barra(150, 76, -40, 700), barra_h(150, 200, 624, 76), barra_h(150, 200, -40, 76))
g("]", 380, barra(150, 76, -40, 700), barra_h(30, 200, 624, 76), barra_h(30, 200, -40, 76))
g("'", 260, barra(93, 74, 520, 700))


# ------------------------------------------------------- fuente de demostración
def construir():
    """Arma los glifos en el formato que espera fontiador_builder."""
    faltan = [c for c in app.TEMPLATE_CHARS if c not in G]
    if faltan:
        raise SystemExit("Faltan glifos: %r" % faltan)

    # Acentos: base + marca, como hace la app al componer.
    marcas = {
        "Á": ("A", "´", 300), "É": ("E", "´", 300), "Í": ("I", "´", 108),
        "Ó": ("O", "´", 300), "Ú": ("U", "´", 300),
        "á": ("a", "´", 250), "é": ("e", "´", 250), "í": ("ı", "´", 90),
        "ó": ("o", "´", 260), "ú": ("u", "´", 250),
        "Ñ": ("N", "~", 300), "ñ": ("n", "~", 250),
    }
    # Marca de tilde, más alta y compacta para usarla como diacrítico.
    tilde = [linea(120, 780, 230, 860, 80), linea(230, 860, 340, 760, 80),
             linea(340, 760, 450, 840, 80)]

    glifos = []
    for ch in app.TEMPLATE_CHARS:
        ancho, contornos = G[ch]
        glifos.append({"char": ch, "advance": ancho, "contours": contornos})

    for ch, (base, marca, dx) in marcas.items():
        ancho, contornos = G[base]
        if marca == "´":
            extra = G["´"][1]
        else:
            extra = tilde
        subidos = []
        for c in extra:
            nuevo = []
            for cmd in c:
                if cmd[0] == "Z":
                    nuevo.append(["Z"])
                else:
                    pts = list(cmd[1:])
                    nuevo.append([cmd[0]] + [pts[i] + (dx if i % 2 == 0 else 250) for i in range(len(pts))])
            subidos.append(nuevo)
        glifos.append({"char": ch, "advance": ancho, "contours": contornos + subidos})

    return glifos


def main():
    glifos = construir()
    destino = os.path.join(RAIZ, "templates")
    os.makedirs(destino, exist_ok=True)
    salida = os.path.join(destino, "FontiadorDemo-Regular.otf")

    metricas = {
        "upm": 1000, "ascender": ASC, "descender": -250,
        "cap_height": CAP, "x_height": XH,
        "baseline_px": 0.0, "scale": 1.0,
        "origin_x_px": 0.0, "default_advance": 560,
    }
    build_font(glifos, salida, family="Fontiador Demo", style="Regular",
               metrics=metricas, kerning=[], adjust={})
    print("glifos dibujados: %d" % len(glifos))
    print("escrito: %s (%d bytes)" % (salida, os.path.getsize(salida)))


if __name__ == "__main__":
    main()
