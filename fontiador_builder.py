"""Construye una fuente OpenType (.otf) a partir de contornos exportados desde Affinity.

Formato de entrada (un diccionario por glifo):
{
  "char": "A",                  # carácter Unicode de un solo símbolo
  "advance": 600,               # ancho de avance en unidades de fuente (opcional)
  "contours": [                 # lista de contornos
     [["M", x, y], ["L", x, y], ["C", x1, y1, x2, y2, x, y], ["Z"]],
     ...
  ]
}

Las coordenadas son las del documento de Affinity en píxeles. Se transforman a unidades de
fuente usando la configuración "metrics" (línea base, escala, origen de la celda).
"""

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

DEFAULT_METRICS = {
    "upm": 1000,
    "ascender": 750,
    "descender": -250,
    "cap_height": 700,
    "x_height": 500,
    "baseline_px": 800.0,    # coordenada y (en Affinity) de la línea base dentro de la celda.
                             # El template tiene celdas de 1000px con baseline a 800 desde el top.
    "scale": 1.0,            # unidades de fuente por píxel de Affinity
    "origin_x_px": 0.0,      # x de origen de la celda en Affinity (se resta a cada punto)
    "default_advance": 500,  # avance por defecto si el glifo no lo indica
}


from shapely.geometry import LineString, Polygon, MultiPolygon, LinearRing
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

CURVE_STEPS = 12


def _flatten(cmds):
    """Convierte comandos M/L/C/Z en una lista de anillos de puntos (x, y) en coordenadas de Affinity."""
    rings, current, pos = [], [], None
    for cmd in cmds:
        op = cmd[0]
        if op == "M":
            if current:
                rings.append((current, False))
            pos = (cmd[1], cmd[2])
            current = [pos]
        elif op == "L":
            pos = (cmd[1], cmd[2])
            current.append(pos)
        elif op == "C":
            p0 = pos
            p1, p2, p3 = (cmd[1], cmd[2]), (cmd[3], cmd[4]), (cmd[5], cmd[6])
            for i in range(1, CURVE_STEPS + 1):
                t = i / CURVE_STEPS
                mt = 1 - t
                x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
                y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
                current.append((x, y))
            pos = p3
        elif op == "Z":
            if current:
                rings.append((current, True))
            current = []
            pos = None
    if current:
        rings.append((current, False))
    return rings


def _contour_items(g):
    """Normaliza los contornos de un glifo. Admite el formato antiguo (lista de comandos) y el nuevo."""
    items = []
    for c in g.get("contours", []):
        if isinstance(c, dict):
            items.append(c)
        else:
            closed = any(cmd[0] == "Z" for cmd in c)
            items.append({"cmds": c, "closed": closed, "fill": True, "stroke": 0})
    return items


def _glyph_geometry(items):
    """Devuelve la geometría final del glifo (relleno + trazos expandidos) en coordenadas de Affinity."""
    parts = []
    for item in items:
        rings = _flatten(item["cmds"])
        if item.get("fill", True):
            for pts, closed in rings:
                if len(pts) >= 3:
                    poly = Polygon(pts).buffer(0)
                    if not poly.is_empty:
                        parts.append(poly)
        width = float(item.get("stroke", 0) or 0)
        if width > 0:
            for pts, closed in rings:
                if len(pts) < 2:
                    continue
                if closed or item.get("closed") and len(pts) >= 3:
                    line = LinearRing(pts)
                    if line.is_ring:
                        parts.append(LineString(pts + [pts[0]]).buffer(width / 2, cap_style="round", join_style="round"))
                else:
                    parts.append(LineString(pts).buffer(width / 2, cap_style="round", join_style="round"))
    if not parts:
        return None
    return unary_union(parts)


def _geometry_to_cmds(geom):
    """Convierte una geometría de shapely en comandos M/L/Z (exterior antihorario, agujeros horario)."""
    polys = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    cmds = []
    for poly in polys:
        poly = orient(poly, sign=1.0)
        for ring in [poly.exterior] + list(poly.interiors):
            coords = list(ring.coords)[:-1]
            if len(coords) < 3:
                continue
            cmds.append(["M", coords[0][0], coords[0][1]])
            for x, y in coords[1:]:
                cmds.append(["L", x, y])
            cmds.append(["Z"])
    return cmds


