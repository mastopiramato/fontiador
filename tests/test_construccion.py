"""Construccion de extremo a extremo: importar y generar una fuente real.

Trabaja siempre en una carpeta temporal (FONTIADOR_DATA_DIR) para no tocar las
fuentes ni el proyecto del usuario, que es justo lo que casi pasa una vez.

    py tests/test_construccion.py
"""

import json
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Aislar los datos ANTES de importar fontiador_paths.
TMP = tempfile.mkdtemp(prefix="fontiador_test_")
os.environ["FONTIADOR_DATA_DIR"] = TMP
sys.path.insert(0, RAIZ)

fallos = []


def check(nombre, cond, detalle=""):
    if cond:
        print("  ok   %s" % nombre)
    else:
        print("  FALLA %s %s" % (nombre, detalle))
        fallos.append(nombre)


def rect(a, b, y0, y1):
    return [["M", a, y0], ["L", b, y0], ["L", b, y1], ["L", a, y1], ["Z"]]


def main():
    import fontiador_paths
    import fontiador_server as s

    print("Aislamiento de datos")
    check("los datos van a la carpeta temporal", fontiador_paths.BASE_DIR == TMP,
          fontiador_paths.BASE_DIR)

    # 1) Importar un export_*.json
    print("Importacion de vectores")
    payload = {
        "metrics": {"upm": 1000, "ascender": 750, "descender": -200, "cap_height": 700,
                    "x_height": 500, "baseline_px": 800, "scale": 1, "default_advance": 500},
        "glyphs": [{"char": c, "advance": 600, "outline_cmds": rect(120 + i * 10, 500, 800, 200)}
                   for i, c in enumerate("HAoV")],
    }
    entrada = os.path.join(TMP, "export_prueba.json")
    with open(entrada, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    res = s._import_paths([entrada], mover=False)
    check("la importacion devuelve un resultado", len(res) == 1)
    check("la importacion fue exitosa", res and res[0].get("ok") is True, str(res))
    check("se importaron 4 glifos", res and res[0].get("glifos") == 4, str(res))

    # 2) Construir la fuente
    print("Construccion de la fuente")
    salida = s.rebuild(family="TestFont", style="Regular")
    check("se genero el archivo", salida and os.path.exists(salida), str(salida))
    if salida and os.path.exists(salida):
        check("el archivo pesa mas que 0", os.path.getsize(salida) > 0)
        # 3) Leer la fuente generada con fontTools
        from fontTools.ttLib import TTFont
        try:
            f = TTFont(salida)
            cmap = f.getBestCmap()
            check("la fuente abre con fontTools", True)
            for ch in "HAoV":
                check("el mapa de caracteres incluye %s" % ch, ord(ch) in cmap)
            check("el nombre de familia es TestFont",
                  f["name"].getDebugName(1) == "TestFont",
                  str(f["name"].getDebugName(1)))
            check("tiene tabla de metricas horizontales", "hmtx" in f)
        except Exception as e:
            check("la fuente abre con fontTools", False, "%s: %s" % (type(e).__name__, e))

    # 4) Un render con el tamano equivocado debe fallar con un mensaje util
    print("Errores comprensibles")
    try:
        raise s.RenderSizeError("mide 100x100 px, se necesitan 11 filas")
    except s.RenderSizeError as e:
        pista = s._import_error_hint(e)
        check("el mensaje menciona la plantilla", "plantilla" in pista.lower(), pista)
        check("el mensaje dice que hacer", "10000" in pista, pista)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print()
    if fallos:
        print("FALLARON %d comprobaciones:" % len(fallos))
        for f in fallos:
            print("  - %s" % f)
        sys.exit(1)
    print("Todo OK")
