"""Fontiador: genera la fuente a partir de las exportaciones de Affinity, con una interfaz local.

Carpeta de trabajo (AF_FONT):
    inbox/   -> el script "Fontiador: exportar glifos" deja aquí archivos export_*.json
    output/  -> aquí se guarda la fuente generada (.otf)

Uso (desde la carpeta AF_FONT):
    python fontiador_server.py
    python fontiador_server.py --family "Mi Fuente" --style Regular --port 8765

Abre http://127.0.0.1:8765 en el navegador para ver el estado, editar kerning,
elegir conjuntos de caracteres y reconstruir la fuente.
"""

import argparse
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fontiador_builder import build_font, _contour_items, _glyph_geometry, _geometry_to_cmds
import fontiador_paths
import fontiador_import
import numpy as np
import potrace
from PIL import Image, ImageFilter
from shapely.geometry import Polygon

APP_VERSION = "0.2.0"

# Repositorio del proyecto: de acá salen las actualizaciones y los enlaces de descarga.
REPO = "mastopiramato/fontiador"
REPO_URL = "https://github.com/" + REPO
RELEASES_API = "https://api.github.com/repos/%s/releases/latest" % REPO

RENDER_CELL = 1000
RENDER_COLS = 10
RENDER_SPECIAL = ['{', '}', '-', '_', '–', '—', '&', '%', '$', '#', '@', '*', '+', '=', '/', '\\', '|', '~', '^', '<', '>', '[', ']', "'", '°', '«', '»']
# Plantilla v6: 103 caracteres. Los acentuados (Á É Í Ó Ú á é í ó ú Ñ ñ) NO están en
# el template: se componen en el servidor a partir de su base + marca. Los dos últimos
# slots son el palo de la i (ı, sin punto) y el círculo de la i (˙), en ese orden.
TEMPLATE_CHARS = (list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + list("abcdefghijklmnopqrstuvwxyz")
                  + list("0123456789") + ['"', ',', '.', '!', '¡', '¿', '?', ':', ';', '(', ')', '´']
                  + RENDER_SPECIAL + ['ı', '˙'])

# Rutas: en modo portable quedan al lado de la app; en una instalacion de sistema
# van a la carpeta de datos del usuario (ver fontiador_paths.py).
BASE_DIR = fontiador_paths.BASE_DIR
INBOX_DIRS = fontiador_paths.inbox_dirs()
OUTPUT = fontiador_paths.OUTPUT_DIR
PROJECT_FILE = fontiador_paths.PROJECT_FILE

_LOG_HANDLE = None


def _redirigir_salida():
    """Manda stdout/stderr al archivo de log.

    Se hace SIEMPRE que la app esté congelada (ventana sin consola), no solo
    cuando stdout es None: en un .exe sin consola los descriptores existen pero
    no llevan a ningún lado, y por eso un fallo de arranque antes de la primera
    línea de log desaparecía sin dejar rastro.
    """
    global _LOG_HANDLE
    if _LOG_HANDLE is not None:
        return
    try:
        os.makedirs(os.path.dirname(fontiador_paths.LOG_FILE) or ".", exist_ok=True)
        _LOG_HANDLE = open(fontiador_paths.LOG_FILE, "a", encoding="utf-8", buffering=1)
    except Exception:
        _LOG_HANDLE = None
        return
    if getattr(sys, "frozen", False) or sys.stdout is None or sys.stderr is None:
        try:
            sys.stdout = _LOG_HANDLE
            sys.stderr = _LOG_HANDLE
        except Exception:
            pass


_redirigir_salida()

# Si la app se llamaba "Affont", los datos viejos se renombran una sola vez.
try:
    for _c in fontiador_paths.rename_legacy():
        log("Datos migrados desde la etapa Affont: %s" % _c)
except Exception:
    pass

CHARSET_GROUPS = {
    "upper": set("ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÑ"),
    "lower": set("abcdefghijklmnopqrstuvwxyzáéíóúñı"),
    "digits": set("0123456789"),
    "punct": set('"' + ",.!¡¿?:;()´" + "{}-_–—&%$#@*+=/\\|~^<>[]'°«»˙"),
}

JOB = {"active": False, "name": "", "stage": "", "done": 0, "total": 0, "started": 0.0, "ended": 0.0, "info": ""}


def _job_start(name, total, stage):
    with _lock:
        JOB.update(active=True, name=name, stage=stage, done=0, total=total, started=time.time(), ended=0.0, info="")


def _job_step(stage, done=None):
    with _lock:
        JOB["stage"] = stage
        if done is not None:
            JOB["done"] = done


def _job_end(stage="Listo"):
    with _lock:
        JOB.update(active=False, stage=stage, done=JOB.get("total", 0), ended=time.time())


_lock = threading.RLock()
_state = {
    "watch": {"inbox": " · ".join(INBOX_DIRS), "last_scan": "-", "pending": 0, "errors": 0},
    "family": "Mi Fuente",
    "style": "Regular",
    "project": {"metrics": {}, "glyphs": {}, "kerning": [], "kerning_base": [], "kerning_char": {}, "adjust": {}, "accent_adjust": {},
                "charsets": {k: True for k in CHARSET_GROUPS}},
    "last_output": None,
    "log": [],
    "version": 0,
}
_accents_hash = None
_missing_logged = set()


# ---------------------------------------------------------------------------
# Importaciones: guía por programa y plantilla de la rejilla
# ---------------------------------------------------------------------------
# Los textos de la guía viven acá, separados de la interfaz, para poder
# corregirlos sin tocar el HTML.
IMPORT_GUIDE = [
    {
        "id": "affinity",
        "nombre": "Affinity Designer / Photo 2",
        "mecanismo": "Exportación JSON de glifos (mejor calidad) o render PNG",
        "formatos": ["export_*.json", "render_*.png"],
        "pasos": [
            "Descargá la plantilla base con el botón de abajo y abrila en Affinity.",
            "Dibujá cada glifo dentro de su celda, apoyado en la línea base verde (y=800).",
            "Si tenés el script de exportación, ejecutalo desde Documento > Guiones: "
            "genera un export_<fecha>.json con los contornos exactos, sin perder curvas.",
            "Sin script: Archivo > Exportar, formato PNG, 600 ppp, y que el ancho quede en 10000 px "
            "(10 columnas x 1000 px). Guardalo como render_loquesea.png.",
            "Elegí el archivo con el botón de arriba. La app lo traza y reconstruye la fuente sola.",
        ],
        "nota": "El JSON conserva los vectores tal cual los dibujaste. El PNG hay que trazarlo, "
                "así que las curvas se aproximan.",
    },
    {
        "id": "illustrator",
        "nombre": "Adobe Illustrator",
        "mecanismo": "Exportación PNG de la mesa de trabajo",
        "formatos": ["render_*.png", "render_*.svg"],
        "pasos": [
            "Abrí la plantilla base. El documento mide 10000 x 11000 px (10 x 11 celdas de 1000 px).",
            "Dibujá los glifos respetando la cuadrícula y la línea base.",
            "Archivo > Exportar > Exportar como, formato PNG.",
            "En el diálogo poné Resolución: Otro, 600 ppp, y Fondo: Transparente.",
            "Confirmá que el ancho exportado sea 10000 px. Si cambia, la app reescala pero pierde nitidez.",
            "Importá el archivo con el botón de arriba.",
        ],
        "nota": "Illustrator no exporta los contornos en un JSON entendible, así que la vía práctica "
                "es el PNG (o un SVG de la mesa completa).",
    },
    {
        "id": "inkscape",
        "nombre": "Inkscape",
        "mecanismo": "Exportación PNG del documento o SVG por glifos",
        "formatos": ["render_*.png", "*.svg"],
        "pasos": [
            "Abrí la plantilla base (el SVG ya viene con la cuadrícula y las guías).",
            "Dibujá cada glifo sobre la línea base.",
            "Archivo > Exportar: elegí PNG, área de exportación 'Página', y en tamaño poné 10000 px de ancho.",
            "Exportá y elegí el archivo con el botón de arriba.",
        ],
        "nota": "Si preferís vectores, exportá un SVG por glifo y elegilos todos juntos; "
                "igual conviene el JSON de Affinity para no re-trazar.",
    },
    {
        "id": "figma",
        "nombre": "Figma",
        "mecanismo": "Exportación PNG del marco",
        "formatos": ["render_*.png"],
        "pasos": [
            "Importá la plantilla como imagen de fondo y dibujá encima, "
            "o creá un marco de 10000 x 11000 px y armá la cuadrícula.",
            "Seleccioná el marco completo (no un grupo suelto).",
            "En Exportar, agregá un ajuste PNG con escala 2x o 4x: Figma no exporta a ppp directamente.",
            "Exportá y verificá el ancho en píxeles: la app necesita 10000 px para no reescalar.",
            "Elegí el archivo con el botón de arriba.",
        ],
        "nota": "Figma no exporta curvas en un formato que la app lea, así que siempre se traza la imagen.",
    },
    {
        "id": "corel",
        "nombre": "CorelDRAW",
        "mecanismo": "Exportación PNG o SVG",
        "formatos": ["render_*.png", "render_*.svg"],
        "pasos": [
            "Abrí la plantilla y dibujá los glifos sobre la cuadrícula.",
            "Archivo > Exportar, elegí PNG, y en opciones poné 600 ppp y fondo transparente.",
            "Verificá que el ancho sea 10000 px.",
            "Importá el archivo con el botón de arriba.",
        ],
        "nota": "CorelDRAW exporta SVG pero la app lo rasteriza igual; el PNG a 600 ppp da el mismo resultado.",
    },
    {
        "id": "otros",
        "nombre": "Otro programa (Glyphs, FontForge, Photoshop, Krita…)",
        "mecanismo": "Cualquier rejilla de 10 columnas con celdas de 1000 px",
        "formatos": ["render_*.png", "export_*.json"],
        "pasos": [
            "Lo que la app necesita es una imagen con la rejilla del formato de abajo, "
            "con los caracteres en el orden indicado.",
            "Exportá a PNG con celdas de 1000 x 1000 px, línea base a 800 px del borde superior "
            "de cada celda.",
            "Si tu programa puede volcar contornos como M/L/C/Z en JSON, usá el formato export_*.json: "
            "se importa sin trazar.",
            "Elegí el archivo con el botón de arriba.",
        ],
        "nota": "El orden de los caracteres es estricto: si cambia, los glifos se asignan al carácter equivocado.",
    },
]


def build_template_svg():
    """Plantilla de la rejilla en SVG: se puede dibujar encima en cualquier programa.

    Dibuja las celdas, las líneas guía verticales (ascendente, altura de mayúscula,
    altura de x, línea base y descendente) y las etiquetas de fila y columna.
    """
    cols = RENDER_COLS
    filas = (len(TEMPLATE_CHARS) + cols - 1) // cols
    ancho = cols * RENDER_CELL
    alto = filas * RENDER_CELL
    base = float(_state["project"]["metrics"].get("baseline_px", 800))
    guias = [("Ascendente", base - 750), ("Altura de mayúscula", base - 700),
             ("Altura de x", base - 500), ("Línea base", base),
             ("Descendente", base + 200)]
    p = []
    p.append('<?xml version="1.0" encoding="UTF-8"?>')
    p.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
             % (ancho, alto, ancho, alto))
    p.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    p.append('<g id="celdas" fill="none" stroke="#d8d8d8" stroke-width="2">')
    for r in range(filas):
        for c in range(cols):
            p.append('<rect x="%d" y="%d" width="%d" height="%d"/>'
                     % (c * RENDER_CELL, r * RENDER_CELL, RENDER_CELL, RENDER_CELL))
    p.append('</g>')
    p.append('<g id="guias">')
    for nombre, y in guias:
        color = "#22aa55" if nombre == "Línea base" else "#c8a24a"
        grosor = 3 if nombre == "Línea base" else 1.5
        p.append('<line x1="0" y1="%g" x2="%d" y2="%g" stroke="%s" stroke-width="%g"/>'
                 % (y, ancho, y, color, grosor))
        p.append('<text x="6" y="%g" font-family="sans-serif" font-size="34" fill="%s">%s</text>'
                 % (y - 8, color, nombre))
    p.append('</g>')
    p.append('<g id="etiquetas" font-family="sans-serif" font-size="90" fill="#c9c9c9" '
             'text-anchor="middle">')
    for r in range(filas):
        for c in range(cols):
            i = r * cols + c
            if i >= len(TEMPLATE_CHARS):
                break
            ch = TEMPLATE_CHARS[i]
            esc = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}.get(ch, ch)
            p.append('<text x="%d" y="%d">%s</text>'
                     % (c * RENDER_CELL + RENDER_CELL // 2, r * RENDER_CELL + 130, esc))
    p.append('</g>')
    p.append('<g id="columna" font-family="sans-serif" font-size="70" fill="#efefef">')
    for c in range(cols):
        p.append('<rect x="%d" y="0" width="120" height="120" fill="#333"/>' % (c * RENDER_CELL))
        p.append('<text x="%d" y="86" text-anchor="middle" fill="#fff">%d</text>'
                 % (c * RENDER_CELL + 60, c + 1))
    p.append('</g>')
    p.append('<g id="fila" font-family="sans-serif" font-size="70">')
    for r in range(filas):
        p.append('<rect x="%d" y="%d" width="120" height="120" fill="#333"/>'
                 % (ancho - 120, r * RENDER_CELL))
        p.append('<text x="%d" y="%d" text-anchor="middle" fill="#fff">%d</text>'
                 % (ancho - 60, r * RENDER_CELL + 86, r + 1))
    p.append('</g>')
    p.append('<g id="info" font-family="sans-serif" font-size="60" fill="#666">')
    p.append('<text x="140" y="%d">Fontiador — plantilla base · %d celdas de %d x %d px · '
             'línea base a %g px · exportar a %d px de ancho</text>'
             % (alto - 40, len(TEMPLATE_CHARS), RENDER_CELL, RENDER_CELL, base, ancho))
    p.append('</g>')
    p.append('</svg>')
    return "\n".join(p)


def build_template_png():
    """Misma plantilla, rasterizada a 100 px por celda para usarla como guía rápida."""
    import io
    from PIL import ImageDraw
    escala = 0.1
    cols = RENDER_COLS
    filas = (len(TEMPLATE_CHARS) + cols - 1) // cols
    celda = int(RENDER_CELL * escala)
    img = Image.new("RGB", (cols * celda, filas * celda), "white")
    d = ImageDraw.Draw(img)
    base = float(_state["project"]["metrics"].get("baseline_px", 800)) * escala
    for r in range(filas):
        for c in range(cols):
            x0, y0 = c * celda, r * celda
            d.rectangle([x0, y0, x0 + celda - 1, y0 + celda - 1], outline="#d8d8d8")
            i = r * cols + c
            if i < len(TEMPLATE_CHARS):
                d.text((x0 + 6, y0 + 6), TEMPLATE_CHARS[i], fill="#c9c9c9")
                for nombre, y in (("Ascendente", base - 75), ("Altura de x", base - 50),
                                  ("Línea base", base), ("Descendente", base + 20)):
                    color = "#22aa55" if nombre == "Línea base" else "#c8a24a"
                    yy = y0 + y
                    if 0 <= yy < img.height:
                        d.line([x0, yy, x0 + celda, yy], fill=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _version_tuple(texto):
    """Convierte 'v0.2.0' o '0.2.0-beta' en una tupla comparable (0, 2, 0)."""
    if not texto:
        return (0,)
    limpio = str(texto).strip().lstrip("vV").split("-")[0].split("+")[0]
    partes = []
    for trozo in limpio.split("."):
        digitos = "".join(c for c in trozo if c.isdigit())
        partes.append(int(digitos) if digitos else 0)
    return tuple(partes) or (0,)


def _version_menor(a, b):
    """¿Es la versión a anterior a la b?"""
    ta, tb = _version_tuple(a), _version_tuple(b)
    largo = max(len(ta), len(tb))
    ta = ta + (0,) * (largo - len(ta))
    tb = tb + (0,) * (largo - len(tb))
    return ta < tb


def check_update():
    """Consulta la última release publicada en el repositorio.

    Devuelve siempre un diccionario: si no hay internet o el repositorio todavía
    no tiene releases, se informa como error y la app sigue funcionando igual.
    """
    import urllib.error
    import urllib.request

    resultado = {
        "actual": APP_VERSION,
        "repo": REPO,
        "repositorio": REPO_URL,
        "descarga": REPO_URL + "/releases/latest",
        "disponible": False,
        "nueva": None,
        "notas": None,
        "publicada": None,
        "error": None,
    }
    req = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "Fontiador/%s" % APP_VERSION},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            datos = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # El repositorio existe pero todavía no hay ninguna release publicada.
            resultado["error"] = ("Todavía no hay ninguna versión publicada en el "
                                  "repositorio.")
        else:
            resultado["error"] = "El repositorio respondió %s." % e.code
        return resultado
    except Exception as e:
        resultado["error"] = ("No se pudo consultar el repositorio (%s). "
                              "¿Hay conexión a internet?" % type(e).__name__)
        return resultado

    etiqueta = datos.get("tag_name") or datos.get("name") or ""
    resultado["nueva"] = etiqueta.lstrip("vV") or None
    resultado["notas"] = (datos.get("body") or "").strip()[:4000] or None
    resultado["publicada"] = (datos.get("published_at") or "")[:10] or None
    if datos.get("html_url"):
        resultado["descarga"] = datos["html_url"]

    # Enlaces directos a los instaladores, si la release los trae adjuntos.
    archivos = []
    for a in datos.get("assets") or []:
        nombre = a.get("name") or ""
        archivos.append({"nombre": nombre, "url": a.get("browser_download_url"),
                         "bytes": a.get("size")})
    resultado["archivos"] = archivos
    if etiqueta and _version_menor(APP_VERSION, etiqueta):
        resultado["disponible"] = True
    return resultado


def load_tutorial():
    """Lee el texto de los tutoriales desde tutorial.json.

    Los textos viven en ese archivo, y no en el código, justamente para poder
    corregirlos sin tocar nada más. Si falta o está mal escrito, la app arranca
    igual: simplemente no muestra tutoriales.
    """
    for ruta in (os.path.join(BASE_DIR, "tutorial.json"),
                 os.path.join(fontiador_paths.TEMPLATES_DIR, "tutorial.json")):
        try:
            with open(ruta, "r", encoding="utf-8-sig") as f:
                datos = json.load(f)
            if isinstance(datos, dict) and datos:
                return datos
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    try:
        print("[fontiador] " + msg, flush=True)
    except Exception:
        pass
    with _lock:
        _state["log"].append(line)
        del _state["log"][:-50]


def bump_version():
    _state["version"] = (_state.get("version", 0) + 1) % 1_000_000


def load_project():
    if os.path.exists(PROJECT_FILE):
        try:
            # utf-8-sig y no utf-8: si el archivo se guardó desde el Bloc de notas
            # de Windows lleva BOM al principio, y leerlo como utf-8 a secas hacía
            # que el proyecto se diera por dañado y se empezara de cero en silencio.
            with open(PROJECT_FILE, "r", encoding="utf-8-sig") as f:
                saved = json.load(f)
            if not isinstance(saved, dict):
                raise ValueError("el contenido no es un objeto JSON")
            _state["project"].update(saved)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            # No se descarta el archivo: se aparta con otro nombre para poder
            # recuperarlo, y se avisa con la ruta exacta.
            respaldo = PROJECT_FILE + ".dañado"
            try:
                shutil.copy2(PROJECT_FILE, respaldo)
                detalle = " Se guardó una copia en %s." % os.path.basename(respaldo)
            except OSError:
                detalle = ""
            log("Aviso: %s no se pudo leer (%s). Se inició un proyecto vacío.%s"
                % (os.path.basename(PROJECT_FILE), e, detalle))
            return
        for k in CHARSET_GROUPS:
            _state["project"]["charsets"].setdefault(k, True)
        _state["project"].setdefault("kerning_base", [])
        _state["project"].setdefault("kerning_char", {})
        _state["project"].setdefault("accent_adjust", {})
        _state["project"].setdefault("trace_overrides", {})
        if isinstance(_state["project"].get("kerning"), list):
            _state["project"]["kerning"] = [p for p in _state["project"]["kerning"] if p.get("source") == "manual" or "source" not in p]


def save_project():
    tmp_file = PROJECT_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(_state["project"], f, ensure_ascii=False, indent=1)
    os.replace(tmp_file, PROJECT_FILE)


def effective_kerning():
    project = _state["project"]
    kerning_char = project.get("kerning_char", {})
    kerning_manual = {(p["left"], p["right"]): p["value"] for p in project.get("kerning", [])}

    chars = [c for c in project.get("glyphs", {}).keys() if c in allowed_chars()]
    if not chars:
        return []

    l_active = {c for c in chars if kerning_char.get(c, {}).get("r", 0) != 0}
    r_active = {c for c in chars if kerning_char.get(c, {}).get("l", 0) != 0}

    for (L, R) in kerning_manual:
        if L in chars and R in chars:
            l_active.add(L)
            r_active.add(R)

    relevant_pairs = set()
    for L in l_active:
        for R in chars:
            relevant_pairs.add((L, R))
    for R in r_active:
        for L in chars:
            relevant_pairs.add((L, R))

    merged = []
    for L, R in relevant_pairs:
        base_r = kerning_char.get(L, {}).get("r", 0)
        base_l = kerning_char.get(R, {}).get("l", 0)
        base_total = base_r + base_l
        manual_offset = kerning_manual.get((L, R), 0)
        final_value = base_total + manual_offset
        if final_value != 0:
            merged.append({"left": L, "right": R, "value": final_value})

    return merged


def allowed_chars():
    charsets = _state["project"]["charsets"]
    chars = set()
    for group, chars_in_group in CHARSET_GROUPS.items():
        if charsets.get(group, True):
            chars |= chars_in_group
    return chars


def import_file(path):
    # utf-8-sig: las exportaciones hechas en Windows suelen traer BOM.
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    project = _state["project"]
    project["metrics"].update(data.get("metrics", {}))
    for g in data.get("glyphs", []):
        project["glyphs"][g["char"]] = g
    bump_version()
    return len(data.get("glyphs", []))


def rebuild(family=None, style=None):
    with _lock:
        compose_accents()
        family = family or _state["family"]
        style = style or _state["style"]
        chars = allowed_chars()
        glyphs = [g for c, g in _state["project"]["glyphs"].items() if c in chars]
                # Merge defensivo: si metrics está vacío o le faltan claves, completamos con
        # los valores por defecto del template (celdas 1000px, baseline a 800, upm 1000).
        metrics = {
            "upm": 1000,
            "ascender": 750,
            "descender": -200,
            "cap_height": 700,
            "x_height": 500,
            "baseline_px": 800.0,
            "scale": 1.0,
            "default_advance": 500,
        }
        metrics.update(_state["project"]["metrics"])
        kerning = effective_kerning()
        adjust = {k: dict(v) for k, v in _state["project"]["adjust"].items()}
    if not glyphs:
        log("No hay glifos que construir con los conjuntos seleccionados.")
        return None
    os.makedirs(OUTPUT, exist_ok=True)
    out = os.path.join(OUTPUT, "%s-%s.otf" % (family.replace(" ", ""), style))
    build_font(glyphs, out, family=family, style=style, metrics=metrics, kerning=kerning, adjust=adjust)
    size = os.path.getsize(out) if os.path.exists(out) else 0
    with _lock:
        _state["family"], _state["style"], _state["last_output"] = family, style, out
    log("Fuente generada: %s (%d glifos, %d pares de kerning, %.1f KB)"
        % (os.path.basename(out), len(glyphs), len(kerning), size / 1024.0))
    return out


def _flatten_potrace(curve, steps=16):
    pts = [(curve.start_point.x, curve.start_point.y)]
    pos = pts[0]
    for seg in curve.segments:
        end = (seg.end_point.x, seg.end_point.y)
        if seg.is_corner:
            pts.append((seg.c.x, seg.c.y))
            pts.append(end)
        else:
            c1 = (seg.c1.x, seg.c1.y)
            c2 = (seg.c2.x, seg.c2.y)
            for i in range(1, steps + 1):
                t = i / steps
                mt = 1 - t
                x = mt**3 * pos[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t**3 * end[0]
                y = mt**3 * pos[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t**3 * end[1]
                pts.append((x, y))
        pos = end
    return pts


TRACE_TURDSIZE = 20
TRACE_BLUR = 0.5
TRACE_ALPHAMAX = 0.4
TRACE_OPTTOLERANCE = 0.1
DEFAULT_THRESHOLD = 0.5


def _trace_settings(char=None):
    """Devuelve (turdsize, blur, alphamax, threshold, opttolerance) para un carácter.

    Si `char` está en project["trace_overrides"], sus valores pisan los globales.
    """
    p = _state["project"]
    turdsize = int(p.get("trace_turdsize", TRACE_TURDSIZE))
    blur = float(p.get("trace_blur", TRACE_BLUR))
    alphamax = float(p.get("trace_alphamax", TRACE_ALPHAMAX))
    threshold = float(p.get("trace_threshold", DEFAULT_THRESHOLD))
    opttol = float(p.get("trace_opttolerance", TRACE_OPTTOLERANCE))
    if char:
        ov = (p.get("trace_overrides") or {}).get(char) or {}
        if "turdsize" in ov: turdsize = int(ov["turdsize"])
        if "blur" in ov: blur = float(ov["blur"])
        if "alphamax" in ov: alphamax = float(ov["alphamax"])
        if "threshold" in ov: threshold = float(ov["threshold"])
        if "opttolerance" in ov: opttol = float(ov["opttolerance"])
    return turdsize, blur, alphamax, threshold, opttol


def trace_mask(mask, turdsize=None, alphamax=None, opttolerance=None):
    if not mask.any():
        return None
    if turdsize is None:
        turdsize = TRACE_TURDSIZE
    if alphamax is None:
        alphamax = TRACE_ALPHAMAX
    if opttolerance is None:
        opttolerance = TRACE_OPTTOLERANCE
    geom = None
    for curve in potrace.Bitmap(~mask).trace(
            turdsize=turdsize, alphamax=alphamax,
            opticurve=True, opttolerance=opttolerance):
        pts = _flatten_potrace(curve)
        if len(pts) < 3:
            continue
        poly = Polygon(pts).buffer(0)
        geom = poly if geom is None else geom.symmetric_difference(poly)
    return geom


def import_render(path, threshold=None):
    Image.MAX_IMAGE_PIXELS = None
    img = Image.open(path)
    w, h = img.size
    transparent = False
    if "A" in img.getbands():
        transparent = img.getchannel("A").getextrema()[0] < 250
    target_w = RENDER_COLS * RENDER_CELL
    min_rows = (len(TEMPLATE_CHARS) + RENDER_COLS - 1) // RENDER_COLS
    if w != target_w:
        ratio = h / float(w)
        target_h = int(round(target_w * ratio))
        if target_h < min_rows * RENDER_CELL:
            raise RenderSizeError(
                "El render mide %dx%d px: se necesitan al menos %d filas (10x%d)." %
                (w, h, min_rows, min_rows))
        log("Render a %dx%d px: se reescala a %dx%d (600 ppp) para la rejilla de celdas." % (w, h, target_w, target_h))
        img = img.convert("RGBA").resize((target_w, target_h), Image.LANCZOS)
        w, h = img.size
    else:
        rows = h // RENDER_CELL
        if rows < min_rows:
            raise RenderSizeError(
                "El render mide %dx%d px: se necesitan al menos %d filas (10x%d)." %
                (w, h, min_rows, min_rows))

    forced_threshold = float(threshold) if threshold is not None else None

    imported_glyphs = {}
    empty, failed, empty_with_pos = [], [], []
    _job_start(os.path.basename(path), len(TEMPLATE_CHARS), "Abriendo render (%dx%d px, %s)" % (
        w, h, "con transparencia" if transparent else "opaco"))

    for i, ch in enumerate(TEMPLATE_CHARS):
        _job_step("Trazando celda '%s' (%d/%d)" % (ch, i + 1, len(TEMPLATE_CHARS)), done=i)
        r, c = divmod(i, RENDER_COLS)
        x0, y0 = c * RENDER_CELL, r * RENDER_CELL
        if x0 + RENDER_CELL > w or y0 + RENDER_CELL > h:
            failed.append(ch + "(fuera)")
            continue
        try:
            cell_img = img.crop((x0, y0, x0 + RENDER_CELL, y0 + RENDER_CELL)).convert("RGBA")
            arr = np.asarray(cell_img, dtype=np.float32) / 255.0
            if transparent:
                coverage = arr[:, :, 3]
            else:
                coverage = 1.0 - (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2])
            t_turdsize, t_blur, t_alphamax, t_level, t_opttol = _trace_settings(char=ch)
            if forced_threshold is not None:
                t_level = forced_threshold
            if t_blur > 0:
                cov_img = Image.fromarray((np.clip(coverage, 0, 1) * 255).astype(np.uint8))
                smooth = np.asarray(cov_img.filter(ImageFilter.GaussianBlur(t_blur)), dtype=np.float32) / 255.0
            else:
                smooth = coverage
            cov_max = float(np.max(smooth)) if smooth.size else 0.0
            cov_mean = float(np.mean(smooth)) if smooth.size else 0.0
            geom = trace_mask(smooth >= t_level, turdsize=t_turdsize,
                              alphamax=t_alphamax, opttolerance=t_opttol)
            if geom is None or geom.is_empty:
                empty.append(ch)
                empty_with_pos.append("%s(fila %d, col %d, max %.2f, mean %.3f)" % (ch, r + 1, c + 1, cov_max, cov_mean))
                continue
            cmds = []
            for cmd in _geometry_to_cmds(geom):
                cmds.append(["Z"] if cmd[0] == "Z" else [cmd[0], cmd[1] + x0, cmd[2] + y0])
            xs = [p[1] - x0 for p in cmds if p[0] != "Z"]
            advance = max(300, round(max(xs) + 100)) if xs else 500
            imported_glyphs[ch] = {"char": ch, "cell": {"x": x0, "y": y0}, "advance": advance,
                                   "outline_cmds": cmds, "source": "render"}
        except Exception as e:
            failed.append("%s(%s)" % (ch, e))

    _job_step("Guardando glifos", done=len(TEMPLATE_CHARS))
    with _lock:
        glyphs = _state["project"]["glyphs"]
        for ch in empty:
            glyphs.pop(ch, None)
        glyphs.update(imported_glyphs)
        _missing_logged.clear()
        bump_version()

    _job_end("Render importado")
    log("Render %s: %dx%d (%d celdas, %d filas), %s · importados %d · vacíos %d · fallidos %d" % (
        os.path.basename(path), w, h, len(TEMPLATE_CHARS), h // RENDER_CELL,
        "con transparencia" if transparent else "opaco",
        len(imported_glyphs), len(empty), len(failed)))
    if empty_with_pos:
        muestra = empty_with_pos[:20]
        log("Celdas vacías: " + ", ".join(muestra) +
            (" (+%d más)" % (len(empty_with_pos) - len(muestra)) if len(empty_with_pos) > len(muestra) else ""))
    if failed:
        log("Celdas fallidas: " + " ".join(failed[:40]))
    return len(imported_glyphs), empty, failed


def _debug_cell(char):
    """Vuelca a output/debug/ los artefactos del trazado de una celda.

    Genera:
      <char>_cell.png    -> el crop original
      <char>_mask.png    -> la máscara después de blur+threshold
      <char>_trace.svg   -> el polígono trazado (si hay)
    Devuelve un dict con las stats.
    """
    Image.MAX_IMAGE_PIXELS = None
    if char not in TEMPLATE_CHARS:
        raise ValueError("carácter no está en el template")
    idx = TEMPLATE_CHARS.index(char)
    r, c = divmod(idx, RENDER_COLS)
    x0, y0 = c * RENDER_CELL, r * RENDER_CELL

    last = _find_last_processed_render()
    if not last:
        raise ValueError("no hay render procesado para diagnosticar")
    img = Image.open(last)
    if img.size[0] != RENDER_COLS * RENDER_CELL:
        target_w = RENDER_COLS * RENDER_CELL
        ratio = img.size[1] / float(img.size[0])
        target_h = int(round(target_w * ratio))
        img = img.convert("RGBA").resize((target_w, target_h), Image.LANCZOS)

    cell_img = img.crop((x0, y0, x0 + RENDER_CELL, y0 + RENDER_CELL)).convert("RGBA")
    arr = np.asarray(cell_img, dtype=np.float32) / 255.0
    has_alpha = "A" in img.getbands() and img.getchannel("A").getextrema()[0] < 250
    if has_alpha:
        coverage = arr[:, :, 3]
    else:
        coverage = 1.0 - (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2])

    t_turdsize, t_blur, t_alphamax, t_level, t_opttol = _trace_settings(char=char)
    if t_blur > 0:
        cov_img = Image.fromarray((np.clip(coverage, 0, 1) * 255).astype(np.uint8))
        smooth = np.asarray(cov_img.filter(ImageFilter.GaussianBlur(t_blur)), dtype=np.float32) / 255.0
    else:
        smooth = coverage
    mask = smooth >= t_level
    geom = trace_mask(mask, turdsize=t_turdsize, alphamax=t_alphamax, opttolerance=t_opttol)

    dbg = os.path.join(OUTPUT, "debug")
    os.makedirs(dbg, exist_ok=True)
    cell_img.save(os.path.join(dbg, "%s_cell.png" % char))
    Image.fromarray((mask * 255).astype(np.uint8)).save(os.path.join(dbg, "%s_mask.png" % char))

    svg_path = os.path.join(dbg, "%s_trace.svg" % char)
    if geom is not None and not geom.is_empty:
        parts = []
        for cmd in _geometry_to_cmds(geom):
            if cmd[0] == "Z":
                parts.append("Z")
            else:
                parts.append("%s %.1f %.1f" % (cmd[0], cmd[1], cmd[2]))
        path_d = " ".join(parts)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">'
                    '<rect width="1000" height="1000" fill="#111"/>'
                    '<path d="%s" fill="#eee" fill-rule="evenodd"/></svg>' % path_d)
    else:
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">'
                    '<rect width="1000" height="1000" fill="#300"/>'
                    '<text x="20" y="60" fill="#f66" font-size="40">sin geometría</text></svg>')

    return {
        "char": char,
        "row": r + 1, "col": c + 1,
        "cov_max": round(float(np.max(smooth)) if smooth.size else 0.0, 4),
        "cov_mean": round(float(np.mean(smooth)) if smooth.size else 0.0, 4),
        "ink_pixels": int(np.sum(mask)),
        "geom_empty": geom is None or geom.is_empty,
        "settings": {"turdsize": t_turdsize, "blur": t_blur, "alphamax": t_alphamax,
                     "threshold": t_level, "opttolerance": t_opttol},
        "files": {
            "cell": os.path.relpath(os.path.join(dbg, "%s_cell.png" % char), BASE_DIR),
            "mask": os.path.relpath(os.path.join(dbg, "%s_mask.png" % char), BASE_DIR),
            "trace_svg": os.path.relpath(svg_path, BASE_DIR),
        },
    }