def _glyph_name(char):
    return "uni%04X" % ord(char)


def _es_comando(x):
    """¿x es un comando M/L/C/Q/Z?"""
    return (isinstance(x, (list, tuple)) and len(x) >= 1
            and isinstance(x[0], str) and x[0] in ("M", "L", "C", "Q", "Z"))


def _anillos_de_comandos(c):
    """Devuelve la lista de anillos de un contorno, o None si no son comandos.

    Admite las dos formas en que puede venir un contorno:

    * una lista de comandos: ``[["M",..], ["L",..], ["Z"]]``
    * una lista de anillos: ``[[["M",..], ["Z"]], [["M",..], ["Z"]]]``, que es el
      caso de las letras con contrapunzón (la O) o la i con su punto.
    """
    if not isinstance(c, (list, tuple)) or not c:
        return None
    if all(_es_comando(x) for x in c):
        return [list(c)]
    if all(isinstance(x, (list, tuple)) and x and all(_es_comando(y) for y in x) for x in c):
        return [list(x) for x in c]
    return None


def _glyph_cmds(g):
    """Comandos M/L/C/Z del glifo, sin perder las curvas si ya venían como tales.

    Hay tres entradas posibles:

    * ``outline_cmds``: lo que traza el importador de renders, ya con los huecos
      orientados; se usa tal cual.
    * ``contours`` con comandos (lo que exporta un programa de diseño): se usan
      directamente, así las curvas originales llegan intactas a la fuente. Antes
      estos casos se aplanaban a segmentos, con lo que se perdían los círculos y
      los glifos con contrapunzón podían quedar vacíos.
    * ``contours`` con listas de puntos: se arma la geometría con shapely (relleno
      y trazo, unión y huecos) y recién ahí se convierte a comandos.
    """
    if g.get("outline_cmds"):
        return g["outline_cmds"]

    items = _contour_items(g)
    crudos = g.get("contours") or []
    por_contorno = [_anillos_de_comandos(c) for c in crudos]
    if crudos and all(a is not None for a in por_contorno):
        return [cmd for anillos in por_contorno for anillo in anillos for cmd in anillo]

    geom = _glyph_geometry(items)
    return _geometry_to_cmds(geom) if geom is not None else []


def _draw_contours(pen, contours, transform):
    """Dibuja los contornos en el pen aplicando la transformación a cada punto."""
    tpen = TransformPen(pen, transform)
    for contour in contours:
        started = False
        for cmd in contour:
            op = cmd[0]
            if op == "M":
                if started:
                    tpen.endPath()
                tpen.moveTo(tuple(cmd[1:3]))
                started = True
            elif op == "L":
                tpen.lineTo(tuple(cmd[1:3]))
            elif op == "C":
                tpen.curveTo(tuple(cmd[1:3]), tuple(cmd[3:5]), tuple(cmd[5:7]))
            elif op == "Q":
                tpen.qCurveTo(tuple(cmd[1:3]), tuple(cmd[3:5]))
            elif op == "Z":
                tpen.closePath()
                started = False
        if started:
            tpen.endPath()


def _rotate_affine(t, deg, cx, cy):
    """Compone una rotación (en grados, alrededor de (cx, cy)) después de la transformación t."""
    import math
    a, bb, c, d, e, f = t
    th = math.radians(deg)
    cs, sn = math.cos(th), math.sin(th)
    k11, k12, k13 = cs, -sn, cx - cs * cx + sn * cy
    k21, k22, k23 = sn, cs, cy - sn * cx - cs * cy
    return (k11 * a + k12 * bb, k21 * a + k22 * bb,
            k11 * c + k12 * d, k21 * c + k22 * d,
            k11 * e + k12 * f + k13, k21 * e + k22 * f + k23)


def _affine_for_glyph(m, g, adj=None):
    """Transforma coordenadas de Affinity (y hacia abajo) a unidades de fuente (y hacia arriba).

    Si el glifo trae "cell" ({"x": .., "y": ..}, esquina superior izquierda de su celda),
    las coordenadas son relativas a esa celda. "baseline_px" es la línea base dentro de la celda.
    """
    s = m["scale"]
    adj = adj or {}
    sx = float(adj.get("sx", 1.0))
    sy = float(adj.get("sy", 1.0))
    dy = float(adj.get("dy", 0.0))
    cell = g.get("cell")
    if cell:
        ox, oy = cell["x"], cell["y"]
    else:
        ox, oy = m["origin_x_px"], 0.0
    # x' = (x - ox) * s * sx ; y' = (baseline - (y - oy)) * s * sy + dy  (escala vertical desde la línea base)
    return (s * sx, 0, 0, -s * sy, -ox * s * sx, (m["baseline_px"] + oy) * s * sy + dy)


def _kern_feature(kerning, glyph_names):
    """Genera el código de feature 'kern' a partir de pares {left, right, value}.

    Solo se incluyen pares cuyos glifos existen en la fuente.
    """
    lines = []
    for pair in kerning or []:
        left = _glyph_name(pair["left"])
        right = _glyph_name(pair["right"])
        if left in glyph_names and right in glyph_names and int(pair["value"]) != 0:
            lines.append("    pos %s %s %d;" % (left, right, int(pair["value"])))
    if not lines:
        return None
    return "languagesystem DFLT dflt;\nfeature kern {\n" + "\n".join(lines) + "\n} kern;\n"


def build_font(glyphs, output_path, family="MiFuente", style="Regular", metrics=None, kerning=None, adjust=None):
    m = dict(DEFAULT_METRICS)
    if metrics:
        m.update(metrics)

    glyph_order = [".notdef", "space"]
    cmap = {32: "space"}
    charstrings = {}
    metrics_table = {}

    # .notdef: un rectángulo vacío
    notdef_pen = T2CharStringPen(m["default_advance"], None)
    notdef_pen.moveTo((50, 0)); notdef_pen.lineTo((50, m["cap_height"]))
    notdef_pen.lineTo((m["default_advance"] - 50, m["cap_height"]))
    notdef_pen.lineTo((m["default_advance"] - 50, 0)); notdef_pen.closePath()
    charstrings[".notdef"] = notdef_pen.getCharString()
    metrics_table[".notdef"] = (m["default_advance"], 0)

    space_adv = m["default_advance"] // 2
    charstrings["space"] = T2CharStringPen(space_adv, None).getCharString()
    metrics_table["space"] = (space_adv, 0)

    for g in glyphs:
        char = g["char"]
        if len(char) != 1:
            raise ValueError("El carácter debe ser de un solo símbolo: %r" % char)
        name = _glyph_name(char)
        adj = (adjust or {}).get(char, {})
        if adj.get("advance"):
            advance = int(adj["advance"])
        else:
            advance = int(round(g.get("advance", m["default_advance"]) * float(adj.get("sx", 1.0))))
        pen = T2CharStringPen(advance, None)
        bounds = BoundsPen(None)
        transform = _affine_for_glyph(m, g, adj)
        rot = float(adj.get("rot", 0.0) or 0.0)
        if rot:
            transform = _rotate_affine(transform, rot, advance / 2.0, 400.0)
        cmds = _glyph_cmds(g)
        _draw_contours(pen, [cmds] if cmds else [], transform)
        _draw_contours(bounds, [cmds] if cmds else [], transform)
        if name in glyph_order:
            continue
        glyph_order.append(name)
        cmap[ord(char)] = name
        charstrings[name] = pen.getCharString()
        lsb = int(bounds.bounds[0]) if bounds.bounds else 0
        metrics_table[name] = (advance, lsb)

    fb = FontBuilder(m["upm"], isTTF=False)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)
    fb.setupCFF(family + "-" + style, {}, charstrings, {})
    fb.setupHorizontalMetrics(metrics_table)
    fb.setupHorizontalHeader(ascent=m["ascender"], descent=m["descender"])
    fb.setupNameTable({
        "familyName": family,
        "styleName": style,
        "uniqueFontIdentifier": family + "-" + style + "-fontiador",
        "fullName": family + " " + style,
        "psName": (family + "-" + style).replace(" ", ""),
        "version": "Version 1.000",
    })
    fb.setupOS2(sTypoAscender=m["ascender"], sTypoDescender=m["descender"],
                usWinAscent=m["ascender"], usWinDescent=-m["descender"],
                sCapHeight=m["cap_height"], sxHeight=m["x_height"])
    fb.setupPost()

    fea = _kern_feature(kerning, set(glyph_order))
    if fea:
        addOpenTypeFeaturesFromString(fb.font, fea)

    fb.save(output_path)
    return output_path