def accent_params(char):
    store = _state["project"].get("accent_adjust", {})
    base = {"dx": 0.0, "dy": 0.0, "s": 1.0}
    base.update({k: float(v) for k, v in store.get("*", {}).items() if k in base})
    base.update({k: float(v) for k, v in store.get(char, {}).items() if k in base})
    return base


ACCENT_MARK = "´"   # tilde aguda
TILDE_MARK = "~"    # virgulilla para Ñ/ñ

# acentuada -> (base, marca)
ACCENT_PAIRS = {
    "Á": ("A", ACCENT_MARK),
    "É": ("E", ACCENT_MARK),
    "Í": ("I", ACCENT_MARK),
    "Ó": ("O", ACCENT_MARK),
    "Ú": ("U", ACCENT_MARK),
    "á": ("a", ACCENT_MARK),
    "é": ("e", ACCENT_MARK),
    "í": ("ı", ACCENT_MARK),   # palo sin punto
    "ó": ("o", ACCENT_MARK),
    "ú": ("u", ACCENT_MARK),
    "Ñ": ("N", TILDE_MARK),
    "ñ": ("n", TILDE_MARK),
}


def _cmds_geom(cmds):
    geom, ring = None, []
    for cmd in list(cmds) + [["Z"]]:
        if cmd[0] == "M":
            ring = [(cmd[1], cmd[2])]
        elif cmd[0] == "L":
            ring.append((cmd[1], cmd[2]))
        elif cmd[0] == "Z":
            if len(ring) >= 3:
                poly = Polygon(ring).buffer(0)
                geom = poly if geom is None else geom.symmetric_difference(poly)
            ring = []
    return geom


def _glyph_geom(g):
    if g.get("outline_cmds"):
        return _cmds_geom(g["outline_cmds"])
    return _glyph_geometry(_contour_items(g))


def compose_accents(force=False):
    global _accents_hash
    project = _state["project"]
    gl = project["glyphs"]

    mark_sig = json.dumps(
        {m: (gl.get(m) or {}).get("outline_cmds", []) for _, m in ACCENT_PAIRS.values()},
        sort_keys=True)
    adj_sig = json.dumps(project.get("accent_adjust", {}))
    bases_sig = "".join(
        json.dumps((gl.get(b) or {}).get("outline_cmds", []))
        for b, _ in ACCENT_PAIRS.values() if b in gl)

    current_hash = hash((mark_sig, adj_sig, bases_sig))
    if not force and _accents_hash == current_hash:
        return

    if force:
        _missing_logged.clear()

    from shapely import affinity
    changed = False
    for acc, (base_ch, mark_ch) in ACCENT_PAIRS.items():
        base = gl.get(base_ch)
        mark = gl.get(mark_ch)
        if not base:
            key = ("base", base_ch, acc)
            if key not in _missing_logged:
                _missing_logged.add(key)
                cell_idx = TEMPLATE_CHARS.index(base_ch) if base_ch in TEMPLATE_CHARS else -1
                pos_txt = ""
                if cell_idx >= 0:
                    r_, c_ = divmod(cell_idx, RENDER_COLS)
                    pos_txt = " (fila %d, col %d)" % (r_ + 1, c_ + 1)
                log("Tildes: falta base '%s'%s para componer '%s'. Si dibujaste esa celda, bajá el umbral o pulsá Re-trazar." % (base_ch, pos_txt, acc))
            if acc in gl and gl[acc].get("source") == "composed":
                gl.pop(acc, None)
                changed = True
            continue
        if not mark:
            key = ("mark", mark_ch, acc)
            if key not in _missing_logged:
                _missing_logged.add(key)
                log("Tildes: falta marca '%s' para componer '%s'." % (mark_ch, acc))
            if acc in gl and gl[acc].get("source") == "composed":
                gl.pop(acc, None)
                changed = True
            continue
        bg, mg = _glyph_geom(base), _glyph_geom(mark)
        if bg is None or mg is None:
            continue
        bx, by = base["cell"]["x"], base["cell"]["y"]
        mx, my = mark["cell"]["x"], mark["cell"]["y"]
        base_rel = affinity.translate(bg, -bx, -by)
        mark_rel = affinity.translate(mg, -mx, -my)
        bminx, bminy, bmaxx, _ = base_rel.bounds
        mminx, _, mmaxx, mmaxy = mark_rel.bounds
        adj = accent_params(acc)
        mcx, mcy = (mminx + mmaxx) / 2, mmaxy
        mark_rel = affinity.scale(mark_rel, adj["s"], adj["s"], origin=(mcx, mcy))
        mminx, _, mmaxx, mmaxy = mark_rel.bounds
        dx = (bminx + bmaxx) / 2 - (mminx + mmaxx) / 2 + adj["dx"]
        dy = bminy - mmaxy - adj["dy"]
        comp = base_rel.union(affinity.translate(mark_rel, dx, dy))

        if acc in TEMPLATE_CHARS:
            r, c = divmod(TEMPLATE_CHARS.index(acc), RENDER_COLS)
            ax, ay = c * RENDER_CELL, r * RENDER_CELL
        else:
            ax, ay = base["cell"]["x"], base["cell"]["y"]

        cmds = []
        for cmd in _geometry_to_cmds(comp):
            cmds.append(["Z"] if cmd[0] == "Z" else [cmd[0], cmd[1] + ax, cmd[2] + ay])
        gl[acc] = {"char": acc, "cell": {"x": ax, "y": ay}, "advance": base.get("advance", 500),
                   "outline_cmds": cmds, "source": "composed",
                   "composed_from": [base_ch, mark_ch]}
        changed = True

    if changed:
        bump_version()
    _accents_hash = current_hash


_PENDING = {}
GIVE_UP_SECONDS = 30.0
STABLE_CHECK_SECONDS = 2.0


def _file_is_stable(path):
    st = _PENDING.setdefault(path, {"size": -1, "since": time.time(), "first_seen": time.time(), "tries": 0, "msg": ""})
    size = os.path.getsize(path)
    now = time.time()
    if size != st["size"]:
        st["size"], st["since"] = size, now
        return False
    return (now - st["since"]) >= STABLE_CHECK_SECONDS


class RenderSizeError(ValueError):
    pass


def _render_key(path):
    digits = "".join(ch for ch in os.path.basename(path) if ch.isdigit())
    return (int(digits) if digits else 0, os.path.getmtime(path))


def _supersede_old_renders(all_renders):
    if len(all_renders) < 2:
        return all_renders
    newest = max(all_renders, key=_render_key)
    for path in all_renders:
        if path == newest:
            continue
        if not _file_is_stable(path):
            continue
        dest_dir = os.path.join(os.path.dirname(path), "procesado")
        os.makedirs(dest_dir, exist_ok=True)
        try:
            shutil.move(path, os.path.join(dest_dir, os.path.basename(path)))
            log("Render superado (no se importa): %s" % os.path.basename(path))
        except OSError as e:
            log("No se pudo apartar render superado %s: %s" % (os.path.basename(path), e))
        _PENDING.pop(path, None)
    return [newest]


def _find_last_processed_render():
    best = None
    best_key = None
    for inbox in INBOX_DIRS:
        for d in (inbox, os.path.join(inbox, "procesado")):
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.lower().startswith("render_") and (f.lower().endswith(".png") or f.lower().endswith(".jpg") or "." not in f):
                    p = os.path.join(d, f)
                    k = _render_key(p)
                    if best_key is None or k > best_key:
                        best, best_key = p, k
    return best


def process_inbox():
    total_pending = 0
    imported = False
    all_renders = []
    for inbox in INBOX_DIRS:
        os.makedirs(inbox, exist_ok=True)
        for f in os.listdir(inbox):
            p = os.path.join(inbox, f)
            if os.path.isfile(p) and f.lower().startswith("render_") and (
                    f.lower().endswith(".png") or f.lower().endswith(".jpg") or "." not in f):
                all_renders.append(p)
    keep_renders = set(_supersede_old_renders(all_renders)) if all_renders else set()
    for inbox in INBOX_DIRS:
        processed = os.path.join(inbox, "procesado")
        errors = os.path.join(inbox, "errores")
        os.makedirs(inbox, exist_ok=True)
        os.makedirs(processed, exist_ok=True)
        os.makedirs(errors, exist_ok=True)
        pending = sorted(f for f in os.listdir(inbox)
                         if os.path.isfile(os.path.join(inbox, f)) and (
                             (f.lower().startswith("export_") and f.lower().endswith(".json"))
                             or os.path.join(inbox, f) in keep_renders))
        total_pending += len(pending)
        for name in pending:
            src = os.path.join(inbox, name)
            st = _PENDING.setdefault(src, {"size": -1, "since": time.time(), "first_seen": time.time(), "tries": 0, "msg": ""})
            try:
                if not _file_is_stable(src):
                    if st["tries"] == 0:
                        st["tries"] = 0
                        log("Esperando a que termine de escribirse: %s (%.1f MB)" % (name, os.path.getsize(src) / 1e6))
                        st["tries"] = -1
                    continue
                first_try = st["tries"] <= 0
                st["tries"] = max(st["tries"], 0) + 1
                mb = os.path.getsize(src) / 1e6
                t0 = time.time()
                if first_try:
                    log("Procesando %s desde %s (%.1f MB)" % (name, inbox, mb))
                if name.lower().endswith(".json"):
                    _job_start(name, 1, "Importando vectores")
                    with _lock:
                        count = import_file(src)
                    _job_end("Vectores importados")
                else:
                    count, _, _ = import_render(src)
                log("Importado %s en %.1f s (%d glifos)" % (name, time.time() - t0, count))
                shutil.move(src, os.path.join(processed, name))
                _PENDING.pop(src, None)
                imported = True
            except RenderSizeError as e:
                log("Render rechazado %s: %s (movido a errores)" % (name, e))
                try:
                    shutil.move(src, os.path.join(errors, name))
                except OSError:
                    pass
                _PENDING.pop(src, None)
                with _lock:
                    _state["watch"]["errors"] += 1
            except Exception as e:
                import traceback
                msg = "%s: %s" % (type(e).__name__, e)
                if msg != st["msg"]:
                    st["msg"] = msg
                    log("Error al importar %s: %s" % (name, msg))
                    for line in traceback.format_exc().strip().splitlines()[-4:]:
                        log("  " + line)
                if time.time() - st["first_seen"] > GIVE_UP_SECONDS:
                    log("No se pudo importar %s tras %d s: movido a errores." % (name, GIVE_UP_SECONDS))
                    try:
                        shutil.move(src, os.path.join(errors, name))
                    except OSError:
                        pass
                    _PENDING.pop(src, None)
                    with _lock:
                        _state["watch"]["errors"] += 1
    with _lock:
        _state["watch"]["last_scan"] = time.strftime("%H:%M:%S")
        _state["watch"]["pending"] = total_pending
    if imported:
        _job_start("fuente", 1, "Componiendo tildes y generando fuente")
        with _lock:
            compose_accents(force=True)
            save_project()
        rebuild()
        _job_end("Fuente generada")
    return imported


def glyph_preview(char):
    with _lock:
        g = _state["project"]["glyphs"].get(char)
        scale = float(_state["project"]["metrics"].get("scale", 1.0))
        baseline = float(_state["project"]["metrics"].get("baseline_px", 800))
    if not g:
        return None
    ox, oy = (g.get("cell") or {}).get("x", 0), (g.get("cell") or {}).get("y", 0)
    if g.get("outline_cmds"):
        cmds = g["outline_cmds"]
    else:
        geom = _glyph_geometry(_contour_items(g))
        cmds = _geometry_to_cmds(geom) if geom is not None else []
    out = []
    for cmd in cmds:
        if cmd[0] == "Z":
            out.append(["Z"])
        else:
            out.append([cmd[0], round((cmd[1] - ox) * scale, 1), round((cmd[2] - oy) * scale, 1)])
    xs = [p[1] for p in out if p[0] != "Z"]
    ys = [p[2] for p in out if p[0] != "Z"]
    bbox = {"w": round(max(xs) - min(xs), 1), "h": round(max(ys) - min(ys), 1)} if xs else {"w": 0, "h": 0}
    return {"char": char, "advance": g.get("advance", 500), "baseline": baseline,
            "bbox": bbox, "contours": [out] if out else []}


def set_adjust(char, data):
    with _lock:
        entry = {}
        for key in ("advance", "sx", "sy", "dy", "rot"):
            val = data.get(key)
            if val is None or val == "":
                continue
            entry[key] = float(val) if key != "advance" else int(float(val))
        if (entry.get("sx", 1.0) == 1.0 and entry.get("sy", 1.0) == 1.0
                and entry.get("dy", 0.0) == 0.0 and entry.get("rot", 0.0) == 0.0 and "advance" not in entry):
            _state["project"]["adjust"].pop(char, None)
        else:
            _state["project"]["adjust"][char] = entry
        save_project()
    log("Ajuste de %s: %s" % (char, entry or "restablecido"))


def set_chars_kerning(chars, left_val, right_val):
    with _lock:
        project = _state["project"]
        if "kerning_char" not in project:
            project["kerning_char"] = {}

        try:
            l_v = int(left_val)
            r_v = int(right_val)
        except (ValueError, TypeError):
            l_v, r_v = 0, 0

        for c in chars:
            if not isinstance(c, str) or len(c) != 1:
                continue
            if l_v == 0 and r_v == 0:
                project["kerning_char"].pop(c, None)
            else:
                project["kerning_char"][c] = {"l": l_v, "r": r_v}
        save_project()
    log("Kerning base asignado a %d caracteres (izq=%d, der=%d)" % (len(chars), l_v, r_v))


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Fontiador</title>
<style>
:root{--bg:#161616;--panel:#222;--line:#333;--text:#eee;--muted:#999;--ok:#7bd44b;--accent:#f06fc0}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);display:flex;height:100vh;overflow:hidden}
nav{width:200px;background:var(--panel);border-right:1px solid var(--line);padding:1em .6em;display:flex;flex-direction:column;gap:.3em}
nav h1{font-size:1.2em;margin:.2em .4em 1em}
nav button{background:none;color:var(--text);border:0;text-align:left;padding:.6em .8em;border-radius:6px;cursor:pointer;font-size:.95em}
nav button.active,nav button:hover{background:#333}
main{flex:1;overflow:auto;padding:1.2em 1.6em}
section{display:none} section.active{display:block}
h2{font-size:1.1em;margin:.2em 0 .8em}
.row{display:flex;gap:1.4em;align-items:flex-start;flex-wrap:wrap}
.panel{background:var(--panel);border-radius:10px;padding:1em;border:1px solid var(--line)}
.preview{background:#0d0d0d;border-radius:10px;border:1px solid var(--line);display:block}
.ctl{width:340px;max-width:100%}
.slider{margin-bottom:1em}
.slider .head{display:flex;justify-content:space-between;font-size:.9em;color:var(--muted);margin-bottom:.2em}
.slider .head b{color:var(--text);font-variant-numeric:tabular-nums}
input[type=range]{width:100%;accent-color:var(--ok)}
.meter{height:6px;background:#333;border-radius:3px;overflow:hidden;margin-top:.3em}
.meter i{display:block;height:100%;background:var(--ok);width:0}
.btn{background:var(--ok);color:#111;border:0;border-radius:6px;padding:.5em .9em;cursor:pointer;font-weight:600}
.btn.sec{background:#444;color:var(--text)} .btn.on{background:var(--accent)}
.chars{display:grid;grid-template-columns:repeat(auto-fill,minmax(38px,1fr));gap:4px;margin-bottom:1em}
.chars button{background:#2c2c2c;color:var(--text);border:1px solid var(--line);border-radius:5px;padding:.35em 0;cursor:pointer;font-size:1em}
.chars button.sel{border-color:var(--ok);background:#34402a}
input[type=number],select,input[type=text]{background:#111;color:var(--text);border:1px solid #444;border-radius:5px;padding:.4em}
table{border-collapse:collapse;width:100%} td,th{padding:.35em .5em;border-bottom:1px solid var(--line);text-align:left}
pre{background:#0d0d0d;padding:.8em;border-radius:6px;max-height:60vh;overflow:auto;font-size:.85em}
.muted{color:var(--muted);font-size:.9em}
label.chk{display:flex;gap:.5em;align-items:center;margin:.3em 0}
.multi{outline:2px solid #ffd95a}
.chip{display:inline-block;border:1px solid #555;border-radius:14px;padding:.2em .6em;margin:.2em;font-size:.9em}
.chip a{color:#aaa;text-decoration:none;margin-left:.2em}
.ksub{display:none} .ksub.active{display:block}
.ksubtab.active{background:var(--ok);color:#111}
.batchgrid{max-height:160px;overflow-y:auto;padding:6px;background:#111;border:1px solid #444;border-radius:6px}
.batchgrid:focus{outline:none;border-color:var(--ok)}
.lockbtn{background:#222;color:#888;border:1px solid #444;border-radius:5px;padding:.15em .5em;cursor:pointer;font-size:1em;line-height:1}
.lockbtn.on{background:var(--accent);color:#111;border-color:var(--accent)}
/* ---------- Tutoriales ---------- */
#tourRoot{position:fixed;inset:0;z-index:400;display:none}
#tourRoot.on{display:block}
#tourRoot .dim{position:absolute;inset:0;background:rgba(8,8,8,.76);animation:tourFade .18s ease}
@keyframes tourFade{from{opacity:0}to{opacity:1}}
#tourSpot{position:absolute;border-radius:9px;pointer-events:none;box-shadow:0 0 0 3px var(--ok), 0 0 0 3000px rgba(8,8,8,.76);animation:tourPulse 1.5s ease-in-out infinite}
@keyframes tourPulse{0%,100%{box-shadow:0 0 0 3px var(--ok), 0 0 0 3000px rgba(8,8,8,.76)}50%{box-shadow:0 0 0 6px var(--accent), 0 0 0 3000px rgba(8,8,8,.76)}}
#tourCard{position:absolute;width:470px;max-width:calc(100vw - 2em);background:var(--panel);border:1px solid #4a4a4a;border-radius:12px;padding:1em 1.1em;box-shadow:0 18px 50px rgba(0,0,0,.65);animation:tourPop .2s ease}
@keyframes tourPop{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}
#tourCard h3{margin:0 0 .5em;font-size:1.05em;display:flex;align-items:center;gap:.5em}
#tourProg{font-weight:600;font-size:.72em;color:var(--ok);border:1px solid var(--line);border-radius:20px;padding:.12em .6em;font-variant-numeric:tabular-nums}
#tourBody{font-size:.95em;line-height:1.5;color:var(--text)}
#tourBody b{color:var(--ok)}
#tourBody ol{margin:.4em 0 .2em 1.1em;padding:0}
#tourKeys{display:flex;flex-wrap:wrap;gap:.4em;margin-top:.75em}
.tk{background:#111;border:1px solid #555;border-bottom-width:3px;border-radius:6px;padding:.16em .5em;font-size:.78em;font-family:ui-monospace,Consolas,monospace;color:#ddd}
.tk.sep{background:none;border:0;color:var(--muted);padding:.16em 0}
#tourCanvas{margin:.85em 0 .1em;background:#0d0d0d;border:1px solid var(--line);border-radius:9px;display:block;width:100%}
#tourBar{display:flex;align-items:center;gap:.5em;margin-top:1em}
#tourBar .sp{flex:1}
#tourBar button{font-size:.9em}
#tourHint{margin-top:.6em;font-size:.76em;color:var(--muted)}
#tourBtns{position:absolute;top:1.1em;right:1.3em;display:flex;gap:.4em;align-items:center}.tourHelp{background:#2c2c2c;color:var(--muted);border:1px solid var(--line);border-radius:50%;width:26px;height:26px;cursor:pointer;font-size:.95em;font-weight:700;line-height:1;padding:0}
.tourHelp:hover{color:var(--text);border-color:var(--ok);background:#34402a}
#updBanner{display:none;background:#2a3a22;border-bottom:1px solid var(--ok);padding:.5em 1em;font-size:.9em;align-items:center;gap:.8em}
#updBanner.on{display:flex}
/* ---------- Pantalla de inicio ---------- */
.hero{background:linear-gradient(135deg,#22301c 0%,var(--panel) 60%);border:1px solid #3d5a2d;border-radius:14px;padding:1.5em;margin-bottom:1.2em}
.hero h2{font-size:1.45em;margin:0 0 .35em}
.hero p{color:#cfcfcf;margin:0 0 1em;max-width:60ch}
.hero .acciones{display:flex;gap:.6em;flex-wrap:wrap}
#impZona{border:2px dashed #4d6b3a;border-radius:12px;padding:1.4em;text-align:center;cursor:pointer;transition:background .15s,border-color .15s}
#impZona:hover,#impZona:focus{background:#26301f;border-color:var(--ok);outline:none}
#impZona .grande{font-size:1.1em;font-weight:700;color:var(--text);display:block;margin-bottom:.25em}
#impZona .chico{color:var(--muted);font-size:.9em}
.accesos{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:.7em}
.acceso{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:.85em 1em;cursor:pointer;text-align:left;color:var(--text);font-size:.95em}
.acceso:hover,.acceso:focus{border-color:var(--ok);background:#2c3427;outline:none}
.acceso b{display:block;margin-bottom:.15em}
.acceso span{color:var(--muted);font-size:.86em;line-height:1.35}
#updBanner a{color:var(--ok)}
#updBanner button{margin-left:auto;background:none;border:1px solid var(--line);color:var(--muted);border-radius:6px;padding:.2em .6em;cursor:pointer}
#tourCursor{position:fixed;z-index:399;display:none;border:2px solid var(--accent);border-radius:7px;pointer-events:none;transition:all .22s ease;box-shadow:0 0 0 3px rgba(240,111,192,.22)}
@media (prefers-reduced-motion:reduce){
  #tourSpot{animation:none}#tourCard{animation:none}#tourRoot .dim{animation:none}
  #tourCursor{transition:none}
}
</style></head><body>
<div id="jobBar" style="display:none;position:fixed;top:0;left:0;right:0;height:34px;background:#111;border-bottom:1px solid #333;z-index:99;padding:5px 12px;font-size:.85em;box-sizing:border-box">
  <div id="jobTxt" style="margin-bottom:3px"></div>
  <div style="height:6px;background:#333;border-radius:3px;overflow:hidden"><i id="jobFill" style="display:block;height:100%;width:0;background:#7bd44b"></i></div>
</div>
<div id="updBanner">
  <span id="updBannerTxt"></span>
  <button id="updBannerClose" title="Ocultar hasta la próxima vez">Ocultar</button>
</div>
<nav>
<h1>Fontiador</h1>
<button data-tab="imp" class="active">Inicio</button>
<button data-tab="dim">Dimensiones</button>
<button data-tab="kern">Kerning</button>
<button data-tab="words">Palabras</button>
<button data-tab="accent">Tildes</button>
<button data-tab="sets">Conjuntos</button>
<button data-tab="font">Fuente</button>
<button data-tab="log">Registro</button>
<p class="muted" style="margin-top:auto" id="navcount"></p>
</nav>
<main>

<section id="tab-dim">
<h2>Dimensiones</h2>
<div class="row" style="align-items:center;margin-bottom:.6em">
  <input type="text" id="charSearch" placeholder="Buscar carácter…" style="width:220px">
  <button class="btn sec" id="reloadBtn" title="Recargar glifos desde el servidor">↻ Recargar</button>
  <button class="btn sec" id="debugBtn" title="Vuelca máscara y trazado de la celda actual a output/debug/">🔍 Diagnóstico</button>
  <span class="muted">Clic: seleccionar · Mayús+clic o Mayús+flechas: multiselección · Ctrl+clic: comparar · Enter: solo este · Ctrl+Enter: toggle</span>
</div>
<div id="dimCats" class="row" style="gap:.3em;margin-bottom:.3em"></div>
<div class="chars" id="dimChars"></div>
<div class="row">
<svg id="dimSvg" class="preview" viewBox="-300 -200 2000 1400" style="width:520px;height:360px"></svg>
<div class="panel ctl">
  <label class="chk"><input type="checkbox" id="lockChk" checked> Escala bloqueada a proporción</label>
  <div class="row" style="gap:.5em;margin:.4em 0 1em">
    <button class="btn sec" id="resetRatio">Proporción original</button>
    <button class="btn sec" id="resetRot">Sin rotación</button>
  </div>
  <div id="sliders"></div>
  <p class="muted" id="dimInfo"></p>

  <div class="panel" style="margin-top:1em">
    <b>Trazado del pincel</b>
    <p class="muted" style="margin:.3em 0">
      Ajusta cuánto del raster se conserva vs. cuánto se vectoriza. Se aplica al
      <b>Re-trazar</b> o en la próxima importación de render.
    </p>
    <div class="slider"><div class="head"><span>Suavizado (blur)</span><b id="v_blur"></b></div>
      <input type="range" id="r_blur" min="0" max="6" step="0.1" value="0.5">
      <div class="meter"><i id="m_blur"></i></div></div>
    <div class="slider"><div class="head"><span>Esquinas (alphamax)</span><b id="v_alphamax"></b></div>
      <input type="range" id="r_alphamax" min="0" max="1.33" step="0.01" value="0.4">
      <div class="meter"><i id="m_alphamax"></i></div></div>
    <div class="slider"><div class="head"><span>Umbral de tinta</span><b id="v_threshold"></b></div>
      <input type="range" id="r_threshold" min="0.05" max="0.95" step="0.01" value="0.5">
      <div class="meter"><i id="m_threshold"></i></div></div>
    <div class="slider"><div class="head"><span>Mancha mínima (px)</span><b id="v_turdsize"></b></div>
      <input type="range" id="r_turdsize" min="0" max="200" step="1" value="20">
      <div class="meter"><i id="m_turdsize"></i></div></div>
    <div class="slider"><div class="head"><span>Tolerancia de curva</span><b id="v_opttolerance"></b></div>
      <input type="range" id="r_opttolerance" min="0.01" max="1" step="0.01" value="0.1">
      <div class="meter"><i id="m_opttolerance"></i></div></div>
    <div class="row" style="gap:.4em">
      <button class="btn sec" id="traceDefaults">Valores por defecto</button>
      <button class="btn" id="retraceBtn">↻ Re-trazar último render</button>
    </div>
    <p class="muted" id="traceInfo" style="font-size:.85em"></p>
  </div>

  <div class="panel" style="margin-top:1em">
    <b>Comparar tamaños</b>
    <p class="muted" style="margin:.3em 0">Se dibuja en gris la base; los demás en color.</p>
    <div class="row" style="gap:.4em;margin-bottom:.6em;align-items:center">
      <button class="btn sec" id="cmpAdd">Añadir actual</button>
      <label>Base <select id="cmpBase"></select></label>
    </div>
    <div id="cmpChips"></div>
  </div>
</div>
</div>
</section>

<section id="tab-kern">
  <div class="subtabs" style="display:flex;gap:.3em;margin-bottom:1em">
    <button class="btn sec ksubtab active" data-ksub="pair">Manual por par</button>
    <button class="btn sec ksubtab" data-ksub="base">Base por lote</button>
  </div>

  <div id="ksub-pair" class="ksub active">
    <h2>Kerning Manual por Par</h2>
    <p class="muted" style="margin:.2em 0 1em">
      Paso <b id="kmStep">1/3 — Izquierda</b>. Flechas navegan · Shift extiende · Ctrl+Enter toggle · <b>Enter avanza</b> · <b>Esc vuelve</b>.
    </p>
    <div class="row" style="align-items:flex-start;gap:1em">
      <div style="width:520px;max-width:100%">
        <svg id="pairSvg" class="preview" viewBox="-200 -200 2600 1400" style="width:100%;height:280px"></svg>
        <p class="muted" id="kernMode" style="font-size:.8em;margin:.3em 0"></p>
      </div>
      <div class="panel ctl" style="width:280px">
        <div class="row" style="gap:.4em;align-items:center;margin-bottom:.4em;font-size:.9em">
          <span>Izq.</span>
          <button class="lockbtn" id="lockL" title="Fijar izquierda (clic o Bloq Mayús)">🔓</button>
          <span style="margin-left:auto">Der.</span>
          <button class="lockbtn" id="lockR" title="Fijar derecha (clic o Bloq Mayús)">🔓</button>
        </div>
        <div class="slider"><div class="head"><span>Separación Final</span><b id="kvOut">0</b></div>
          <input type="range" id="kvS" min="-600" max="600" value="0">
          <div class="meter"><i id="kvM"></i></div></div>
        <p class="muted" id="kvInfo" style="font-size:.9em"></p>
        <button class="btn" id="kvSave">Guardar Excepción</button>
      </div>
    </div>

    <h2 style="margin-top:1.5em">Lote activo</h2>
    <div class="chars batchgrid" data-side="pair" tabindex="0" style="margin-bottom:1em"></div>

    <h2 style="margin-top:1.5em">Pares con ajuste manual guardado</h2>
    <div class="row" style="gap:.4em;margin-bottom:.4em;align-items:center">
      <button class="btn sec" id="kernSelAll">Todos</button>
      <button class="btn sec" id="kernSelNone">Ninguno</button>
      <button class="btn" id="kernDelSel">Eliminar seleccionados</button>
    </div>
    <table>
      <thead><tr>
        <th style="width:2.5em"><input type="checkbox" id="kernChkAll"></th>
        <th>Izquierda</th><th>Derecha</th><th>Ajuste</th><th>Origen</th><th></th>
      </tr></thead>
      <tbody id="kerntable"></tbody>
    </table>
  </div>

  <div id="ksub-base" class="ksub">
    <h2>Kerning Base por Lote</h2>
    <p class="muted" style="margin-top:0">
      Modifica el kerning base (izquierda/derecha) de las letras del lote.
      Los <b>placeholders</b> son solo para previsualizar: <b>⇄</b> (o <b>Shift+Tab</b>) los intercambia sin tocar el lote.
    </p>

    <div class="panel" style="display:flex;gap:.5em;align-items:center;padding:.4em .6em;margin-bottom:.6em;max-width:560px">
      <label style="font-size:.9em">Placeholder izq. <select id="basePL"></select></label>
      <button class="btn sec" id="baseSwapPL" title="Intercambiar placeholders (Shift+Tab)" style="padding:.2em .6em">⇄</button>
      <label style="font-size:.9em">Placeholder der. <select id="basePR"></select></label>
    </div>

    <svg id="basePrevSvg" class="preview" viewBox="-200 -200 2600 1400" style="width:100%;height:280px;margin-bottom:1em"></svg>

    <div class="panel" style="max-width:900px">
      <p class="muted" style="margin-top:0">
        Escribe letras o usa <b>Flechas</b>. <b>Shift+Flechas</b> extiende, <b>Enter</b> selecciona solo este, <b>Ctrl+Enter</b> agrega/quita.
      </p>
      <div class="chars batchgrid" data-side="base" tabindex="0" style="margin-bottom:1em"></div>

      <div style="display:flex;gap:1.5em;flex-wrap:wrap;align-items:flex-start">
        <div style="flex:1;min-width:250px">
          <label style="display:block;margin-bottom:.3em;font-size:.9em">Izquierda: <b id="kbLv" style="color:var(--ok)">0</b></label>
          <input type="range" id="kbLSlider" min="-600" max="600" value="0" style="width:100%">
          <input type="number" id="kbL" value="0" style="width:5.5em;margin-top:.3em">
        </div>
        <div style="flex:1;min-width:250px">
          <label style="display:block;margin-bottom:.3em;font-size:.9em">Derecha: <b id="kbRv" style="color:var(--ok)">0</b></label>
          <input type="range" id="kbRSlider" min="-600" max="600" value="0" style="width:100%">
          <input type="number" id="kbR" value="0" style="width:5.5em;margin-top:.3em">
        </div>
        <div style="flex:1;min-width:250px">
          <label style="display:block;margin-bottom:.3em;font-size:.9em">Ambos: <b id="kbBothv" style="color:var(--ok)">—</b></label>
          <input type="range" id="kbBothSlider" min="-600" max="600" value="0" style="width:100%">
          <input type="number" id="kbBoth" placeholder="=" style="width:5.5em;margin-top:.3em">
        </div>
      </div>

      <div class="row" style="gap:.4em;margin-top:1em">
        <div>
          <label style="display:block;margin-bottom:.3em;font-size:.9em">Lote (<span id="kbSelCount">0</span>)</label>
          <div id="kbSelPreview" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:bold;color:var(--ok);height:2.2em;line-height:2.2em;background:#111;padding:0 .6em;border-radius:5px;border:1px solid #333">Ninguna</div>
        </div>
        <button class="btn" id="kbApply" style="align-self:flex-end">Aplicar a Lote</button>
        <button class="btn sec" id="kbDelete" style="align-self:flex-end" title="Pone izquierda y derecha en 0 para todo el lote">Restablecer a 0</button>
      </div>
    </div>
  </div>
</section>

<section id="tab-imp" class="active">
<h2>Inicio <span class="muted" id="impModo" style="font-size:.75em;font-weight:400"></span></h2>

<div class="hero">
  <h2>Traé tu rejilla de glifos</h2>
  <p>Elegí el archivo que exportaste de tu programa de diseño. Fontiador lo traza,
     arma los glifos y reconstruye la fuente.</p>
  <div id="impZona" tabindex="0" role="button" aria-label="Elegir archivo para importar">
    <span class="grande">Elegir archivo…</span>
    <span class="chico">PNG, JPG, SVG o la exportación JSON de glifos · se pueden elegir varios</span>
  </div>
  <div class="acciones" style="margin-top:.9em">
    <button class="btn sec" id="impRescan">Re-escanear inbox</button>
    <button class="btn sec" id="impRefresh">↻ Actualizar</button>
    <button class="btn sec" id="impTutorial">Ver el tutorial</button>
  </div>
  <p class="muted" id="impPickHint" style="margin:.8em 0 0"></p>
  <div id="impResultado"></div>
</div>

<p class="muted" style="margin:.2em 0 .6em">Ir a una sección</p>
<div class="accesos" id="impAccesos">
  <button class="acceso" data-ir="dim"><b>Dimensiones</b><span>Altura, ancho, posición y trazado de cada glifo</span></button>
  <button class="acceso" data-ir="kern"><b>Kerning</b><span>El espacio entre pares de letras</span></button>
  <button class="acceso" data-ir="words"><b>Palabras</b><span>Probá texto real con la fuente</span></button>
  <button class="acceso" data-ir="accent"><b>Tildes</b><span>Ajustá las vocales acentuadas</span></button>
  <button class="acceso" data-ir="sets"><b>Conjuntos</b><span>Qué caracteres entran en la fuente</span></button>
  <button class="acceso" data-ir="font"><b>Fuente</b><span>Nombre, estilo, construir y actualizaciones</span></button>
  <button class="acceso" data-ir="log"><b>Registro</b><span>Qué pasó y qué falló</span></button>
</div>

<div class="panel" style="margin-top:1.2em">
  <p style="margin-top:0"><b>Formato que espera la app</b></p>
  <div id="impFormato" class="muted">Cargando…</div>
  <p style="margin-bottom:.4em;margin-top:.8em">
    <a class="btn" href="/api/import/plantilla.svg" download="fontiador-plantilla.svg"
       style="text-decoration:none;display:inline-block">Descargar plantilla (SVG)</a>
    <a class="btn sec" href="/api/import/plantilla.png" download="fontiador-plantilla.png"
       style="text-decoration:none;display:inline-block;margin-left:.4em">Versión PNG</a>
  </p>
  <p class="muted">La plantilla ya trae la cuadrícula, la línea base y el orden de los caracteres.
     Se puede abrir en Affinity, Illustrator, Inkscape, Figma o CorelDRAW y dibujar encima.</p>
  <details style="margin-top:.6em">
    <summary style="cursor:pointer">Ver la correspondencia de cada celda</summary>
    <div id="impOrden" style="max-height:320px;overflow:auto;margin-top:.6em"></div>
  </details>
</div>

<div class="panel">
  <p style="margin-top:0"><b>Carpetas vigiladas</b></p>
  <div id="impCarpetas" class="muted">Cargando…</div>
  <p style="margin-bottom:0;margin-top:.8em">
    <button class="btn sec" id="impClearErr">Vaciar errores</button>
    <button class="btn sec" id="impClearProc" style="margin-left:.4em">Vaciar procesados</button>
  </p>
</div>
</section>

<section id="tab-words">
<h2>Palabras</h2>
<div class="row" style="margin-bottom:1em;align-items:center">
  <input type="text" id="wordIn" value="Hola mundo" style="width:420px;font-size:1.1em">
  <label class="chk"><input type="checkbox" id="wordKern"> aplicar kerning</label>
</div>
<div class="panel" style="overflow:auto">
  <svg id="wordSvg" style="height:320px;background:#0d0d0d;border-radius:6px;display:block;width:100%" viewBox="-100 -200 1200 1400"></svg>
</div>
<p class="muted" id="wordInfo"></p>
</section>

<section id="tab-accent">
<h2>Tildes</h2>
<p class="muted" style="margin-top:0">Las vocales acentuadas usan la tilde ´ de la plantilla; la Ñ/ñ usan la virgulilla ~. Ajusta todas a la vez o por letra (la letra prevalece sobre el general).</p>
<div class="row" style="align-items:flex-start;gap:1em">
  <div style="width:360px;max-width:100%">
    <div class="panel" style="display:flex;gap:.5em;align-items:center;margin-bottom:.5em">
      <label>Aplicar a <select id="accSel"></select></label>
    </div>
    <svg id="accSvg" class="preview" viewBox="-300 -300 1400 1500" style="width:100%;height:360px"></svg>
  </div>
  <div class="panel ctl" style="width:300px">
    <div class="slider"><div class="head"><span>Desplazamiento X</span><b id="accXv"></b></div>
      <input type="range" id="accX" min="-300" max="300" step="5" value="0"></div>
    <div class="slider"><div class="head"><span>Desplazamiento Y</span><b id="accYv"></b></div>
      <input type="range" id="accY" min="-300" max="300" step="5" value="0"></div>
    <div class="slider"><div class="head"><span>Escala</span><b id="accSv"></b></div>
      <input type="range" id="accS" min="50" max="200" step="1" value="100"></div>
    <p class="muted" id="accInfo"></p>
    <button class="btn sec" id="recomposeBtn" style="margin-right:.4em">↻ Recomponer</button>
    <button class="btn sec" id="accReset">Restablecer</button>
  </div>
</div>
</section>

<section id="tab-sets">
<h2>Conjuntos de caracteres</h2>
<div class="panel" style="max-width:420px">
<label class="chk"><input type="checkbox" id="cs_upper"> Mayúsculas</label>
<label class="chk"><input type="checkbox" id="cs_lower"> Minúsculas</label>
<label class="chk"><input type="checkbox" id="cs_digits"> Números</label>
<label class="chk"><input type="checkbox" id="cs_punct"> Puntuación</label>
<p style="margin-top:1em"><button class="btn sec" id="tourReset">↻ Restablecer tutoriales</button></p>
<p class="muted">Vuelve a mostrar el tutorial de cada sección la próxima vez que la abras.</p>
</div>
</section>

<section id="tab-font">
<h2>Fuente</h2>
<div class="panel" style="max-width:520px">
<p><label>Familia <input type="text" id="family"></label></p>
<p><label>Estilo <input type="text" id="style" size="10"></label></p>
<p><button class="btn" id="build">Reconstruir fuente</button></p>
<p class="muted" id="out"></p>
<p style="margin-top:1.4em;border-top:1px solid var(--line);padding-top:1em">
  <b>Versión <span id="verActual">…</span></b><br>
  <span class="muted" id="updEstado">Todavía no se comprobó si hay actualizaciones.</span>
</p>
<p>
  <button class="btn sec" id="updBuscar">Buscar actualizaciones</button>
  <a class="btn sec" id="updDescargar" href="#" target="_blank" rel="noopener"
     style="text-decoration:none;display:none;margin-left:.4em">Abrir la descarga</a>
</p>
<details id="updNotas" style="display:none;margin-top:.6em">
  <summary style="cursor:pointer">Ver qué cambió en la versión nueva</summary>
  <pre id="updNotasTxt" style="max-height:240px"></pre>
</details>
</div>
</section>

<section id="tab-log">
<h2>Registro</h2>
<pre id="log"></pre>
</section>

</main>
<script>
const M = {asc:50, cap:100, xh:300, base:800, desc:1000};

const S = {
  status: null, char: null, lock: true, uniform: 100,
  adj: {}, base: {}, cache: {}, chars: '', busyUntil: 0, version: -1
};

const KB_SEL = new Set();
let KB_CURSOR = 0;
let KB_ANCHOR = 0;

// Estado del par manual (dos lotes + paso + candados)
const KSTATE = {step: 'L', L: new Set(), R: new Set(), lockL: false, lockR: false};
let DIM_STEP = 'chars';

async function api(path, body){
  const r = await fetch(path, body === undefined ? {} :
    {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  return r.json();
}
function $(id){ return document.getElementById(id); }

function clearGlyphCache(){ S.cache = {}; }

// ---------- fillSelect ----------
function fillSelect(id, chars, noneOption, defaultValue){
  const sel = $(id);
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '';
  if (noneOption){ const o = document.createElement('option'); o.value = ''; o.textContent = 'Sin base'; sel.appendChild(o); }
  for (const c of (chars || '')){ const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o); }
  if (prev && chars && chars.includes(prev)) sel.value = prev;
  else if (defaultValue && chars && chars.includes(defaultValue)) sel.value = defaultValue;
  else if (chars && chars.length && !noneOption) sel.value = chars[0];
}

// ---------- Geometría ----------
async function baseGlyph(c){
  if (!c) return null;
  if (!S.cache[c]) S.cache[c] = await api('/api/glyph?c=' + encodeURIComponent(c));
  return S.cache[c];
}
function adjOf(c){
  const a = S.adj[c] || {};
  return {advance: a.advance ?? null, sx: a.sx ?? 1, sy: a.sy ?? 1, dy: a.dy ?? 0, rot: a.rot ?? 0};
}
function advOf(g, a){ return a.advance ?? Math.round(g.advance * a.sx); }

function glyphPaths(g, a, dx){
  const B = g.baseline || M.base;
  const adv = advOf(g, a);
  const cx = adv / 2, cy = 400;
  const th = (a.rot || 0) * Math.PI / 180, cs = Math.cos(th), sn = Math.sin(th);
  let d = '';
  for (const cmds of g.contours) for (const cmd of cmds){
    if (cmd[0] === 'Z'){ d += 'Z '; continue; }
    const fx = cmd[1] * a.sx, fy = (B - cmd[2]) * a.sy + a.dy;
    const rx = cx + cs * (fx - cx) - sn * (fy - cy);
    const ry = cy + sn * (fx - cx) + cs * (fy - cy);
    d += cmd[0] + ' ' + (rx + dx).toFixed(1) + ' ' + (B - ry).toFixed(1) + ' ';
  }
  return d;
}
function guides(x0, width){
  let s = '';
  for (const [y,c] of [[M.asc,'#2f3a2f'],[M.cap,'#2f3a2f'],[M.xh,'#3a3a2f'],[M.base,'#7bd44b'],[M.desc,'#2f3a2f']])
    s += '<line x1="'+x0+'" x2="'+(x0+width)+'" y1="'+y+'" y2="'+y+'" stroke="'+c+'" stroke-width="4"/>';
  return s;
}
function showSVGMessage(svgId, msg){
  const svg = $(svgId);
  if (svg) svg.innerHTML = '<text x="20" y="60" fill="#f06fc0" font-size="42" font-family="system-ui">' + msg + '</text>';
}
function setMeter(id, val, min, max){
  if ($(id)) $(id).style.width = Math.max(0, Math.min(100, (val-min)/(max-min)*100)) + '%';
}

function getPairKerning(L, R){
  if (!L || !R) return 0;
  const kbStore = (S.status && S.status.kerning_char) || {};
  const baseL = (kbStore[L] || {}).r || 0;
  const baseR = (kbStore[R] || {}).l || 0;
  const baseTotal = baseL + baseR;
  const manualList = (S.status && S.status.kerning) || [];
  const saved = manualList.find(p => p.left === L && p.right === R);
  const manualOffset = saved ? saved.value : 0;
  return baseTotal + manualOffset;
}

// ---------- Navegación geométrica ----------
function findNeighbor(buttons, fromIdx, dir){
  if (fromIdx < 0 || fromIdx >= buttons.length) return -1;
  const rects = buttons.map(b => b.getBoundingClientRect());
  const cr = rects[fromIdx];
  let best = -1, bestDist = Infinity;
  for (let i = 0; i < buttons.length; i++){
    if (i === fromIdx) continue;
    const r = rects[i];
    let ok = false, dist = 0;
    if (dir === 'left'){ ok = (r.bottom > cr.top + 1) && (r.top < cr.bottom - 1) && (r.right <= cr.left); dist = cr.left - r.right; }
    else if (dir === 'right'){ ok = (r.bottom > cr.top + 1) && (r.top < cr.bottom - 1) && (r.left >= cr.right); dist = r.left - cr.right; }
    else if (dir === 'up'){ ok = (r.right > cr.left + 1) && (r.left < cr.right - 1) && (r.bottom <= cr.top); dist = cr.top - r.bottom; }
    else if (dir === 'down'){ ok = (r.right > cr.left + 1) && (r.left < cr.right - 1) && (r.top >= cr.bottom); dist = r.top - cr.bottom; }
    if (ok && dist < bestDist){ bestDist = dist; best = i; }
  }
  return best;
}

// ---------- Comparación ----------
const CMP = {chars: [], base: null};
const CMP_COLORS = ['#f06fc0','#5ad2ff','#ffd95a','#9b8cff','#ff8a5a','#7bd44b','#ff6b6b','#6bffd1'];
function renderCompare(){
  const box = $('cmpChips');
  if (!box) return;
  box.innerHTML = '';
  CMP.chars.forEach((c,i) => {
    const chip = document.createElement('span'); chip.className = 'chip';
    chip.style.borderColor = CMP_COLORS[i % CMP_COLORS.length];
    chip.innerHTML = c + ' <a href="#">✕</a>';
    chip.querySelector('a').onclick = e => { e.preventDefault(); CMP.chars.splice(i,1); renderCompare(); drawDim(); };
    box.appendChild(chip);
  });
  fillSelect('cmpBase', S.chars, true);
  if ($('cmpBase')) $('cmpBase').value = CMP.base || '';
}
function addToCompare(c){
  if (!c) return;
  if (!CMP.chars.includes(c)) CMP.chars.push(c);
  renderCompare(); drawDim();
}

// ---------- Dimensiones ----------
async function drawDim(){
  const c = S.char;
  if (!c){ showSVGMessage('dimSvg', 'Sin carácter'); return; }
  const g = await baseGlyph(c);
  if (!g || !g.contours){ showSVGMessage('dimSvg', 'Sin glifo para ' + c); return; }
  const a = adjOf(c);
  const adv = advOf(g, a);
  let extra = '';

  if (CMP.base && CMP.base !== c){
    const gb = await baseGlyph(CMP.base);
    if (gb && gb.contours) extra += '<path d="'+glyphPaths(gb, adjOf(CMP.base), 0)+'" fill="#3d3d3d"/>';
  }
  const others = [...KB_SEL].filter(x => x !== c);
  for (const cc of others){
    const gc = await baseGlyph(cc);
    if (gc && gc.contours) extra += '<path d="'+glyphPaths(gc, adjOf(cc), 0)+
      '" fill="rgba(123,212,75,0.28)" stroke="rgba(123,212,75,0.55)" stroke-width="3"/>';
  }
  for (let i = 0; i < CMP.chars.length; i++){
    const cc = CMP.chars[i];
    if (cc === c || cc === CMP.base || others.includes(cc)) continue;
    const gc = await baseGlyph(cc);
    if (gc && gc.contours) extra += '<path d="'+glyphPaths(gc, adjOf(cc), 0)+
      '" fill="none" stroke="'+CMP_COLORS[i % CMP_COLORS.length]+'" stroke-width="6"/>';
  }
  $('dimSvg').innerHTML = guides(-300, 2000) + extra +
    '<rect x="0" y="0" width="'+adv+'" height="1000" fill="none" stroke="#555" stroke-dasharray="12 12"/>' +
    '<path d="'+glyphPaths(g, a, 0)+'" fill="#ffffff" stroke="#ffffff" stroke-width="10" stroke-linejoin="round"/>';
  const w = Math.round((g.bbox?.w || 0) * a.sx), h = Math.round((g.bbox?.h || 0) * a.sy);
  if ($('dimInfo')) {
    $('dimInfo').textContent = 'Editando ' + c + ' (blanco) · caja ' + w + ' × ' + h + ' · avance ' + adv + ' · rotación ' + Math.round(a.rot) + '°' +
      (others.length ? ' · ' + others.length + ' en selección múltiple (verde)' : '') +
      (CMP.base ? ' · base ' + CMP.base + ' (gris)' : '') +
      (CMP.chars.length ? ' · comparadas en color' : '');
  }
}

const DIM_SLIDERS = [
  {key:'uniform', label:'Escala', min:10, max:300, step:1, unit:'%', mode:'lock'},
  {key:'width', label:'Ancho', min:10, max:3000, step:5, unit:' u', mode:'free'},
  {key:'height', label:'Alto', min:10, max:3000, step:5, unit:' u', mode:'free'},
  {key:'dy', label:'Desplazamiento Y', min:-500, max:500, step:5, unit:'', mode:'both'},
  {key:'rot', label:'Rotación', min:-180, max:180, step:1, unit:'°', mode:'both'},
];
function buildSliders(){
  const box = $('sliders');
  if (!box) return;
  box.innerHTML = '';
  for (const s of DIM_SLIDERS){
    const wrap = document.createElement('div'); wrap.className = 'slider'; wrap.id = 'sl_' + s.key;
    wrap.innerHTML = '<div class="head"><span>'+s.label+'</span><b id="v_'+s.key+'"></b></div>' +
      '<input type="range" id="r_'+s.key+'" min="'+s.min+'" max="'+s.max+'" step="'+s.step+'">' +
      '<div class="meter"><i id="m_'+s.key+'"></i></div>';
    box.appendChild(wrap);
    $('r_'+s.key).addEventListener('input', e => onSlider(s.key, parseFloat(e.target.value)));
    $('r_'+s.key).addEventListener('change', () => saveAdj());
  }
}
function currentValues(c){
  const g = S.cache[c] || {bbox:{w:0,h:0}};
  const a = adjOf(c);
  return {
    uniform: S.uniform,
    width: (g.bbox?.w || 0) * a.sx,
    height: (g.bbox?.h || 0) * a.sy,
    dy: a.dy, rot: a.rot,
  };
}
function refreshSliderUI(){
  const c = S.char; if (!c) return;
  const vals = currentValues(c);
  for (const s of DIM_SLIDERS){
    const row = $('sl_'+s.key);
    if (!row) continue;
    const visible = s.mode === 'both' || (s.mode === 'lock' && S.lock) || (s.mode === 'free' && !S.lock);
    row.style.display = visible ? '' : 'none';
    const v = vals[s.key];
    if ($('r_'+s.key)) $('r_'+s.key).value = v;
    if ($('v_'+s.key)) $('v_'+s.key).textContent = Math.round(v) + (s.unit || '');
    setMeter('m_'+s.key, v, s.min, s.max);
  }
  if ($('lockChk')) $('lockChk').checked = S.lock;
}
function onSlider(key, val){
  S.busyUntil = Date.now() + 1500;
  const c = S.char;
  const g = S.cache[c] || {bbox:{w:1,h:1}};
  const a = S.adj[c] = Object.assign({}, S.adj[c] || {});
  if (key === 'uniform'){
    S.uniform = val;
    const u = val / 100;
    const cur = a.sx / Math.max(0.0001, a.sy);
    const r = (isFinite(cur) && cur > 0) ? cur : 1;
    a.sx = u * Math.sqrt(r);
    a.sy = u / Math.sqrt(r);
  }
  if (key === 'width'){ a.sx = val / Math.max(1, g.bbox?.w || 1); }
  if (key === 'height'){ a.sy = val / Math.max(1, g.bbox?.h || 1); }
  if (key === 'dy') a.dy = val;
  if (key === 'rot') a.rot = val;

  for (const other of KB_SEL){
    if (other === c) continue;
    const oa = S.adj[other] = Object.assign({}, S.adj[other] || {});
    if (key === 'uniform'){ oa.sx = a.sx; oa.sy = a.sy; }
    else if (key === 'width'){ oa.sx = a.sx; }
    else if (key === 'height'){ oa.sy = a.sy; }
    else if (key === 'dy'){ oa.dy = a.dy; }
    else if (key === 'rot'){ oa.rot = a.rot; }
  }
  refreshSliderUI(); drawDim(); drawPair(); drawBasePrev();
}
async function saveAdj(){
  const c = S.char; if (!c) return;
  const a = adjOf(c);
  await api('/api/adjust', {char:c, advance:'', sx:a.sx, sy:a.sy, dy:a.dy, rot:a.rot});
  const others = [...KB_SEL].filter(x => x !== c).join('');
  if (others) await api('/api/adjust/many', {chars: others, sx:a.sx, sy:a.sy, dy:a.dy, rot:a.rot});
  await loadStatus();
}
function uniformFrom(a){ return Math.sqrt(Math.max(0.0001, a.sx) * Math.max(0.0001, a.sy)); }
function setLock(on){
  S.lock = on;
  if (S.char) S.uniform = Math.round(uniformFrom(adjOf(S.char)) * 100);
  refreshSliderUI(); drawDim(); drawPair(); drawBasePrev();
}
function resetRatio(){
  if (!S.char) return;
  const a = adjOf(S.char);
  const u = uniformFrom(a);
  const cur = S.adj[S.char] = Object.assign({}, S.adj[S.char] || {});
  cur.sx = cur.sy = u;
  S.uniform = Math.round(u * 100);
  S.lock = true;
  refreshSliderUI(); drawDim(); drawPair(); drawBasePrev(); saveAdj();
}
function resetRot(){
  if (!S.char) return;
  const cur = S.adj[S.char] = Object.assign({}, S.adj[S.char] || {});
  cur.rot = 0; refreshSliderUI(); drawDim(); drawPair(); drawBasePrev(); saveAdj();
}

// ---------- Trazado ----------
const TRACE_KEYS = ['blur','alphamax','threshold','turdsize','opttolerance'];
function fillTraceUI(){
  const t = (S.status && S.status.trace) || {};
  for (const k of TRACE_KEYS){
    const v = t[k];
    const el = $('r_' + k);
    if (v === undefined || !el) continue;
    el.value = v;
    const b = $('v_' + k);
    if (b) b.textContent = (k === 'turdsize') ? Math.round(v) : (+v).toFixed(2);
    const min = parseFloat(el.min), max = parseFloat(el.max);
    setMeter('m_' + k, v, min, max);
  }
}
async function pushTrace(){
  const data = {};
  for (const k of TRACE_KEYS){
    const el = $('r_' + k);
    if (el) data[k] = parseFloat(el.value);
  }
  await api('/api/trace', data);
  await loadStatus();
}
function bindTraceSliders(){
  for (const k of TRACE_KEYS){
    const el = $('r_' + k);
    if (!el) continue;
    el.oninput = () => {
      const v = parseFloat(el.value);
      const b = $('v_' + k);
      if (b) b.textContent = (k === 'turdsize') ? Math.round(v) : v.toFixed(2);
      const min = parseFloat(el.min), max = parseFloat(el.max);
      setMeter('m_' + k, v, min, max);
    };
    el.onchange = pushTrace;
  }
}

// ---------- Caracteres ----------
function renderCharGrid(){
  const q = ($('charSearch') ? $('charSearch').value : '').trim();
  const box = $('dimChars');
  if (!box) return;
  box.innerHTML = '';
  const list = q ? [...S.chars].filter(c => q.includes(c) || c.includes(q)) : [...S.chars];
  for (const c of list){
    const b = document.createElement('button'); b.textContent = c; b.dataset.c = c;
    b.title = 'Clic: seleccionar · Mayús+clic: multiselección · Ctrl+clic: comparar · Enter: solo este · Ctrl+Enter: toggle';
    b.onclick = (e) => {
      if (e.ctrlKey || e.metaKey) addToCompare(c);
      else if (e.shiftKey){
        KB_SEL.has(c) ? KB_SEL.delete(c) : KB_SEL.add(c);
        if (S.char) KB_SEL.add(S.char);
        syncSelectionVisuals();
      } else {
        KB_SEL.clear(); KB_SEL.add(c);
        selectChar(c);
      }
    };
    if (c === S.char) b.classList.add('sel');
    if (KB_SEL.has(c) && c !== S.char) b.classList.add('multi');
    box.appendChild(b);
  }
  if (!list.length) box.innerHTML = '<span class="muted">Sin resultados</span>';
}
async function selectChar(c){
  S.char = c;
  if (!S.cache[c]) await baseGlyph(c);
  S.uniform = Math.round(uniformFrom(adjOf(c)) * 100);
  refreshSliderUI();
  syncSelectionVisuals();
}

function dimMove(dir, extend){
  const btns = [...document.querySelectorAll('#dimChars button')];
  if (!btns.length || !S.char) return;
  const curIdx = btns.findIndex(b => b.dataset.c === S.char);
  if (curIdx < 0) return;
  const best = findNeighbor(btns, curIdx, dir);
  if (best < 0) return;
  const oldChar = S.char;
  const newChar = btns[best].dataset.c;
  if (extend){ KB_SEL.add(oldChar); KB_SEL.add(newChar); }
  selectChar(newChar);
}
document.addEventListener('keydown', e => {
  if (!document.querySelector('nav button[data-tab="dim"].active')) return;
  const el = document.activeElement;
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) return;

  if (e.key === 'Escape'){
    e.preventDefault();
    DIM_STEP = 'chars';
    KB_SEL.clear();
    syncSelectionVisuals();
    return;
  }

  if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.shiftKey){
    e.preventDefault();
    if (DIM_STEP === 'chars'){
      if (KB_SEL.size > 0) DIM_STEP = S.lock ? 'uniform' : 'width';
    } else {
      saveAdj();
      const order = S.lock ? ['chars','uniform','dy','rot'] : ['chars','width','height','dy','rot'];
      const i = order.indexOf(DIM_STEP);
      DIM_STEP = order[(i + 1) % order.length];
    }
    refreshSliderUI();
    return;
  }

  if (e.ctrlKey && e.key === 'Enter'){
    e.preventDefault();
    if (S.char){
      KB_SEL.has(S.char) ? KB_SEL.delete(S.char) : KB_SEL.add(S.char);
      syncSelectionVisuals();
    }
    return;
  }

  if (DIM_STEP === 'chars'){
    const map = {ArrowLeft:'left', ArrowRight:'right', ArrowUp:'up', ArrowDown:'down'};
    const dir = map[e.key];
    if (!dir) return;
    e.preventDefault();
    dimMove(dir, e.shiftKey);
    return;
  }

  const step = e.shiftKey ? 10 : 1;
  let delta = 0;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') delta = -step;
  if (e.key === 'ArrowRight' || e.key === 'ArrowUp') delta = step;
  if (!delta) return;
  e.preventDefault();
  const el2 = $('r_' + DIM_STEP);
  if (el2){
    const v = parseFloat(el2.value) + delta;
    el2.value = v;
    onSlider(DIM_STEP, parseFloat(el2.value));
  }
});

// ---------- Par manual ----------
async function drawPair(){
  const svg = $('pairSvg');
  if (!svg) return;
  if (!S.chars){ showSVGMessage('pairSvg', 'Sin glifos cargados'); return; }

  const Ls = [...S.chars].filter(c => KSTATE.L.has(c));
  const Rs = [...S.chars].filter(c => KSTATE.R.has(c));
  const k = parseInt($('kvS').value, 10) || 0;

  if (!Ls.length && !Rs.length){
    showSVGMessage('pairSvg', 'Selecciona izquierda y derecha');
    return;
  }

  let maxL = 0, maxR = 0;
  const Litems = [], Ritems = [];
  for (const L of Ls){
    const g = await baseGlyph(L);
    if (!g || !g.contours) continue;
    const a = adjOf(L); const adv = advOf(g, a);
    Litems.push({g, a, adv}); maxL = Math.max(maxL, adv);
  }
  for (const R of Rs){
    const g = await baseGlyph(R);
    if (!g || !g.contours) continue;
    const a = adjOf(R); const adv = advOf(g, a);
    Ritems.push({g, a, adv}); maxR = Math.max(maxR, adv);
  }
  if (!Litems.length && !Ritems.length){
    showSVGMessage('pairSvg', 'Sin glifos para la selección');
    return;
  }

  const offR = maxL + k;
  const totalW = offR + Math.max(maxR, 1);
  const vbW = Math.max(2600, totalW + 400);

  let d = '';
  for (const {g, a} of Litems){
    d += '<path d="'+glyphPaths(g, a, 0)+'" fill="#eee"/>';
  }
  d += '<rect x="0" y="0" width="'+Math.max(maxL,1)+'" height="1000" fill="none" stroke="#555" stroke-dasharray="12 12"/>';
  for (const {g, a} of Ritems){
    d += '<path d="'+glyphPaths(g, a, offR)+'" fill="#f06fc0"/>';
  }
  d += '<rect x="'+offR+'" y="0" width="'+Math.max(maxR,1)+'" height="1000" fill="none" stroke="#555" stroke-dasharray="12 12"/>';

  svg.setAttribute('viewBox', '-200 -200 ' + vbW + ' 1400');
  svg.innerHTML = guides(-200, vbW) + d;
}

async function drawBasePrev(){
  const svg = $('basePrevSvg');
  if (!svg || !$('basePL') || !$('basePR')) return;
  if (!S.chars){ showSVGMessage('basePrevSvg', 'Sin glifos cargados'); return; }

  const PL = $('basePL').value || null;
  const PR = $('basePR').value || null;
  const batch = [...S.chars].filter(c => KB_SEL.has(c));
  const kbStore = (S.status && S.status.kerning_char) || {};
  // Con un único carácter usamos los valores actuales de los inputs
  // (vista previa en vivo). Con varios, lo guardado para el primero del lote.
  const firstBatch = batch[0];
  let baseKern;
  if (batch.length === 1){
    baseKern = {
      l: parseInt($('kbL') ? $('kbL').value : 0, 10) || 0,
      r: parseInt($('kbR') ? $('kbR').value : 0, 10) || 0,
    };
  } else {
    baseKern = firstBatch ? (kbStore[firstBatch] || {l:0, r:0}) : {l:0, r:0};
  }

  let maxBatch = 0;
  const batchItems = [];
  for (const ch of batch){
    const g = await baseGlyph(ch);
    if (!g || !g.contours) continue;
    const a = adjOf(ch);
    const adv = advOf(g, a);
    batchItems.push({g, a, adv, ch});
    maxBatch = Math.max(maxBatch, adv);
  }

  if (!PL && !PR && !batchItems.length){
    showSVGMessage('basePrevSvg', 'Selecciona lote o placeholders');
    return;
  }

  let pen = 0, d = '';

  if (PL){
    const g = await baseGlyph(PL);
    if (g && g.contours){
      const a = adjOf(PL);
      d += '<path d="'+glyphPaths(g, a, pen)+'" fill="none" stroke="#7bd44b" stroke-width="4"/>';
      pen += advOf(g, a);
    }
  }
  pen += baseKern.l;

  const batchX = pen;
  for (const {g, a} of batchItems){
    d += '<path d="'+glyphPaths(g, a, batchX)+'" fill="#eee"/>';
  }
  pen = batchX + Math.max(maxBatch, 1);

  pen += baseKern.r;

  if (PR){
    const g = await baseGlyph(PR);
    if (g && g.contours){
      const a = adjOf(PR);
      d += '<path d="'+glyphPaths(g, a, pen)+'" fill="none" stroke="#7bd44b" stroke-width="4"/>';
      pen += advOf(g, a);
    }
  }

  const vbW = Math.max(2600, pen + 400);
  svg.setAttribute('viewBox', '-200 -200 ' + vbW + ' 1400');
  svg.innerHTML = guides(-200, vbW) + d;
}

function switchKsub(name){
  document.querySelectorAll('.ksubtab').forEach(b => b.classList.toggle('active', b.dataset.ksub === name));
  document.querySelectorAll('#tab-kern .ksub').forEach(s => s.classList.toggle('active', s.id === 'ksub-' + name));
  ensureKerningData();
}

function ensureKerningData(){
  if (!S.chars || !S.chars.length) return;
  if ($('basePL') && !$('basePL').value) fillSelect('basePL', S.chars, false, S.chars.includes('A') ? 'A' : null);
  if ($('basePR') && !$('basePR').value) fillSelect('basePR', S.chars, false, S.chars.includes('V') ? 'V' : null);
  renderBatchGrids();
}

async function loadPairUI(L, R){
  if (!L || !R) return;
  KSTATE.L = new Set([L]);
  KSTATE.R = new Set([R]);
  KSTATE.step = 'value';
  const kbStore = (S.status && S.status.kerning_char) || {};
  const baseL = (kbStore[L] || {}).r || 0;
  const baseR = (kbStore[R] || {}).l || 0;
  const baseTotal = baseL + baseR;
  const saved = (S.status && S.status.kerning || []).find(p => p.left === L && p.right === R);
  const manualOffset = saved ? saved.value : 0;
  const finalVal = baseTotal + manualOffset;
  if ($('kvS')) $('kvS').value = finalVal;
  if ($('kvOut')) $('kvOut').textContent = finalVal;
  setMeter('kvM', finalVal, -600, 600);
  if ($('kvInfo')) $('kvInfo').innerHTML = 'Par: <b>' + L + R + '</b> · Base: <b>' + baseTotal + '</b> · Manual: <b>' + manualOffset + '</b>';
  updateKmStepLabel();
  syncSelectionVisuals();
}

function selectKbRangeInto(set, start, end){
  const charsArr = [...S.chars];
  const min = Math.min(start, end), max = Math.max(start, end);
  set.clear();
  for (let i = min; i <= max; i++) if (charsArr[i]) set.add(charsArr[i]);
}
function selectKbRange(start, end){ selectKbRangeInto(KB_SEL, start, end); }

function renderBatchGrids(){
  const charsArr = [...S.chars];
  document.querySelectorAll('.batchgrid').forEach(grid => {
    grid.innerHTML = '';
    if (!charsArr.length){
      grid.innerHTML = '<span class="muted">Sin glifos cargados</span>';
      return;
    }
    const set = gridSet(grid);
    charsArr.forEach((c, i) => {
      const b = document.createElement('button');
      b.textContent = c;
      b.dataset.idx = i;
      if (set.has(c)) b.classList.add('sel');
      if (i === KB_CURSOR) b.style.outline = '2px solid #7bd44b';
      b.onclick = (e) => {
        const s = gridSet(grid);
        if (e.ctrlKey || e.metaKey){
          s.has(c) ? s.delete(c) : s.add(c);
          KB_CURSOR = i; KB_ANCHOR = i;
        } else if (e.shiftKey){
          selectKbRangeInto(s, KB_ANCHOR, i);
        } else {
          s.clear(); s.add(c);
          KB_CURSOR = i; KB_ANCHOR = i;
        }
        grid.focus();
        syncSelectionVisuals();
      };
      grid.appendChild(b);
    });
  });
  updateKmStepLabel();
  syncSelectionVisuals();
}

function gridSet(grid){
  if (grid.dataset.side === 'base') return KB_SEL;
  return KSTATE.step === 'R' ? KSTATE.R : KSTATE.L;
}

function updateKmStepLabel(){
  const el = $('kmStep');
  if (!el) return;
  if (KSTATE.step === 'L') el.textContent = '1/3 — Selecciona izquierda (Enter para avanzar)';
  else if (KSTATE.step === 'R') el.textContent = '2/3 — Selecciona derecha (Enter para avanzar · doble Enter = mismo carácter) · Esc vuelve';
  else el.textContent = '3/3 — Ajusta separación (←→ ±1 · Shift ±10 · número directo) · Enter guarda · Esc vuelve';
  updateLockUI();
}

function updateLockUI(){
  const lockL = $('lockL'), lockR = $('lockR');
  if (lockL){
    lockL.classList.toggle('on', KSTATE.lockL);
    lockL.textContent = KSTATE.lockL ? '🔒' : '🔓';
    lockL.title = KSTATE.lockL ? 'Izquierda fija (clic o Bloq Mayús para soltar)' : 'Fijar izquierda (clic o Bloq Mayús)';
  }
  if (lockR){
    lockR.classList.toggle('on', KSTATE.lockR);
    lockR.textContent = KSTATE.lockR ? '🔒' : '🔓';
    lockR.title = KSTATE.lockR ? 'Derecha fija (clic o Bloq Mayús para soltar)' : 'Fijar derecha (clic o Bloq Mayús)';
  }
}

function updateKbInputsIfIdle(){
  const activeId = document.activeElement && document.activeElement.id;
  if (activeId === 'kbL' || activeId === 'kbR' || activeId === 'kbBoth') return;
  if (KB_SEL.size === 1){
    const c = [...KB_SEL][0];
    const kc = (S.status && S.status.kerning_char) || {};
    const cd = kc[c] || {l:0, r:0};
    if ($('kbL')) $('kbL').value = cd.l || 0;
    if ($('kbR')) $('kbR').value = cd.r || 0;
    syncKbSliders();
  } else if (KB_SEL.size === 0){
    if ($('kbL')) $('kbL').value = 0;
    if ($('kbR')) $('kbR').value = 0;
    syncKbSliders();
  }
}

function syncKbSliders(){
  if ($('kbLSlider') && $('kbL')) $('kbLSlider').value = parseInt($('kbL').value || 0, 10) || 0;
  if ($('kbRSlider') && $('kbR')) $('kbRSlider').value = parseInt($('kbR').value || 0, 10) || 0;
  if ($('kbLv') && $('kbL')) $('kbLv').textContent = $('kbL').value || 0;
  if ($('kbRv') && $('kbR')) $('kbRv').textContent = $('kbR').value || 0;
}

function syncSelectionVisuals(){
  const dg = $('dimChars');
  if (dg) for (const b of dg.querySelectorAll('button')){
    const c = b.dataset.c;
    b.classList.toggle('sel', c === S.char);
    b.classList.toggle('multi', KB_SEL.has(c) && c !== S.char);
  }
  const activeGrid = document.activeElement && document.activeElement.classList && document.activeElement.classList.contains('batchgrid')
    ? document.activeElement : null;
  const charsArr = [...S.chars];
  document.querySelectorAll('.batchgrid').forEach(grid => {
    const set = gridSet(grid);
    for (const b of grid.querySelectorAll('button')){
      const i = +b.dataset.idx;
      const c = charsArr[i];
      b.classList.toggle('sel', set.has(c));
      b.style.outline = (grid === activeGrid && i === KB_CURSOR) ? '2px solid #7bd44b' : 'none';
    }
  });
  if ($('kbSelCount')) $('kbSelCount').textContent = KB_SEL.size;
  if ($('kbSelPreview')) $('kbSelPreview').textContent = KB_SEL.size ? [...KB_SEL].join(', ') : 'Ninguna';
  updateKbInputsIfIdle();
  updateKmStepLabel();
  drawDim();
  drawPair();
  drawBasePrev();
}

// ---------- Palabras ----------
async function renderWord(){
  if (!$('wordIn') || !$('wordSvg')) return;
  const text = $('wordIn').value || '';
  const useKern = $('wordKern') ? $('wordKern').checked : false;
  const defAdv = (S.status && S.status.metrics && S.status.metrics.default_advance) || 500;
  let pen = 0, prev = null, d = '', missing = 0;
  for (const ch of text){
    if (ch === ' '){ pen += defAdv / 2; prev = null; continue; }
    const g = await baseGlyph(ch);
    if (!g || !g.contours){ missing++; pen += defAdv; prev = null; continue; }
    if (useKern && prev !== null){
      pen += getPairKerning(prev, ch);
    }
    const a = adjOf(ch);
    d += glyphPaths(g, a, pen);
    pen += advOf(g, a);
    prev = ch;
  }
  $('wordSvg').setAttribute('viewBox', '-100 -200 ' + Math.max(400, pen + 200) + ' 1400');
  $('wordSvg').innerHTML = guides(-100, Math.max(400, pen + 200)) +
    '<path d="' + d + '" fill="#eee"/>';
  if ($('wordInfo')) {
    $('wordInfo').textContent = 'Ancho total: ' + Math.round(pen) + ' u' +
      (missing ? ' · sin glifo: ' + missing + ' (espacio por defecto)' : '');
  }
}

// ---------- Tildes ----------
const ACC_CHARS = ['Á','É','Í','Ó','Ú','á','é','í','ó','ú','Ñ','ñ'];
function accSelect(){
  const sel = $('accSel');
  if (!sel) return;
  sel.innerHTML = '';
  const o0 = document.createElement('option'); o0.value = '*'; o0.textContent = 'Todas las tildes'; sel.appendChild(o0);
  for (const c of ACC_CHARS){ const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o); }
}
function accValues(){
  const key = $('accSel') ? $('accSel').value : '*';
  const store = (S.status && S.status.accent_adjust) || {};
  const g = store['*'] || {}, p = store[key] || {};
  const get = (k, d) => (p[k] !== undefined ? p[k] : (g[k] !== undefined && key !== '*' ? g[k] : d));
  return {dx: get('dx', 0), dy: get('dy', 0), s: get('s', 1)};
}
function accShow(){
  const v = accValues();
  if ($('accX')) { $('accX').value = v.dx; $('accXv').textContent = Math.round(v.dx); }
  if ($('accY')) { $('accY').value = v.dy; $('accYv').textContent = Math.round(v.dy); }
  if ($('accS')) { $('accS').value = Math.round(v.s * 100); $('accSv').textContent = Math.round(v.s * 100) + '%'; }
  if ($('accInfo')) {
    $('accInfo').textContent = $('accSel').value === '*' ? 'Ajuste general de todas las tildes.' :
      'Ajuste de ' + $('accSel').value + ' (prevalece sobre el general).';
  }
  accPreview();
}
async function accPreview(){
  if (!$('accSvg') || !$('accSel')) return;
  const c = $('accSel').value === '*' ? 'Á' : $('accSel').value;
  delete S.cache[c];
  const g = await baseGlyph(c);
  if (!g || !g.contours){ showSVGMessage('accSvg', 'Sin glifo ' + c); return; }
  $('accSvg').innerHTML = guides(-300, 1400) +
    '<path d="' + glyphPaths(g, {sx:1, sy:1, dy:0, rot:0}, 0) + '" fill="#eee"/>';
}
async function accSave(){
  const v = {char: $('accSel').value, dx: parseFloat($('accX').value), dy: parseFloat($('accY').value),
             s: parseFloat($('accS').value) / 100};
  await api('/api/accent', v);
  await loadStatus(); accShow();
}

// ---------- Categorías ----------
const CAT_NAMES = {mayusculas:'Mayúsculas', minusculas:'Minúsculas', numeros:'Números', puntuacion:'Puntuación', especiales:'Especiales', tildes:'Tildes'};
const CAT_TEST = {
  mayusculas: c => /^[A-Z]$/.test(c), minusculas: c => /^[a-z]$/.test(c), numeros: c => /^[0-9]$/.test(c),
  puntuacion: c => '"' + ',.!¡¿?:;()´'.includes(c), especiales: c => "{}-_–—&%$#@*+=/\\|~^<>[]'°«»".includes(c),
  tildes: c => 'ÁÉÍÓÚáéíóúÑñ'.includes(c)
};
function catChars(cat){ return [...S.chars].filter(c => cat === 'todas' ? true : CAT_TEST[cat](c)); }
function catButtons(containerId, onPick){
  const box = $(containerId);
  if (!box) return;
  box.innerHTML = '';
  for (const k of Object.keys(CAT_NAMES).concat(['todas'])){
    const b = document.createElement('button'); b.className = 'btn sec'; b.style.padding = '.2em .5em';
    b.textContent = k === 'todas' ? 'Todas' : CAT_NAMES[k];
    b.onclick = () => onPick(k);
    box.appendChild(b);
  }
  const n = document.createElement('button'); n.className = 'btn sec'; n.style.padding = '.2em .5em';
  n.textContent = 'Ninguna'; n.onclick = () => onPick('ninguna'); box.appendChild(n);
}
function dimPickCat(k){
  KB_SEL.clear();
  if (k !== 'ninguna') for (const c of catChars(k)) KB_SEL.add(c);
  if (S.char) KB_SEL.add(S.char);
  syncSelectionVisuals();
}

// ---------- Tabla kerning manual ----------
function renderKerningTable(){
  const tb = $('kerntable'); if (!tb) return;
  tb.innerHTML = '';
  const manualList = (S.status && S.status.kerning) || [];
  for (const p of manualList){
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td><input type="checkbox" class="kernrow" data-l="'+p.left+'" data-r="'+p.right+'"></td>' +
      '<td>'+p.left+'</td><td>'+p.right+'</td><td>'+p.value+'</td><td class="muted">manual</td>' +
      '<td><button class="btn sec">Eliminar</button></td>';
    tr.onclick = (e) => {
      if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON'){
        KB_SEL.clear(); KB_SEL.add(p.left);
        loadPairUI(p.left, p.right);
        syncSelectionVisuals();
      }
    };
    tr.querySelector('button').onclick = async (e) => {
      e.stopPropagation();
      await api('/api/kerning/delete', {left:p.left, right:p.right});
      await loadStatus();
    };
    tb.appendChild(tr);
  }
}

// ---------- Estado ----------
async function loadStatus(){
  let s;
  try { s = await api('/api/status'); } catch (e) { return; }
  S.status = s;
  if (Date.now() > S.busyUntil) S.adj = s.adjust || {};
  if ($('navcount')) {
    const j = s.job || {};
    const bar = $('jobBar');
    if (j.active){
      bar.style.display = '';
      const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
      $('jobTxt').textContent = (j.name ? j.name + ' · ' : '') + j.stage + ' · ' + pct + '% · ' + j.elapsed + ' s';
      $('jobFill').style.width = pct + '%';
    } else if (j.since_end !== null && j.since_end !== undefined && j.since_end < 4){
      bar.style.display = '';
      $('jobTxt').textContent = j.stage + ' (' + j.elapsed + ' s)';
      $('jobFill').style.width = '100%';
    } else {
      bar.style.display = 'none';
    }
    $('navcount').innerHTML = s.glyphs + ' glifos · ' + s.kerning.length + ' pares manuales<br><br>' +
      'Vigilando:<br><span style="font-size:.8em">' + s.watch.inbox + '</span><br>' +
      'Revisión: ' + s.watch.last_scan + ' · pendientes: ' + s.watch.pending +
      (s.watch.errors ? ' · errores: ' + s.watch.errors : '');
  }
  if ($('log')) $('log').textContent = s.log.join('\n');
  if ($('out')) $('out').textContent = s.last_output ? 'Última fuente: ' + s.last_output : '';
  for (const k of ['upper','lower','digits','punct']) {
    if ($('cs_'+k)) $('cs_'+k).checked = s.charsets[k];
  }

  const changed = (S.version !== s.version) || (S.chars !== s.all_chars);
  if (changed){
    S.version = s.version;
    S.chars = s.all_chars;
    clearGlyphCache();
    renderCharGrid();
    fillSelect('basePL', S.chars, false, S.chars.includes('A') ? 'A' : null);
    fillSelect('basePR', S.chars, false, S.chars.includes('V') ? 'V' : null);
    renderBatchGrids();
    if (!S.char && S.chars) selectChar(S.chars[0]);
    catButtons('dimCats', dimPickCat);
    renderCompare();
    fillTraceUI();
    drawDim(); drawPair(); drawBasePrev();
  }
  renderKerningTable();
  if (document.querySelector('nav button[data-tab="words"].active')) renderWord();
  if ($('family') && !$('family').value){ $('family').value = s.family; $('style').value = s.style; }
}

// ---------- Kerning: teclado ----------
const K = {mode: 'select', slot: 'R', cursor: 0, saved: 0, buf: null};
function kernModeLabel(){
  const t = {
    select: 'Letras · escribe una letra · ←→ lado · ⇥ intercambiar · ↓ cuadrícula · Enter kerning',
    grid: 'Cuadrícula · flechas navegan · letra salta · Enter elige · Esc vuelve',
    kern: 'Kerning · ←→ ±1 (Shift ±10) · escribe número · Enter guarda · ↑ cancela'
  };
  if ($('kernMode')) $('kernMode').textContent = t[K.mode];
}
function kernPaint(){
  const grid = $('kernGrid');
  if (grid) {
    grid.style.display = K.mode === 'grid' ? '' : 'none';
    if (K.mode === 'grid'){
      grid.innerHTML = '';
      [...S.chars].forEach((c, i) => {
        const b = document.createElement('button'); b.textContent = c;
        if (i === K.cursor) b.classList.add('sel');
        b.onclick = () => { K.cursor = i; kernEnter(); };
        grid.appendChild(b);
      });
      const cur = grid.children[K.cursor];
      if (cur && cur.scrollIntoView) cur.scrollIntoView({block: 'nearest'});
    }
  }
  kernModeLabel();
}
function kernSetValue(v){
  v = Math.max(-600, Math.min(600, Math.round(v)));
  if ($('kvS')) $('kvS').value = v;
  if ($('kvOut')) $('kvOut').textContent = v;
  setMeter('kvM', v, -600, 600);
  drawPair();
}
async function kernSave(){
  await savePair();
}

async function savePair(){
  const k = parseInt($('kvS').value, 10) || 0;
  const Ls = [...S.chars].filter(c => KSTATE.L.has(c));
  const Rs = [...S.chars].filter(c => KSTATE.R.has(c));
  if (!Ls.length || !Rs.length) return;
  for (const L of Ls){
    for (const R of Rs){
      await api('/api/kerning/set', {left:L, right:R, value:k});
    }
  }
  await loadStatus();
  // Ciclo dependiente de los candados:
  //  - L fijo, R libre  -> conservar L, limpiar R, volver a R
  //  - R fijo, L libre  -> conservar R, limpiar L, volver a L
  //  - ninguno fijo     -> limpiar ambos, volver a L
  //  - ambos fijos      -> no puede pasar (la UI lo impide)
  if (KSTATE.lockL && !KSTATE.lockR){
    KSTATE.step = 'R';
    KSTATE.R.clear();
  } else if (KSTATE.lockR && !KSTATE.lockL){
    KSTATE.step = 'L';
    KSTATE.L.clear();
  } else {
    KSTATE.step = 'L';
    KSTATE.L.clear();
    KSTATE.R.clear();
  }
  updateKmStepLabel();
  syncSelectionVisuals();
}

document.addEventListener('keydown', e => {
  if (!document.querySelector('nav button[data-tab="kern"].active')) return;
  const activeSub = document.querySelector('.ksubtab.active');
  if (!activeSub) return;
  const el = document.activeElement;
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
             || (el.classList && el.classList.contains('batchgrid')))) return;

  // Bloq Mayús: toggle del candado del paso actual (solo manual).
  if (activeSub.dataset.ksub === 'pair' && e.key === 'CapsLock'){
    e.preventDefault();
    if (KSTATE.step === 'L' && !KSTATE.lockR){
      KSTATE.lockL = !KSTATE.lockL;
      updateLockUI();
    } else if (KSTATE.step === 'R' && !KSTATE.lockL){
      KSTATE.lockR = !KSTATE.lockR;
      updateLockUI();
    }
    return;
  }

  if (activeSub.dataset.ksub === 'base'){
    if (e.key === 'Escape'){ e.preventDefault(); KB_SEL.clear(); syncSelectionVisuals(); }
    return;
  }

  if (e.key === 'Escape'){
    e.preventDefault();
    if (KSTATE.step === 'value'){ KSTATE.step = 'R'; }
    else if (KSTATE.step === 'R'){ KSTATE.step = 'L'; KSTATE.R.clear(); }
    else { KSTATE.L.clear(); KSTATE.R.clear(); }
    updateKmStepLabel();
    syncSelectionVisuals();
    return;
  }

  if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey){
    e.preventDefault();
    if (KSTATE.step === 'L' && KSTATE.L.size > 0){ KSTATE.step = 'R'; }
    else if (KSTATE.step === 'R' && KSTATE.R.size > 0){ KSTATE.step = 'value'; }
    else if (KSTATE.step === 'value'){ kernSave(); return; }
    updateKmStepLabel();
    syncSelectionVisuals();
    return;
  }

  if (KSTATE.step === 'value'){
    const cur = parseInt($('kvS').value, 10) || 0;
    const stp = e.shiftKey ? 10 : 1;
    if (e.key === 'ArrowLeft'){ kernSetValue(cur - stp); e.preventDefault(); return; }
    if (e.key === 'ArrowRight'){ kernSetValue(cur + stp); e.preventDefault(); return; }
    if (/^[0-9]$/.test(e.key) || e.key === '-'){
      K.buf = ((K.buf === null) ? '' : K.buf) + e.key;
      if (K.buf === '-') { e.preventDefault(); return; }
      const v = parseInt(K.buf, 10);
      if (!isNaN(v)) kernSetValue(v);
      e.preventDefault(); return;
    }
    if (e.key === 'Backspace' && K.buf !== null){
      K.buf = K.buf.slice(0, -1) || null;
      if (K.buf && K.buf !== '-') kernSetValue(parseInt(K.buf, 10));
      e.preventDefault(); return;
    }
  }
});

document.querySelectorAll('.batchgrid').forEach(grid => {
  grid.addEventListener('keydown', e => {
    const charsArr = [...S.chars];
    if (!charsArr.length) return;
    const k = e.key;
    const isBase = grid.dataset.side === 'base';
    const set = gridSet(grid);

    // Paso separación (solo manual): flechas y números ajustan el valor
    if (!isBase && KSTATE.step === 'value'){
      const cur = parseInt($('kvS').value, 10) || 0;
      const stp = e.shiftKey ? 10 : 1;
      if (k === 'ArrowLeft' || k === 'ArrowDown'){ kernSetValue(cur - stp); e.preventDefault(); return; }
      if (k === 'ArrowRight' || k === 'ArrowUp'){ kernSetValue(cur + stp); e.preventDefault(); return; }
      if (/^[0-9]$/.test(k) || k === '-'){
        K.buf = ((K.buf === null) ? '' : K.buf) + k;
        if (K.buf === '-') { e.preventDefault(); return; }
        const v = parseInt(K.buf, 10);
        if (!isNaN(v)) kernSetValue(v);
        e.preventDefault(); return;
      }
      if (k === 'Backspace' && K.buf !== null){
        K.buf = K.buf.slice(0, -1) || null;
        if (K.buf && K.buf !== '-') kernSetValue(parseInt(K.buf, 10));
        e.preventDefault(); return;
      }
      if (k === 'Enter'){ kernSave(); e.preventDefault(); return; }
      if (k === 'Escape'){
        KSTATE.step = 'R';
        updateKmStepLabel();
        syncSelectionVisuals();
        e.preventDefault();
        return;
      }
      e.preventDefault();
      return;
    }

    // Shift+Tab: intercambiar placeholders (solo base)
    if (isBase && e.shiftKey && k === 'Tab'){
      e.preventDefault();
      const l = $('basePL').value, r = $('basePR').value;
      $('basePL').value = r; $('basePR').value = l;
      drawBasePrev();
      return;
    }

    // Esc: vaciar el lote activo
    if (k === 'Escape'){
      e.preventDefault();
      set.clear();
      syncSelectionVisuals();
      return;
    }

    // Flechas: navegar geométricamente
    if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(k)){
      e.preventDefault();
      const btns = [...grid.querySelectorAll('button')];
      if (!btns.length) return;
      const dir = {ArrowLeft:'left', ArrowRight:'right', ArrowUp:'up', ArrowDown:'down'}[k];
      const next = findNeighbor(btns, KB_CURSOR, dir);
      if (next < 0) return;
      const prev = KB_CURSOR;
      KB_CURSOR = next;
      if (e.shiftKey){
        set.add(charsArr[prev]);
        set.add(charsArr[next]);
      } else if (!e.ctrlKey && !e.metaKey){
        set.clear();
        set.add(charsArr[next]);
      }
      syncSelectionVisuals();
      const cur = btns[KB_CURSOR];
      if (cur && cur.scrollIntoView) cur.scrollIntoView({block:'nearest'});
      return;
    }

    // Enter: avanzar el flujo / doble Enter
    if (k === 'Enter' && !e.ctrlKey && !e.metaKey){
      e.preventDefault();
      if (isBase){
        if ($('kbL')){ $('kbL').focus(); $('kbL').select(); }
      } else {
        if (KSTATE.step === 'L'){
          if (KSTATE.L.size > 0) KSTATE.step = 'R';
        } else if (KSTATE.step === 'R'){
          if (KSTATE.R.size === 0 && KSTATE.L.size === 1){
            KSTATE.R = new Set(KSTATE.L);
            KSTATE.step = 'value';
          } else if (KSTATE.R.size > 0){
            KSTATE.step = 'value';
          }
        }
        updateKmStepLabel();
        syncSelectionVisuals();
      }
      return;
    }

    // Ctrl+Enter: toggle del carácter con foco
    if (e.ctrlKey && k === 'Enter'){
      e.preventDefault();
      const c = charsArr[KB_CURSOR];
      if (c){ set.has(c) ? set.delete(c) : set.add(c); }
      syncSelectionVisuals();
      return;
    }

    // Letras: navegan y seleccionan
    if (k.length === 1 && charsArr.includes(k)){
      e.preventDefault();
      const idx = charsArr.indexOf(k);
      KB_CURSOR = idx;
      if (e.ctrlKey || e.metaKey) set.has(k) ? set.delete(k) : set.add(k);
      else if (e.shiftKey) selectKbRangeInto(set, KB_ANCHOR, KB_CURSOR);
      else { KB_ANCHOR = idx; set.clear(); set.add(k); }
      syncSelectionVisuals();
      const cur = grid.children[KB_CURSOR];
      if (cur && cur.scrollIntoView) cur.scrollIntoView({block:'nearest'});
      return;
    }
  });
});

if ($('kbL')) $('kbL').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); if ($('kbR')) { $('kbR').focus(); $('kbR').select(); } } });
if ($('kbR')) $('kbR').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); if ($('kbApply')) $('kbApply').click(); } });

// ---------- Eventos ----------
document.querySelectorAll('.ksubtab').forEach(b => b.onclick = () => switchKsub(b.dataset.ksub));

if ($('recomposeBtn')) $('recomposeBtn').onclick = async () => {
  await api('/api/recompose', {});
  clearGlyphCache();
  S.version = -1;
  await loadStatus();
};

if ($('baseSwapPL')) $('baseSwapPL').onclick = () => {
  const l = $('basePL').value, r = $('basePR').value;
  $('basePL').value = r; $('basePR').value = l;
  drawBasePrev();
};
if ($('basePL')) $('basePL').onchange = drawBasePrev;
if ($('basePR')) $('basePR').onchange = drawBasePrev;

// ---------- Candados manual ----------
if ($('lockL')) $('lockL').onclick = () => {
  KSTATE.lockL = !KSTATE.lockL;
  if (KSTATE.lockL) KSTATE.lockR = false;
  updateLockUI();
};
if ($('lockR')) $('lockR').onclick = () => {
  KSTATE.lockR = !KSTATE.lockR;
  if (KSTATE.lockR) KSTATE.lockL = false;
  updateLockUI();
};

// ---------- Sliders de kerning base ----------
function kbSliderSet(which, value){
  value = Math.max(-600, Math.min(600, Math.round(value)));
  if (which === 'L' || which === 'both'){ if ($('kbL')) $('kbL').value = value; if ($('kbLSlider')) $('kbLSlider').value = value; if ($('kbLv')) $('kbLv').textContent = value; }
  if (which === 'R' || which === 'both'){ if ($('kbR')) $('kbR').value = value; if ($('kbRSlider')) $('kbRSlider').value = value; if ($('kbRv')) $('kbRv').textContent = value; }
  drawBasePrev();
}
if ($('kbLSlider')) $('kbLSlider').oninput = (e) => kbSliderSet('L', parseFloat(e.target.value));
if ($('kbRSlider')) $('kbRSlider').oninput = (e) => kbSliderSet('R', parseFloat(e.target.value));
if ($('kbBothSlider')) $('kbBothSlider').oninput = (e) => {
  const v = Math.round(parseFloat(e.target.value));
  if ($('kbBothv')) $('kbBothv').textContent = v;
  kbSliderSet('both', v);
};
if ($('kbL')) $('kbL').oninput = (e) => kbSliderSet('L', parseFloat(e.target.value) || 0);
if ($('kbR')) $('kbR').oninput = (e) => kbSliderSet('R', parseFloat(e.target.value) || 0);
if ($('kbBoth')) $('kbBoth').oninput = (e) => {
  const v = parseFloat(e.target.value);
  if (!isNaN(v)) kbSliderSet('both', v);
};

if ($('kbApply')) $('kbApply').onclick = async () => {
  if (!KB_SEL.size) return alert('Selecciona al menos un carácter para el lote.');
  await api('/api/kerning/char', {
    chars: [...KB_SEL],
    l: parseInt($('kbL').value || 0, 10),
    r: parseInt($('kbR').value || 0, 10)
  });
  if ($('kbBoth')) $('kbBoth').value = '';
  await loadStatus();
};
if ($('kbDelete')) $('kbDelete').onclick = async () => {
  if (!KB_SEL.size) return alert('Selecciona al menos un carácter para el lote.');
  await api('/api/kerning/char', {chars: [...KB_SEL], l: 0, r: 0});
  await loadStatus();
};

if ($('kernChkAll')) $('kernChkAll').onchange = (e) => {
  document.querySelectorAll('.kernrow').forEach(c => c.checked = e.target.checked);
};
if ($('kernSelAll')) $('kernSelAll').onclick = () => {
  document.querySelectorAll('.kernrow').forEach(c => c.checked = true);
};
if ($('kernSelNone')) $('kernSelNone').onclick = () => {
  document.querySelectorAll('.kernrow').forEach(c => c.checked = false);
};
if ($('kernDelSel')) $('kernDelSel').onclick = async () => {
  const rows = [...document.querySelectorAll('.kernrow')].filter(c => c.checked);
  if (!rows.length) return;
  for (const r of rows){
    await api('/api/kerning/delete', {left: r.dataset.l, right: r.dataset.r});
  }
  await loadStatus();
};

document.querySelectorAll('nav button[data-tab]').forEach(btn => btn.onclick = () => {
  document.querySelectorAll('nav button[data-tab]').forEach(b => b.classList.toggle('active', b === btn));
  document.querySelectorAll('section').forEach(sec => sec.classList.toggle('active', sec.id === 'tab-' + btn.dataset.tab));
  if (btn.dataset.tab === 'kern'){ ensureKerningData(); drawPair(); drawBasePrev(); }
  if (btn.dataset.tab === 'dim'){ drawDim(); }
  if (btn.dataset.tab === 'words') renderWord();
  if (btn.dataset.tab === 'imp'){ impRefresh(); }
});

if ($('reloadBtn')) $('reloadBtn').onclick = async () => {
  clearGlyphCache();
  S.version = -1;
  await loadStatus();
};

if ($('debugBtn')) $('debugBtn').onclick = async () => {
  if (!S.char){ alert('Seleccioná un carácter primero'); return; }
  const r = await api('/api/debug_cell?c=' + encodeURIComponent(S.char));
  if (r && r.error){ alert('Error: ' + r.error); return; }
  console.log('Diagnóstico', r);
  alert('Carácter ' + r.char + ' (fila ' + r.row + ', col ' + r.col + ')\n' +
        'max ' + r.cov_max + ' · mean ' + r.cov_mean + ' · ink ' + r.ink_pixels + ' px\n' +
        'geom empty: ' + r.geom_empty + '\n' +
        'settings: ' + JSON.stringify(r.settings) + '\n\n' +
        'Archivos en output/debug/:\n  ' + r.files.cell + '\n  ' + r.files.mask + '\n  ' + r.files.trace_svg);
};

bindTraceSliders();
if ($('traceDefaults')) $('traceDefaults').onclick = async () => {
  await api('/api/trace', {blur: 0.5, alphamax: 0.4, threshold: 0.5, turdsize: 20, opttolerance: 0.1});
  await loadStatus();
};
if ($('retraceBtn')) $('retraceBtn').onclick = async () => {
  const r = await api('/api/retrace', {});
  if (r && r.error) alert('Error: ' + r.error);
  await loadStatus();
};

buildSliders();
if ($('lockChk')) $('lockChk').onchange = e => setLock(e.target.checked);
if ($('resetRatio')) $('resetRatio').onclick = resetRatio;
if ($('resetRot')) $('resetRot').onclick = resetRot;
if ($('charSearch')) $('charSearch').oninput = renderCharGrid;
if ($('cmpAdd')) $('cmpAdd').onclick = () => addToCompare(S.char);
if ($('cmpBase')) $('cmpBase').onchange = () => { CMP.base = $('cmpBase').value || null; drawDim(); };
if ($('kvS')) {
  $('kvS').onchange = savePair;
  $('kvS').oninput = () => { S.busyUntil = Date.now() + 1500; $('kvOut').textContent = $('kvS').value; setMeter('kvM', $('kvS').value, -600, 600); drawPair(); };
}
if ($('kvSave')) $('kvSave').onclick = () => kernSave();

kernPaint();
updateLockUI();
syncKbSliders();
if ($('wordIn')) $('wordIn').oninput = renderWord;
if ($('accSel')) $('accSel').onchange = accShow;
['accX','accY','accS'].forEach(id => {
  if ($(id)) {
    $(id).oninput = () => {
      if ($('accXv')) $('accXv').textContent = $('accX').value;
      if ($('accYv')) $('accYv').textContent = $('accY').value;
      if ($('accSv')) $('accSv').textContent = $('accS').value + '%';
    };
    $(id).onchange = accSave;
  }
});
if ($('accReset')) $('accReset').onclick = async () => { await api('/api/accent', {char: $('accSel').value, dx: 0, dy: 0, s: 1}); await loadStatus(); accShow(); };
accSelect();
if ($('wordKern')) $('wordKern').onchange = renderWord;
for (const k of ['upper','lower','digits','punct']) {
  if ($('cs_'+k)) {
    $('cs_'+k).onchange = () => {
      const b = {};
      for (const j of ['upper','lower','digits','punct']) b[j] = $('cs_'+j).checked;
      api('/api/charsets', b).then(loadStatus);
    };
  }
}
if ($('build')) {
  $('build').onclick = async () => {
    await api('/api/build', {family:$('family').value, style:$('style').value}); loadStatus();
  };
}
loadStatus(); setInterval(loadStatus, 1000);
</script>
<script>
/* =====================================================================
   IMPORTACIONES
   ---------------------------------------------------------------------
   Elige archivos desde la app (diálogo nativo del sistema), explica el
   formato de la rejilla y muestra el estado de las carpetas vigiladas.
   ===================================================================== */

function impMsg(html, tipo){
  const box = $('impResultado');
  if (!box) return;
  const color = tipo === 'error' ? 'var(--accent)' : (tipo === 'ok' ? 'var(--ok)' : 'var(--muted)');
  box.innerHTML = '<p style="color:' + color + ';margin:.5em 0 0">' + html + '</p>';
}

async function impImportar(rutas){
  if (!rutas || !rutas.length){ impMsg('No se eligió ningún archivo.', 'muted'); return; }
  const zona = $('impZona');
  const rotulo = zona ? zona.querySelector('.grande') : null;
  if (zona) zona.style.opacity = '.6';
  if (rotulo) rotulo.textContent = 'Importando…';
  impMsg('Importando ' + rutas.length + ' archivo(s). El trazado puede tardar…', 'muted');
  try {
    const r = await api('/api/import/files', {rutas: rutas});
    if (r && r.error){ impMsg('Error: ' + r.error, 'error'); return; }
    const res = (r && r.resultados) || [];
    const ok = res.filter(x => x.ok);
    const mal = res.filter(x => !x.ok);
    let html = '';
    if (ok.length){
      html += '<b style="color:var(--ok)">Importados ' + ok.length + ':</b> ' +
        ok.map(x => x.archivo + ' (' + x.glifos + ' glifos)').join(', ') + '. ';
    }
    if (mal.length){
      html += '<br><b style="color:var(--accent)">Fallaron ' + mal.length + ':</b> ' +
        mal.map(x => x.archivo + ' — ' + x.motivo).join('; ') + '.';
    }
    impMsg(html || 'Sin resultados.', ok.length ? 'ok' : 'error');
  } catch (e){
    impMsg('Error inesperado: ' + e.message, 'error');
  } finally {
    if (zona) zona.style.opacity = '';
    if (rotulo) rotulo.textContent = 'Elegir archivo…';
    impRefresh();
    loadStatus();
  }
}

async function impElegir(){
  const zona = $('impZona');
  const rotulo = zona ? zona.querySelector('.grande') : null;
  if (rotulo) rotulo.textContent = 'Esperando el diálogo…';
  try {
    const r = await api('/api/import/dialog', {});
    if (r && r.error){ impMsg('No se pudo abrir el diálogo: ' + r.error, 'error'); return; }
    const rutas = (r && r.rutas) || [];
    if (!rutas.length){ impMsg('Cancelaste la elección (o el diálogo no está disponible).', 'muted'); return; }
    await impImportar(rutas);
  } catch (e){
    impMsg('Error abriendo el diálogo: ' + e.message, 'error');
  } finally {
    if (rotulo) rotulo.textContent = 'Elegir archivo…';
  }
}

function impFormatoHTML(f, modo, base){
  if (!f) return '';
  const filas = f.filas;
  return '<table style="font-size:.92em"><tbody>' +
    '<tr><td>Cuadrícula</td><td><b>' + f.columnas + ' columnas × ' + filas + ' filas</b> ' +
      '(' + f.caracteres + ' caracteres)</td></tr>' +
    '<tr><td>Tamaño de celda</td><td><b>' + f.celda + ' × ' + f.celda + ' px</b></td></tr>' +
    '<tr><td>Ancho total del render</td><td><b>' + (f.columnas * f.celda) + ' px</b> ' +
      '<span class="muted">(en PNG, 600 ppp)</span></td></tr>' +
    '<tr><td>Línea base</td><td><b>' + f.linea_base + ' px</b> desde el borde superior de cada celda</td></tr>' +
    '<tr><td>Avance por defecto</td><td>' + f.avance_defecto + ' unidades (UPM ' + f.upm + ')</td></tr>' +
    '</tbody></table>' +
    '<p class="muted" style="margin:.5em 0 0">Dónde guarda los datos esta instalación: <b>' +
      (base || '') + '</b> (' + (modo === 'usuario' ? 'carpeta de datos del usuario' : 'carpeta de la app') + ').</p>';
}

function impOrdenHTML(orden){
  if (!orden) return '';
  let html = '<table style="font-size:.85em"><thead><tr><th>#</th><th>Fila</th><th>Col</th>' +
             '<th>Carácter</th><th>Esquina (x, y)</th></tr></thead><tbody>';
  for (const fila of orden){
    for (const c of fila){
      const esc = (c.char === '<' ? '&lt;' : c.char === '>' ? '&gt;' : c.char === '&' ? '&amp;' : c.char);
      html += '<tr><td>' + c.i + '</td><td>' + c.fila + '</td><td>' + c.col + '</td>' +
              '<td style="font-size:1.3em">' + esc + '</td>' +
              '<td class="muted">' + c.x + ', ' + c.y + '</td></tr>';
    }
  }
  return html + '</tbody></table>';
}

function impCarpetasHTML(carpetas){
  if (!carpetas || !carpetas.length) return '<p class="muted">Sin carpetas configuradas.</p>';
  let html = '';
  for (const c of carpetas){
    const pend = c.pendientes.length, proc = c.procesado.length, err = c.errores.length;
    html += '<div style="margin-bottom:.8em"><code style="font-size:.85em">' + c.ruta + '</code><br>' +
      '<span class="muted">' + pend + ' pendiente(s) · ' + proc + ' procesado(s) · ' +
      (err ? '<b style="color:var(--accent)">' + err + ' con error</b>' : '0 con error') + '</span>';
    if (pend) html += '<br><span class="muted">En espera: ' + c.pendientes.join(', ') + '</span>';
    if (err) html += '<br><span style="color:var(--accent);font-size:.9em">Con error: ' +
      c.errores.join(', ') + '</span>';
    html += '</div>';
  }
  return html;
}

async function impRefresh(){
  try {
    const r = await api('/api/import/status');
    if (!r || r.error) return;
    if ($('impModo')) $('impModo').textContent = '(' + r.datos + ')';
    if ($('impFormato')) $('impFormato').innerHTML = impFormatoHTML(r.formato, r.modo, r.base_dir);
    if ($('impOrden')) $('impOrden').innerHTML = impOrdenHTML(r.orden);
    if ($('impCarpetas')) $('impCarpetas').innerHTML = impCarpetasHTML(r.carpetas);
    if ($('impPickHint')){
      $('impPickHint').textContent = r.dialogo
        ? 'Se abre el diálogo de archivos de ' + r.plataforma + '. Podés elegir varios a la vez.'
        : 'Este sistema no tiene diálogo de archivos disponible: copiá el archivo dentro de la carpeta inbox y usá "Re-escanear inbox".';
    }
  } catch (e) { /* silencioso: no romper la interfaz por un fallo de red */ }
}


if ($('impZona')){
  $('impZona').onclick = impElegir;
  $('impZona').onkeydown = e => { if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); impElegir(); } };
}
if ($('impRefresh')) $('impRefresh').onclick = impRefresh;
if ($('impTutorial')) $('impTutorial').onclick = () => tourReplay();
document.querySelectorAll('#impAccesos .acceso').forEach(b => {
  b.onclick = () => { const t = b.dataset.ir; const nav = document.querySelector('nav button[data-tab="' + t + '"]'); if (nav) nav.click(); };
});
if ($('impRescan')) $('impRescan').onclick = async () => {
  const b = $('impRescan'); b.disabled = true; b.textContent = 'Escaneando…';
  try {
    const r = await api('/api/import/rescan', {});
    impMsg(r && r.importado ? 'Se importó lo que había pendiente en inbox.' : 'No había nada nuevo en inbox.', 'ok');
  } catch (e){ impMsg('Error: ' + e.message, 'error'); }
  b.disabled = false; b.textContent = 'Re-escanear inbox';
  impRefresh(); loadStatus();
};
for (const [id, donde] of [['impClearErr','errores'], ['impClearProc','procesado']]){
  if ($(id)) $(id).onclick = async () => {
    const r = await api('/api/import/clear', {donde: donde});
    impMsg(r && r.ok ? ('Se borraron ' + r.borrados + ' archivo(s) de ' + donde + '.') : 'No se pudo limpiar.', 'ok');
    impRefresh();
  };
}

/* Importaciones es la pantalla de inicio, así que se carga sola al abrir. */
impRefresh();

</script>
<script>
/* =====================================================================
   ACTUALIZACIONES
   ---------------------------------------------------------------------
   Consulta la última release publicada en el repositorio y, si hay una
   versión más nueva, ofrece el enlace de descarga. También muestra un
   aviso discreto al abrir la app.
   ===================================================================== */

function updMostrar(info){
  if ($('verActual')) $('verActual').textContent = info.actual || '?';
  const estado = $('updEstado');
  const descargar = $('updDescargar');
  if (!estado) return;

  if (info.error){
    estado.textContent = info.error;
    if (descargar) descargar.style.display = 'none';
    return;
  }
  if (info.disponible){
    estado.innerHTML = 'Hay una versión nueva: <b>' + info.nueva + '</b>' +
      (info.publicada ? ' (' + info.publicada + ')' : '') + '. Estás usando la ' + info.actual + '.';
    if (descargar){ descargar.style.display = 'inline-block'; descargar.href = info.descarga; }
    if (info.notas && $('updNotas') && $('updNotasTxt')){
      $('updNotasTxt').textContent = info.notas;
      $('updNotas').style.display = 'block';
    }
  } else {
    estado.textContent = 'Estás al día (versión ' + info.actual + ').';
    if (descargar) descargar.style.display = 'none';
    if ($('updNotas')) $('updNotas').style.display = 'none';
  }
}

async function updBuscar(manual){
  const btn = $('updBuscar');
  if (btn){ btn.disabled = true; btn.textContent = manual ? 'Buscando…' : 'Comprobando…'; }
  if (manual && $('updEstado')) $('updEstado').textContent = 'Consultando el repositorio…';
  try {
    const info = await api('/api/update/check');
    if (info && !info.__err) updMostrar(info);
    if (manual && info && info.__err && $('updEstado')) $('updEstado').textContent = 'No se pudo consultar.';
  } catch (e){
    if (manual && $('updEstado')) $('updEstado').textContent = 'No se pudo consultar el repositorio.';
  } finally {
    if (btn){ btn.disabled = false; btn.textContent = 'Buscar actualizaciones'; }
  }
}

function updAviso(info){
  const b = $('updBanner');
  if (!b || !info || !info.disponible) return;
  if (localStorage.getItem('fontiador_upd_oculto') === String(info.nueva)) return;  // ya lo ocultó
  if ($('updBannerTxt')){
    $('updBannerTxt').innerHTML = 'Hay una versión nueva de Fontiador: <b>' + info.nueva +
      '</b> (tenés la ' + info.actual + '). ' +
      '<a href="' + info.descarga + '" target="_blank" rel="noopener">Ver la descarga</a>';
  }
  b.classList.add('on');
  if ($('updBannerClose')) $('updBannerClose').onclick = () => {
    b.classList.remove('on');
    try { localStorage.setItem('fontiador_upd_oculto', String(info.nueva)); } catch (e) {}
  };
}

(function updInit(){
  const btn = $('updBuscar');
  if (btn) btn.onclick = () => updBuscar(true);
  /* Comprobación silenciosa al abrir: si no hay internet, no molesta a nadie. */
  setTimeout(async () => {
    try {
      const info = await api('/api/update/check');
      if (info && !info.__err){ updMostrar(info); updAviso(info); }
    } catch (e) {}
  }, 2500);
})();
</script>
<script>
/* =====================================================================
   TUTORIALES ANIMADOS
   ---------------------------------------------------------------------
   Cada sección muestra un tutorial la primera vez que se abre, y se puede
   repetir con el botón "?" de su cabecera.

   Los textos de todos los tutoriales viven en TOURS, más abajo, y no en la
   lógica: así se pueden revisar o traducir sin tocar el motor.

   Estructura de un paso:
     target : selector CSS del elemento que se resalta ("" = sin foco)
     sub    : pestaña interna que hay que activar antes de mostrarlo
     title  : título de la tarjeta
     body   : HTML del texto (admite <b> y <ol><li>)
     keys   : teclas o gestos que se muestran como fichas
     viewBox: (opcional) marco del lienzo de la animación
     demo   : (opcional) nombre de la animación a dibujar en el lienzo
     loop   : (opcional) la animación se repite en bucle
     cursor : (opcional) mueve el recuadro rosa por la rejilla de caracteres
   ===================================================================== */

/* Los textos de los tutoriales NO viven acá: se leen de tutorial.json a través
   de /api/tutorial, así se pueden corregir sin tocar el código. El formato es
   sencillo: **negrita**, `código`, listas con "1." o "- ", y saltos de línea. */
let TOURS = {};
let TOURS_LISTOS = false;

function tourTexto(s){
  if (!s) return '';
  const esc = x => x.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const bloques = [];
  let html = esc(s).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
  const lineas = html.split('\n');
  let lista = null;
  const cerrar = () => { if (lista){ bloques.push('<' + lista + '>' + lista_items.join('') + '</' + lista + '>'); lista = null; } };
  let lista_items = [];
  for (const linea of lineas){
    const v = linea.trim();
    if (!v){ cerrar(); bloques.push(''); continue; }
    const num = v.match(/^(\d+)\.\s+(.*)$/);
    const vin = v.match(/^-\s+(.*)$/);
    if (num){ if (lista !== 'ol'){ cerrar(); lista = 'ol'; lista_items = []; } lista_items.push('<li>' + num[2] + '</li>'); }
    else if (vin){ if (lista !== 'ul'){ cerrar(); lista = 'ul'; lista_items = []; } lista_items.push('<li>' + vin[1] + '</li>'); }
    else { cerrar(); bloques.push('<p>' + v + '</p>'); }
  }
  cerrar();
  return bloques.filter(Boolean).join('');
}

async function cargarTutorial(){
  if (TOURS_LISTOS) return TOURS;
  try {
    const r = await fetch('/api/tutorial');
    if (r.ok) TOURS = await r.json();
  } catch (e){ /* sin tutoriales: la app funciona igual */ }
  TOURS_LISTOS = true;
  return TOURS;
}

const TOUR_STORE = 'fontiador_tours_v1';

function toursSeen(){
  try { return JSON.parse(localStorage.getItem(TOUR_STORE) || '{}') || {}; }
  catch (e) { return {}; }
}
function tourSeen(id){ return toursSeen()[id] === true; }
function markTourSeen(id){
  const s = toursSeen();
  s[id] = true;
  try { localStorage.setItem(TOUR_STORE, JSON.stringify(s)); } catch (e) {}
}

/* ---------- Utilerías de dibujo (mismo espacio de coordenadas que la app) ---------- */
/* Copia literal de glyphPaths() de la app, para que las animaciones usen exactamente
   la misma transformación (línea base, escala, desplazamiento) y no una aproximación. */
function demoT(glyph, a, dx){
  a = a || {};
  const B = (M && M.base) || 800, sx = a.sx || 1, sy = a.sy || 1, dy = a.dy || 0;
  const th = (a.rot || 0) * Math.PI / 180, cs = Math.cos(th), sn = Math.sin(th);
  let d = '';
  for (const cmds of glyph) for (const cmd of cmds){
    if (cmd[0] === 'Z'){ d += 'Z '; continue; }
    const fx = cmd[1] * sx, fy = (B - cmd[2]) * sy + dy;
    d += cmd[0] + ' ' + (fx + dx).toFixed(1) + ' ' + (B - fy).toFixed(1) + ' ';
  }
  return d;
}
const DEMO_G = {
  H: [[["M",120,800],["L",220,800],["L",220,520],["L",520,520],["L",520,800],["L",620,800],
       ["L",620,140],["L",520,140],["L",520,430],["L",220,430],["L",220,140],["L",120,140],["Z"]]],
  A: [[["M",90,800],["L",620,800],["L",620,710],["L",140,710],["L",140,420],["L",570,420],
       ["L",570,330],["L",140,330],["L",140,140],["L",90,140],["Z"]]],
  o: [[["M",380,450],["L",105,450],["L",105,390],["L",380,390],["Z"]]],
  accentBase: [[["M",300,800],["L",420,800],["L",420,450],["L",300,450],["Z"]]],
  accentMark: [[["M",300,300],["L",340,240],["L",380,300],["L",360,300],["L",340,270],["L",320,300],["Z"]]]
};
function demoGuides(x0, w){
  let s = '';
  for (const p of [[M.asc,'#2f3a2f'],[M.cap,'#2f3a2f'],[M.xh,'#3a3a2f'],[M.base,'#7bd44b'],[M.desc,'#2f3a2f']])
    s += '<line x1="' + x0 + '" x2="' + (x0 + w) + '" y1="' + p[0] + '" y2="' + p[0] + '" stroke="' + p[1] + '" stroke-width="4"/>';
  return s;
}
const DEMOS = {
  /* Ancho y alto: la caja que se estira */
  scale: (v, loop, svg) => {
    const sx = v.sx, sy = v.sy;
    svg.innerHTML = demoGuides(-260, 1900) +
      '<rect x="0" y="0" width="' + (560 * sx).toFixed(1) + '" height="' + (660 * sy).toFixed(1) +
      '" fill="none" stroke="#555" stroke-dasharray="12 12"/>' +
      '<path d="' + demoT(DEMO_G.H, {sx: sx, sy: sy}, 0) + '" fill="#fff" stroke="#fff" stroke-width="10" stroke-linejoin="round"/>' +
      '<text x="-230" y="105" fill="#f06fc0" font-size="80" font-family="system-ui">ancho x' + sx.toFixed(2) + '</text>' +
      '<text x="-230" y="205" fill="#7bd44b" font-size="80" font-family="system-ui">alto x' + sy.toFixed(2) + '</text>';
  },
  /* Los dos lotes del asistente */
  pair: (v, loop, svg) => {
    svg.innerHTML = demoGuides(-80, 1300) +
      '<path d="' + demoT(DEMO_G.H, {}, 0) + '" fill="#fff"/>' +
      '<path d="' + demoT(DEMO_G.A, {}, 1500 - 1480 * v) + '" fill="#7bd44b" fill-opacity="0.55" stroke="#7bd44b" stroke-width="6"/>' +
      '<text x="60" y="880" fill="#999" font-size="52" font-family="system-ui">izquierda</text>' +
      '<text x="' + (1500 - 1480 * v + 60).toFixed(0) + '" y="880" fill="#7bd44b" font-size="52" font-family="system-ui">derecha</text>' +
      '<text x="120" y="560" fill="#999" font-size="50" font-family="system-ui">paso 1: elegí izquierda · paso 2: elegí derecha</text>';
  },
  /* Base frente a ajuste manual */
  kern: (v, loop, svg) => {
    const base = 340, adv = base + v * 260;
    svg.innerHTML = demoGuides(-80, 1400) +
      '<rect x="0" y="0" width="' + adv.toFixed(1) + '" height="1000" fill="none" stroke="#555" stroke-dasharray="12 12"/>' +
      '<path d="' + demoT(DEMO_G.H, {}, 0) + '" fill="#fff"/>' +
      '<path d="' + demoT(DEMO_G.o, {}, adv) + '" fill="#fff"/>' +
      '<path d="' + demoT(DEMO_G.o, {}, base) + '" fill="none" stroke="#555" stroke-dasharray="10 10"/>' +
      '<text x="120" y="720" fill="#7bd44b" font-size="54" font-family="system-ui">avance ' + Math.round(adv) +
      ' · base ' + base + ' · ajuste ' + Math.round(adv - base) + '</text>';
  },
  /* Una palabra con kerning correcto */
  word: (v, loop, svg) => {
    const gap = 30 + 190 * v;
    svg.innerHTML = demoGuides(-40, 1440) +
      '<path d="' + demoT(DEMO_G.H, {}, 60) + '" fill="#fff"/>' +
      '<path d="' + demoT(DEMO_G.o, {}, 60 + 700 + gap) + '" fill="#fff"/>' +
      '<path d="' + demoT(DEMO_G.H, {}, 60 + 1100 + gap) + '" fill="#fff"/>' +
      '<text x="60" y="645" fill="#999" font-size="52" font-family="system-ui">"HoH" · el par Ho se cierra, H vuelve a abrir</text>';
  },
  /* Vocal + marca = vocal acentuada */
  accent: (v, loop, svg) => {
    const dy = -220 * v;
    svg.innerHTML = demoGuides(-260, 1800) +
      '<path d="' + demoT(DEMO_G.accentBase, {}, 0) + '" fill="#fff"/>' +
      '<path d="' + demoT(DEMO_G.accentMark, {dy: dy}, 0) + '" fill="#f06fc0"/>' +
      '<text x="520" y="80" fill="#f06fc0" font-size="58" font-family="system-ui">marca (´) se une a la vocal</text>' +
      '<text x="520" y="180" fill="#7bd44b" font-size="58" font-family="system-ui">resultado: Á</text>';
  },
  /* Conjuntos activos */
  sets: (v, loop, svg) => {
    const on = v > 0.5;
    svg.innerHTML = '<rect x="0" y="0" width="1120" height="360" fill="#0d0d0d"/>' +
      '<text x="50" y="110" fill="' + (on ? '#7bd44b' : '#555') + '" font-size="90" font-family="system-ui">A B C 1 2 3</text>' +
      '<text x="50" y="240" fill="' + (on ? '#7bd44b' : '#555') + '" font-size="90" font-family="system-ui">a b c . , !</text>' +
      '<text x="50" y="330" fill="#999" font-size="46" font-family="system-ui">' +
      (on ? 'mayúsculas · minúsculas · números · puntuación — incluidos' : 'solo mayúsculas · minúsculas · números') + '</text>';
  },
  /* La rejilla de la plantilla: celdas y linea base */
  template: (v, loop, svg) => {
    const cw = 340, chh = 300;
    let s = '<rect x="0" y="0" width="1200" height="700" fill="#0d0d0d"/>';
    for (let r = 0; r < 2; r++){
      for (let c = 0; c < 3; c++){
        const x = 40 + c * (cw + 30), y = 40 + r * (chh + 30);
        s += '<rect x="' + x + '" y="' + y + '" width="' + cw + '" height="' + chh +
             '" fill="none" stroke="#3a3a3a" stroke-width="3"/>';
        // linea base a 80% de la altura de la celda (800 de 1000 px)
        s += '<line x1="' + x + '" y1="' + (y + chh * 0.8) + '" x2="' + (x + cw) +
             '" y2="' + (y + chh * 0.8) + '" stroke="#7bd44b" stroke-width="4"/>';
      }
    }
    // El contorno de ejemplo "crece" al ritmo de la animacion para dar sensacion de dibujo.
    const k = 0.35 + 0.65 * v;
    s += '<rect x="40" y="40" width="' + (cw * k).toFixed(0) + '" height="' + (chh * k).toFixed(0) +
         '" fill="none" stroke="#f06fc0" stroke-width="4" stroke-dasharray="10 8"/>';
    s += '<text x="40" y="640" fill="#999" font-size="44" font-family="system-ui">' +
         '10 columnas x celda 1000 px · linea base a 800 px · ancho total 10000 px</text>';
    svg.innerHTML = s;
  },
  /* Construir la fuente */
  build: (v, loop, svg) => {    const p = v;
    svg.innerHTML = '<rect x="0" y="0" width="1120" height="360" fill="#0d0d0d"/>' +
      '<rect x="60" y="120" width="900" height="26" fill="#333" rx="13"/>' +
      '<rect x="60" y="120" width="' + (900 * p).toFixed(0) + '" height="26" fill="#7bd44b" rx="13"/>' +
      '<text x="60" y="90" fill="#eee" font-size="56" font-family="system-ui">' + (p < 0.99 ? 'generando .otf…' : 'listo · output/MiFuente-Regular.otf') + '</text>' +
      '<text x="60" y="230" fill="#999" font-size="48" font-family="system-ui">' + Math.round(p * 103) + ' / 103 glifos · kerning incluido</text>';
  }
};

/* ---------- Motor ---------- */
const TOUR = { id: null, step: 0, active: false, timers: [], acts: [], raf: 0, card: null, spot: null, cursor: null };

function tourRoot(){
  let r = $('tourRoot');
  if (!r){
    r = document.createElement('div');
    r.id = 'tourRoot';
    r.innerHTML = '<div class="dim"></div><div id="tourSpot"></div><div id="tourCursor"></div>';
    document.body.appendChild(r);
  }
  return r;
}
function tourClearTimers(){
  TOUR.timers.forEach(t => clearTimeout(t));
  TOUR.timers = [];
  if (TOUR.raf) cancelAnimationFrame(TOUR.raf);
  TOUR.raf = 0;
}
function tourUndo(){
  TOUR.acts.forEach(fn => { try { fn(); } catch (e) {} });
  TOUR.acts = [];
}
function tourLater(fn, ms){ TOUR.timers.push(setTimeout(() => { try { fn(); } catch (e) {} }, ms)); }

/* Anima un lienzo SVG. v puede ser número, objeto o array de números. */
function tourAnimate(demo, viewBox, loop){
  const svg = $('tourCanvas');
  if (!svg || !demo) return;
  svg.setAttribute('viewBox', viewBox || '-100 0 1200 1000');
  const fn = DEMOS[demo];
  if (!fn) return;
  const paint = val => { try { fn(val, loop, svg); } catch (e) {} };
  const DUR = 1900, HOLD = loop ? 850 : 0;
  const start = performance.now();
  const tick = now => {
    if (!TOUR.active) return;
    const t = (now - start) % (DUR + HOLD);
    let p = Math.min(1, t / DUR);
    p = p * p * (3 - 2 * p);                       // suavizado
    let val;
    if (demo === 'scale') val = { sx: 1 + 0.55 * Math.sin(Math.PI * p), sy: 1 + 0.30 * Math.sin(Math.PI * p) };
    else if (demo === 'sets') val = p < 0.5 ? 0 : 1;
    else val = p;
    paint(val);
    if (p >= 1 && !loop) return;
    TOUR.raf = requestAnimationFrame(tick);
  };
  TOUR.raf = requestAnimationFrame(tick);
}

/* Mueve el recuadro rosa por la rejilla de caracteres, como si usaras las flechas. */
function tourCursorRun(){
  const cur = $('tourCursor');
  const grid = $('dimChars');
  if (!cur || !grid) return;
  const btns = [...grid.querySelectorAll('button')];
  if (btns.length < 3){ cur.style.display = 'none'; return; }
  cur.style.display = 'block';
  const place = i => {
    const b = btns[Math.min(i, btns.length - 1)];
    const r = b.getBoundingClientRect();
    cur.style.left = (r.left - 3) + 'px';
    cur.style.top = (r.top - 3) + 'px';
    cur.style.width = r.width + 'px';
    cur.style.height = r.height + 'px';
  };
  const seq = [0, 1, 2, 3, 4, 3, 2, 1];
  let i = 0;
  place(seq[0]);
  const step = () => {
    if (!TOUR.active) return;
    i = (i + 1) % seq.length;
    place(seq[i]);
    TOUR.timers.push(setTimeout(step, 620));
  };
  TOUR.timers.push(setTimeout(step, 620));
}

function tourHighlight(sel){
  const spot = $('tourSpot');
  const root = tourRoot();
  if (!spot) return;
  if (!sel){ spot.style.display = 'none'; return; }
  let el = null;
  try { el = document.querySelector(sel); } catch (e) { el = null; }
  if (!el){ spot.style.display = 'none'; return; }
  try { el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (e) {}
  const r = el.getBoundingClientRect();
  const pad = 5;
  spot.style.display = 'block';
  spot.style.left = (r.left - pad) + 'px';
  spot.style.top = (r.top - pad) + 'px';
  spot.style.width = Math.max(0, r.width + pad * 2) + 'px';
  spot.style.height = Math.max(0, r.height + pad * 2) + 'px';
}

function tourPlaceCard(){
  const card = TOUR.card, spot = $('tourSpot');
  if (!card) return;
  const cw = card.offsetWidth || 470, ch = card.offsetHeight || 240;
  const vw = window.innerWidth, vh = window.innerHeight, gap = 16, m = 12;
  let left = Math.round((vw - cw) / 2), top = Math.round((vh - ch) / 2), nearTop = false;
  const rect = (spot && spot.style.display !== 'none')
    ? { top: parseFloat(spot.style.top), left: parseFloat(spot.style.left),
        width: parseFloat(spot.style.width), height: parseFloat(spot.style.height) }
    : null;
  if (rect && (rect.height + ch + gap + m * 2) <= vh){
    const below = rect.top + rect.height + gap;
    const above = rect.top - ch - gap;
    if (below + ch + m <= vh){ top = below; nearTop = true; }
    else if (above >= m){ top = above; }
    left = Math.round(rect.left + rect.width / 2 - cw / 2);
  }
  left = Math.max(m, Math.min(left, vw - cw - m));
  top = Math.max(m, Math.min(top, vh - ch - m));
  card.style.left = left + 'px';
  card.style.top = top + 'px';
  if (card._arrow) card._arrow.style.display = nearTop ? 'block' : 'none';
}

async function tourRender(){
  await cargarTutorial();
  const tour = TOURS[TOUR.id];
  if (!tour || !tour.steps || !tour.steps.length){ tourClose(); return; }
  const st = tour.steps[TOUR.step];
  if (!st){ tourClose(); return; }
  const last = TOUR.step === tour.steps.length - 1;
  tourClearTimers();
  tourUndo();
  $('tourCursor').style.display = 'none';

  if (st.sub) switchKsub(st.sub);                  // solo cambia de vista, no guarda nada
  $('tourProg').textContent = (TOUR.step + 1) + ' / ' + tour.steps.length;
  $('tourTitle').textContent = st.title || tour.title;
  $('tourBody').innerHTML = st.body || '';
  $('tourPrev').style.visibility = TOUR.step === 0 ? 'hidden' : 'visible';
  $('tourNext').textContent = last ? 'Listo' : 'Siguiente';
  const kk = $('tourKeys');
  kk.innerHTML = '';
  (st.keys || []).forEach(k => {
    const s = document.createElement('span');
    s.className = (k === '+' || k === '/' || k === '·') ? 'tk sep' : 'tk';
    s.textContent = k;
    kk.appendChild(s);
  });
  const cv = $('tourCanvas');
  if (st.demo){ cv.style.display = 'block'; tourAnimate(st.demo, st.viewBox, st.loop); }
  else { cv.style.display = 'none'; }

  tourHighlight(st.target);
  setTimeout(() => { tourPlaceCard(); if (st.cursor) tourCursorRun(); }, 30);
}

function tourWindowResize(){
  if (!TOUR.active) return;
  const st = (TOURS[TOUR.id] || {steps:[]}).steps[TOUR.step] || {};
  tourHighlight(st.target);
  tourPlaceCard();
}

function tourOpen(id, auto){
  if (TOUR.active) tourClose();
  const tour = TOURS[id];
  if (!tour) return;
  TOUR.id = id; TOUR.step = 0; TOUR.active = true;
  /* Solo la reproducción automática marca el tutorial como visto: el botón "?" 
     puede repetirse tantas veces como haga falta sin alterar el estado. */
  if (auto) markTourSeen(id);
  const root = tourRoot();
  root.classList.add('on');
  if (!TOUR.card){
    const card = document.createElement('div');
    card.id = 'tourCard';
    card.innerHTML =
      '<h3><span id="tourProg"></span><span id="tourTitle"></span></h3>' +
      '<div id="tourBody"></div><svg id="tourCanvas"></svg>' +
      '<div id="tourKeys"></div>' +
      '<div id="tourBar">' +
        '<button class="btn sec" id="tourSkip">Saltar</button>' +
        '<span class="sp"></span>' +
        '<button class="btn sec" id="tourPrev">Anterior</button>' +
        '<button class="btn" id="tourNext">Siguiente</button>' +
      '</div>' +
      '<div id="tourHint">Salto de paso con ← → · Esc para salir</div>';
    root.appendChild(card);
    TOUR.card = card;
    $('tourSkip').onclick = () => tourClose();
    $('tourPrev').onclick = () => tourGo(-1);
    $('tourNext').onclick = () => tourGo(1);
  }
  TOUR.card.style.display = 'block';
  document.body.style.overflow = 'hidden';
  window.addEventListener('resize', tourWindowResize);
  window.addEventListener('scroll', tourWindowResize, true);
  tourRender();
}

function tourGo(dir){
  const tour = TOURS[TOUR.id];
  if (!tour) return;
  const next = TOUR.step + dir;
  if (next < 0) return;
  if (next >= tour.steps.length){ tourClose(); return; }
  TOUR.step = next;
  tourRender();
}

function tourClose(){
  if (!TOUR.active) return;
  TOUR.active = false;
  tourClearTimers();
  tourUndo();
  if (TOUR.card) TOUR.card.style.display = 'none';
  const cur = $('tourCursor');
  if (cur) cur.style.display = 'none';
  const root = $('tourRoot');
  if (root) root.classList.remove('on');
  if ($('tourProg')) $('tourProg').textContent = '';
  if ($('tourTitle')) $('tourTitle').textContent = '';
  if ($('tourBody')) $('tourBody').innerHTML = '';
  if ($('tourKeys')) $('tourKeys').innerHTML = '';
  TOUR.id = null;
  TOUR.step = 0;
  document.body.style.overflow = '';
  window.removeEventListener('resize', tourWindowResize);
  window.removeEventListener('scroll', tourWindowResize, true);
}

/* El teclado del tutorial tiene prioridad sobre los atajos de la app */
window.addEventListener('keydown', e => {
  if (!TOUR.active) return;
  if (e.key === 'Escape'){ e.preventDefault(); e.stopPropagation(); tourClose(); return; }
  if (e.key === 'ArrowRight'){ e.preventDefault(); e.stopPropagation(); tourGo(1); return; }
  if (e.key === 'ArrowLeft'){ e.preventDefault(); e.stopPropagation(); tourGo(-1); return; }
  if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); e.stopPropagation(); tourGo(1); return; }
}, true);

function tourMaybeAuto(id){
  if (!TOURS[id] || tourSeen(id)) return;
  /* ?nofirst=1 desactiva el arranque automático (útil para pruebas y capturas). */
  try {
    if (new URLSearchParams(location.search).get('nofirst') === '1') return;
  } catch (e) {}
  setTimeout(() => {
    if (TOUR.active || tourSeen(id)) return;   // no pisar una repetición pedida a mano
    tourOpen(id, true);
  }, 450);
}

function tourReplay(){
  if (TOUR.active) return;
  const active = document.querySelector('nav button[data-tab].active');
  if (active && TOURS[active.dataset.tab]) tourOpen(active.dataset.tab, false);
}

function tourMountButtons(){
  const bar = document.createElement('div');
  bar.id = 'tourBtns';
  bar.innerHTML = '<button class="tourHelp" title="Ver el tutorial de esta sección">?</button>';
  bar.querySelector('button').onclick = tourReplay;
  document.querySelector('main').appendChild(bar);
}

function tourReset(){
  try { localStorage.removeItem(TOUR_STORE); } catch (e) {}
  alert('Tutoriales restablecidos: volverán a mostrarse al abrir cada sección.');
}

/* Enganches: la primera visita a cada sección lanza su tutorial */
document.querySelectorAll('nav button[data-tab]').forEach(btn => {
  const prev = btn.onclick;
  btn.onclick = ev => {
    if (prev) prev(ev);
    tourMaybeAuto(btn.dataset.tab);
  };
});
tourMountButtons();
if ($('tourReset')) $('tourReset').onclick = tourReset;

/* La sección que ya está abierta al cargar tampoco se "cliquea": lanzarla también. */
(function(){
  const active = document.querySelector('nav button[data-tab].active');
  if (active) tourMaybeAuto(active.dataset.tab);
})();

/* Inicio e Importaciones son la misma pantalla. Se instala al final para pisar
   el manejador general de pestañas. */
(function(){
  const irA = tab => {
    const btn = document.querySelector('nav button[data-tab="' + tab + '"]');
    if (!btn) return;
    document.querySelectorAll('nav button[data-tab]').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('section').forEach(sec => sec.classList.toggle('active', sec.id === 'tab-' + tab));
    if (tab === 'dim' && typeof drawDim === 'function') drawDim();
    if (tab === 'kern' && typeof ensureKerningData === 'function'){ ensureKerningData(); drawPair(); drawBasePrev(); }
    if (tab === 'words' && typeof renderWord === 'function') renderWord();
    if (tab === 'imp' && typeof impRefresh === 'function') impRefresh();
    const caja = document.querySelector('main');
    if (caja) caja.scrollTop = 0;
  };
  window.fontiadorIrA = irA;
  const inicio = document.querySelector('nav button[data-tab="imp"]');
  if (inicio) inicio.onclick = () => irA('imp');
})();
</script></body></html>
"""


def _import_error_hint(e):
    """Convierte el error técnico en algo que el usuario pueda accionar."""
    if isinstance(e, RenderSizeError):
        return ("El render no tiene el tamaño esperado: %s Descargá la plantilla base, "
                "dibujá sobre esa cuadrícula y exportá a 10000 px de ancho." % e)
    msg = "%s: %s" % (type(e).__name__, e)
    if isinstance(e, PermissionError):
        return msg + " — puede que el archivo esté abierto en otro programa."
    if isinstance(e, json.JSONDecodeError):
        return msg + " — el archivo no es una exportación de glifos válida (¿es un JSON de otra cosa?)."
    return msg


def _import_paths(paths, mover=True):
    """Importa una lista de rutas y devuelve el resumen para la interfaz.

    Si el archivo venía de una carpeta vigilada se mueve a ``procesado/`` para que
    el vigilante no lo vuelva a importar en cada escaneo.
    """
    res = []
    for p in paths:
        base = os.path.basename(p)
        try:
            if not os.path.isfile(p):
                res.append({"archivo": base, "ok": False, "motivo": "el archivo no existe"})
                continue
            ext = os.path.splitext(p)[1].lower()
            if ext == ".json":
                _job_start(base, 1, "Importando vectores")
                with _lock:
                    n = import_file(p)
                _job_end("Vectores importados")
            elif ext in (".png", ".jpg", ".jpeg", ".svg"):
                n, _vacios, _fallidos = import_render(p)
            else:
                res.append({"archivo": base, "ok": False,
                            "motivo": "extensión no soportada (%s). Se aceptan PNG, JPG, SVG y JSON."
                                      % (ext or "sin extensión")})
                continue
            if mover:
                for d in INBOX_DIRS:
                    if os.path.dirname(os.path.abspath(p)) == os.path.abspath(d):
                        destino = os.path.join(d, "procesado")
                        os.makedirs(destino, exist_ok=True)
                        try:
                            shutil.move(p, os.path.join(destino, base))
                        except OSError:
                            pass
                        break
            with _lock:
                compose_accents(force=True)
                save_project()
            rebuild()
            res.append({"archivo": base, "ok": True, "glifos": n})
        except Exception as e:
            log("Error importando %s: %s" % (base, e))
            res.append({"archivo": base, "ok": False, "motivo": _import_error_hint(e)})
    return res


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        # La ruta se compara sin la cadena de consulta: así /?nofirst=1 sirve la app
        # igual que / (y los parámetros quedan disponibles en el navegador).
        from urllib.parse import parse_qs, urlparse
        ruta = urlparse(self.path).path
        if ruta == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path.startswith("/api/glyph?"):
            char = parse_qs(urlparse(self.path).query).get("c", [""])[0]
            g = glyph_preview(char)
            if g is None:
                self._send(404, json.dumps({"error": "sin glifo"}))
            else:
                self._send(200, json.dumps(g, ensure_ascii=False))
        elif self.path.startswith("/api/debug_cell?"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            char = q.get("c", [""])[0]
            if not char or char not in TEMPLATE_CHARS:
                self._send(400, json.dumps({"error": "carácter fuera del template"}))
                return
            try:
                info = _debug_cell(char)
                self._send(200, json.dumps(info, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
        elif self.path == "/api/tutorial":
            self._send(200, json.dumps(load_tutorial(), ensure_ascii=False))
        elif self.path == "/api/demo/font":
            rutas = [
                os.path.join(fontiador_paths.TEMPLATES_DIR, "FontiadorDemo-Regular.otf"),
                os.path.join(BASE_DIR, "templates", "FontiadorDemo-Regular.otf"),
            ]
            fuente = next((r for r in rutas if os.path.isfile(r)), None)
            if not fuente:
                self._send(404, json.dumps({"error": "no se encontró la fuente de demostración"}))
                return
            with open(fuente, "rb") as f:
                datos = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "font/otf")
            self.send_header("Content-Disposition",
                             'attachment; filename="FontiadorDemo-Regular.otf"')
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
        elif self.path == "/api/update/check":
            try:
                info = check_update()
            except Exception as e:
                info = {"actual": APP_VERSION, "repo": REPO, "repositorio": REPO_URL,
                        "descarga": REPO_URL + "/releases/latest", "disponible": False,
                        "nueva": None, "error": "%s: %s" % (type(e).__name__, e)}
            if info.get("disponible"):
                log("Hay una versión nueva disponible: %s (tenés la %s)."
                    % (info.get("nueva"), APP_VERSION))
            self._send(200, json.dumps(info, ensure_ascii=False))
        elif self.path == "/api/import/status":
            with _lock:
                project = _state["project"]
                turdsize, blur, alphamax, threshold, opttol = _trace_settings()
            self._send(200, json.dumps({
                "plataforma": fontiador_import.platform_name(),
                "dialogo": fontiador_import.dialog_available(),
                "datos": fontiador_paths.describe(),
                "modo": fontiador_paths.MODE,
                "base_dir": fontiador_paths.BASE_DIR,
                "carpetas": fontiador_import.watched_state(INBOX_DIRS),
                "formato": {
                    "columnas": RENDER_COLS,
                    "celda": RENDER_CELL,
                    "filas": (len(TEMPLATE_CHARS) + RENDER_COLS - 1) // RENDER_COLS,
                    "caracteres": len(TEMPLATE_CHARS),
                    "linea_base": project["metrics"].get("baseline_px", 800),
                    "avance_defecto": project["metrics"].get("default_advance", 500),
                    "upm": project["metrics"].get("upm", 1000),
                },
                "orden": fontiador_import.order_reference(TEMPLATE_CHARS, RENDER_COLS, RENDER_CELL),
                "trazado": {"turdsize": turdsize, "blur": blur, "alphamax": alphamax,
                            "threshold": threshold, "opttolerance": opttol},
            }, ensure_ascii=False))
        elif self.path == "/api/import/guide":
            self._send(200, json.dumps({"programas": IMPORT_GUIDE}, ensure_ascii=False))
        elif self.path == "/api/import/plantilla.svg":
            svg = build_template_svg()
            self._send(200, svg, "image/svg+xml; charset=utf-8")
        elif self.path == "/api/import/plantilla.png":
            try:
                png = build_template_png()
            except Exception as e:
                self._send(500, json.dumps({"error": "no se pudo generar la plantilla: %s" % e}))
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Disposition", 'attachment; filename="fontiador-plantilla.png"')
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
        elif self.path == "/api/status":
            with _lock:
                project = _state["project"]
                glyphs = project["glyphs"]
                chars = "".join(c for c in sorted(glyphs) if c in allowed_chars())
                turdsize, blur, alphamax, threshold, opttol = _trace_settings()
                payload = {
                    "glyphs": len(glyphs),
                    "chars": chars,
                    "family": _state["family"],
                    "style": _state["style"],
                    "last_output": _state["last_output"],
                    "charsets": project["charsets"],
                    "kerning": project.get("kerning", []),
                    "kerning_char": project.get("kerning_char", {}),
                    "all_chars": "".join(sorted(glyphs.keys())),
                    "adjust": project.get("adjust", {}),
                    "accent_adjust": project.get("accent_adjust", {}),
                    "trace": {"turdsize": turdsize, "blur": blur, "alphamax": alphamax,
                              "threshold": threshold, "opttolerance": opttol},
                    "version": _state.get("version", 0),
                    "job": dict(JOB,
                                elapsed=round(time.time() - JOB["started"], 1) if JOB.get("started") else 0,
                                since_end=round(time.time() - JOB["ended"], 1) if JOB.get("ended") else None),
                    "metrics": {"baseline_px": project["metrics"].get("baseline_px", 800),
                                "default_advance": project["metrics"].get("default_advance", 500)},
                    "log": list(_state["log"]),
                    "watch": dict(_state["watch"]),
                }
            self._send(200, json.dumps(payload, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "no encontrado"}))

    def do_POST(self):
        try:
            data = self._json_body()
        except json.JSONDecodeError:
            self._send(400, json.dumps({"error": "JSON inválido"}))
            return

        if self.path == "/api/import/dialog":
            try:
                paths = fontiador_import.pick_many("render")
            except Exception as e:
                self._send(500, json.dumps({"error": "no se pudo abrir el diálogo: %s" % e}))
                return
            self._send(200, json.dumps({"rutas": paths or []}, ensure_ascii=False))
            return

        if self.path == "/api/import/files":
            rutas = data.get("rutas") or data.get("paths") or []
            if isinstance(rutas, str):
                rutas = [rutas]
            rutas = [fontiador_import._clean(r) for r in rutas]
            rutas = [r for r in rutas if r]
            if not rutas:
                self._send(400, json.dumps({"error": "no se recibió ninguna ruta válida"}))
                return
            self._send(200, json.dumps({"resultados": _import_paths(rutas)}, ensure_ascii=False))
            return

        if self.path == "/api/import/rescan":
            try:
                imported = process_inbox()
                self._send(200, json.dumps({"ok": True, "importado": bool(imported)}))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return

        if self.path == "/api/import/clear":
            donde = str(data.get("donde", "errores"))
            if donde not in ("errores", "procesado"):
                self._send(400, json.dumps({"error": "usá 'errores' o 'procesado'"}))
                return
            borrados = 0
            for d in INBOX_DIRS:
                p = os.path.join(d, donde)
                if not os.path.isdir(p):
                    continue
                for f in os.listdir(p):
                    fp = os.path.join(p, f)
                    if os.path.isfile(fp):
                        try:
                            os.remove(fp)
                            borrados += 1
                        except OSError:
                            pass
            log("Limpieza de inbox/%s: %d archivos" % (donde, borrados))
            self._send(200, json.dumps({"ok": True, "borrados": borrados}))
            return

        if self.path == "/api/recompose":
            with _lock:
                compose_accents(force=True)
                save_project()
            rebuild()
            self._send(200, json.dumps({"ok": True}))
            return

        if self.path == "/api/retrace":
            last = _find_last_processed_render()
            if not last:
                self._send(404, json.dumps({"error": "no hay render previo para re-traza"}))
                return
            try:
                _job_start("re-trace", 1, "Re-trazando " + os.path.basename(last))
                count, _, _ = import_render(last)
                with _lock:
                    compose_accents(force=True)
                    save_project()
                rebuild()
                _job_end("Re-trazado")
                self._send(200, json.dumps({"ok": True, "glyphs": count, "source": os.path.basename(last)}))
            except Exception as e:
                log("Error re-trazando: %s" % e)
                _job_end("Error")
                self._send(500, json.dumps({"error": str(e)}))
            return

        with _lock:
            project = _state["project"]
            if self.path == "/api/kerning/set":
                left, right = str(data.get("left", "")), str(data.get("right", ""))
                if len(left) != 1 or len(right) != 1:
                    self._send(400, json.dumps({"error": "usa un carácter por lado"}))
                    return
                final_val = int(data.get("value", 0))
                kerning_char = project.get("kerning_char", {})
                base_val = kerning_char.get(left, {}).get("r", 0) + kerning_char.get(right, {}).get("l", 0)
                manual_offset = final_val - base_val
                project["kerning"] = [p for p in project.get("kerning", []) if (p["left"], p["right"]) != (left, right)]
                if manual_offset != 0:
                    project["kerning"].append({"left": left, "right": right, "value": manual_offset})
                save_project()
                log("Kerning manual %s%s = %d (base=%d, ajuste=%d)" % (left, right, final_val, base_val, manual_offset))
                self._send(200, json.dumps({"ok": True}))
                return
            elif self.path == "/api/kerning/delete":
                key = (str(data.get("left", "")), str(data.get("right", "")))
                project["kerning"] = [p for p in project.get("kerning", [])
                                      if (p["left"], p["right"]) != key]
                save_project()
                log("Kerning eliminado: %s%s" % key)
                self._send(200, json.dumps({"ok": True}))
                return
            elif self.path == "/api/kerning/char":
                chars_raw = data.get("chars") or data.get("char") or ""
                if isinstance(chars_raw, str):
                    chars = [chars_raw] if len(chars_raw) == 1 else list(chars_raw)
                elif isinstance(chars_raw, list):
                    chars = chars_raw
                else:
                    chars = []
                if not chars:
                    self._send(400, json.dumps({"error": "elige caracteres"}))
                    return
                set_chars_kerning(chars, data.get("l", 0), data.get("r", 0))
                self._send(200, json.dumps({"ok": True}))
                return
            elif self.path == "/api/adjust":
                char = str(data.get("char", ""))
                if len(char) != 1:
                    self._send(400, json.dumps({"error": "elige un carácter"}))
                    return
                set_adjust(char, data)
                self._send(200, json.dumps({"ok": True}))
                return
            elif self.path == "/api/adjust/many":
                chars = [c for c in str(data.get("chars", "")) if c]
                for c in chars:
                    set_adjust(c, {"advance": "", "sx": data.get("sx", 1), "sy": data.get("sy", 1),
                                   "dy": data.get("dy", 0), "rot": data.get("rot", 0)})
                self._send(200, json.dumps({"chars": len(chars)}))
                return
            elif self.path == "/api/accent":
                key = str(data.get("char", "*"))
                if key != "*" and key not in ACCENT_PAIRS and key != ACCENT_MARK and key != TILDE_MARK:
                    self._send(400, json.dumps({"error": "elige una vocal acentuada o *"}))
                    return
                entry = {k: float(data.get(k, 0.0)) if k in ("dx", "dy") else float(data.get(k, 1.0))
                         for k in ("dx", "dy", "s")}
                project["accent_adjust"][key] = entry
                save_project()
                compose_accents(force=True)
                self._send(200, json.dumps({"ok": True}))
                return
            elif self.path == "/api/charsets":
                for k in CHARSET_GROUPS:
                    if k in data:
                        project["charsets"][k] = bool(data[k])
                save_project()
                bump_version()
                self._send(200, json.dumps({"ok": True}))
                return
            elif self.path == "/api/trace":
                for k, key in (("blur","trace_blur"),("alphamax","trace_alphamax"),
                               ("threshold","trace_threshold"),("turdsize","trace_turdsize"),
                               ("opttolerance","trace_opttolerance")):
                    if k in data:
                        v = float(data[k]) if k != "turdsize" else int(float(data[k]))
                        project[key] = v
                save_project()
                self._send(200, json.dumps({"ok": True}))
                return
            elif self.path == "/api/build":
                pass
            else:
                self._send(404, json.dumps({"error": "no encontrado"}))
                return

        if self.path == "/api/build":
            family = (data.get("family") or "").strip() or None
            style = (data.get("style") or "").strip() or None
            try:
                out = rebuild(family, style)
            except Exception as e:
                log("Error al construir: %s" % e)
                self._send(500, json.dumps({"error": str(e)}))
                return
            self._send(200, json.dumps({"path": out}))
        else:
            self._send(200, json.dumps({"ok": True}))


def watch(interval):
    import traceback
    while True:
        try:
            process_inbox()
        except Exception as e:
            log("Error vigilando inbox: %s: %s" % (type(e).__name__, e))
            for line in traceback.format_exc().strip().splitlines()[-4:]:
                log("  " + line)
        time.sleep(interval)


def start_window(url):
    try:
        import webview
    except Exception as e:
        log("Ventana propia no disponible (%s). Se usa el navegador." % e)
        return False
    try:
        webview.create_window("Fontiador", url, width=1280, height=860, min_size=(900, 600))
        t0 = time.time()
        webview.start()
        if time.time() - t0 < 5:
            log("La ventana propia se cerró al instante. Se usa el navegador.")
            return False
        return True
    except Exception as e:
        log("No se pudo abrir la ventana propia (%s). Se usa el navegador." % e)
        return False


def _abrir_servidor(puerto_pedido):
    """Crea el servidor HTTP sin morir si el puerto está ocupado.

    Antes, si el 8765 estaba tomado, la app terminaba al instante sin dejar
    rastro: con la ventana sin consola el usuario veía que no pasaba nada.
    Ahora se prueba el puerto pedido y, si falla, se pide uno libre al sistema.
    Devuelve (servidor, puerto_real, aviso).
    """
    try:
        s = ThreadingHTTPServer(("127.0.0.1", puerto_pedido), Handler)
        return s, s.server_address[1], None
    except OSError as e:
        aviso = ("El puerto %d estaba ocupado (%s). " % (puerto_pedido, e))
    try:
        s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        puerto = s.server_address[1]
        return s, puerto, aviso + "Se usa el puerto libre %d." % puerto
    except OSError as e:
        raise RuntimeError("No se pudo abrir ningún puerto local: %s" % e)


def _avisar_error(mensaje):
    """Muestra el error al usuario cuando no hay consola donde leerlo.

    En Windows se usa un cuadro de diálogo nativo; en el resto se escribe en la
    salida de error. Siempre queda además la traza en fontiador.log.
    """
    try:
        log("ERROR FATAL: " + mensaje.replace("\n", " | "))
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, "No se pudo iniciar Fontiador.\n\n" + mensaje +
                "\n\nEl detalle quedó en:\n" + fontiador_paths.LOG_FILE,
                "Fontiador", 0x10)  # MB_ICONERROR
            return
        except Exception:
            pass
    try:
        sys.stderr.write(mensaje + "\n")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Fontiador: genera la fuente desde Affinity")
    parser.add_argument("--family", default="Mi Fuente")
    parser.add_argument("--style", default="Regular")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--browser", action="store_true", help="usar el navegador en lugar de una ventana propia")
    parser.add_argument("--no-browser", action="store_true", help="no abrir ventana ni navegador")
    args = parser.parse_args()

    _state["family"], _state["style"] = args.family, args.style
    fontiador_paths.ensure_dirs()
    load_project()
    for d in INBOX_DIRS:
        os.makedirs(d, exist_ok=True)
    threading.Thread(target=watch, args=(args.interval,), daemon=True).start()

    server, puerto, aviso = _abrir_servidor(args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % puerto
    log(fontiador_paths.describe())
    if aviso:
        log(aviso)
    log("Interfaz en %s — vigilando: %s" % (url, " · ".join(INBOX_DIRS)))

    try:
        if args.no_browser:
            pass
        elif not args.browser and start_window(url):
            log("Ventana cerrada por el usuario. Terminado.")
            return
        else:
            import webbrowser
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Terminado.")
        sys.exit(0)


if __name__ == "__main__":
    # Cualquier fallo de arranque se registra y se muestra, en vez de que la app
    # desaparezca sin explicacion cuando corre sin consola.
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        import traceback
        detalle = traceback.format_exc()
        try:
            _redirigir_salida()
        except Exception:
            pass
        _avisar_error("%s: %s" % (type(e).__name__, e))
        try:
            log("Traza completa:")
            for linea in detalle.strip().splitlines():
                log("  " + linea)
        except Exception:
            pass
        sys.exit(1)