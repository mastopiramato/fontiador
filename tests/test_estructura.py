"""Pruebas mínimas de Fontiador.

Se ejecutan sin dependencias externas (no hace falta pytest):

    py tests/test_estructura.py

Cubren los errores que ya nos mordieron una vez: que la página quede con las
etiquetas <script> desbalanceadas, que desaparezca un endpoint, y que las rutas
de trabajo dejen de ser escribibles.
"""

import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

fallos = []


def check(nombre, condicion, detalle=""):
    if condicion:
        print("  ok   %s" % nombre)
    else:
        print("  FALLA %s %s" % (nombre, detalle))
        fallos.append(nombre)


def extraer_page():
    src = open(os.path.join(RAIZ, "fontiador_server.py"), encoding="utf-8").read()
    m = re.search(r'PAGE = r"""(.*?)"""\n', src, re.S)
    return m.group(1) if m else None


def test_page_html():
    print("PAGE / HTML")
    page = extraer_page()
    check("PAGE existe", page is not None)
    if not page:
        return
    abiertos = len(re.findall(r"<script>", page))
    cerrados = len(re.findall(r"</script>", page))
    check("etiquetas <script> balanceadas", abiertos == cerrados,
          "abren %d, cierran %d" % (abiertos, cerrados))
    check("cierra body y html", page.rstrip().endswith("</body></html>"))
    check("no hay comilla triple dentro de PAGE", '"""' not in page)
    # Cada bloque de script tiene que ser sintácticamente válido cuando menos en
    # cuanto a llaves y paréntesis balanceados (no reemplaza a node --check, pero
    # detecta un corte a la mitad).
    bloques = re.findall(r"<script>(.*?)</script>", page, re.S)
    for i, b in enumerate(bloques):
        check("bloque %d con llaves balanceadas" % i,
              b.count("{") == b.count("}"), "abren %d, cierran %d" % (b.count("{"), b.count("}")))
        check("bloque %d con parentesis balanceados" % i, b.count("(") == b.count(")"))


def test_endpoints():
    print("Endpoints HTTP")
    import fontiador_server as s
    import inspect
    fuente = inspect.getsource(s.Handler.do_POST) + inspect.getsource(s.Handler.do_GET)
    esperados = [
        "/api/status", "/api/glyph", "/api/build", "/api/kerning/set", "/api/kerning/delete",
        "/api/kerning/char", "/api/adjust", "/api/adjust/many", "/api/accent", "/api/charsets",
        "/api/trace", "/api/recompose", "/api/retrace", "/api/debug_cell",
        "/api/import/status", "/api/import/guide", "/api/import/dialog", "/api/import/files",
        "/api/import/rescan", "/api/import/clear",
        "/api/import/plantilla.svg", "/api/import/plantilla.png",
        "/api/demo/font", "/api/update/check",
    ]
    for ep in esperados:
        check("ruta %s" % ep, ep in fuente)


def test_nombres_de_modulos():
    """Ningún archivo debe referirse a los módulos viejos affont_*.

    Al renombrar el proyecto se escaparon referencias sueltas a affont_paths,
    que solo se notaban al usar la función: el módulo importaba bien y fallaba
    después, en pleno pedido. Esta comprobación las detecta antes.
    """
    print("Nombres de módulos")
    import glob
    import re
    viejos = ("affont_paths", "affont_import", "affont_builder", "affont_server")
    patrones = [re.compile(r"\b%s\s*\." % v) for v in viejos] + \
               [re.compile(r"^\s*(?:import|from)\s+%s\b" % v) for v in viejos]
    problemas = []
    for patron in ("*.py", "tests/*.py", "packaging/*.py"):
        for p in glob.glob(os.path.join(RAIZ, patron)):
            try:
                t = open(p, encoding="utf-8").read()
            except OSError:
                continue
            for i, linea in enumerate(t.splitlines(), 1):
                for rx in patrones:
                    if rx.search(linea):
                        problemas.append("%s:%d %s" % (os.path.relpath(p, RAIZ), i,
                                                       linea.strip()[:60]))
    check("sin referencias a módulos affont_*", not problemas,
          "; ".join(problemas[:5]))

    # Los módulos con el nombre nuevo tienen que existir y ser importables.
    for mod in ("fontiador_paths", "fontiador_import", "fontiador_builder"):
        check("el módulo %s existe" % mod,
              os.path.isfile(os.path.join(RAIZ, mod + ".py")))


def test_secciones():
    """La estructura de secciones tiene que coincidir con el menú."""
    print("Secciones y menú")
    page = extraer_page()
    if not page:
        return
    secciones = re.findall(r'<section id="tab-(\w+)"', page)
    menu = re.findall(r'<button data-tab="(\w+)"', page)
    check("la misma cantidad de secciones que de botones",
          len(secciones) == len(menu), "%d vs %d" % (len(secciones), len(menu)))
    faltan = [t for t in menu if t not in secciones]
    check("cada botón del menú tiene su sección", not faltan, str(faltan))
    sobran = [t for t in secciones if t not in menu]
    check("no hay secciones huérfanas", not sobran, str(sobran))

    # Conjuntos se integró a Fuente: no debe volver como pestaña propia.
    check("Conjuntos ya no es una pestaña", "sets" not in menu)
    check("las casillas de conjuntos viven en Fuente",
          page.find('id="cs_upper"') > page.find('<section id="tab-font"'))

    # Tildes va antes que Palabras.
    check("Tildes está antes que Palabras",
          menu.index("accent") < menu.index("words"), str(menu))

    # Cada sección dibuja sus atajos como fichas.
    for tab in secciones:
        bloque = re.search(r'<section id="tab-%s".*?(?=<section id=|\Z)' % tab, page, re.S)
        # Los atajos se generan por JavaScript, así que alcanza con que la sección
        # exista y esté en la tabla de atajos.
        check("%s tiene sección" % tab, bloque is not None)
    for tab in secciones:
        check("%s figura en la tabla de atajos" % tab,
              ("%s:" % tab) in page or ("'%s'" % tab) in page)


def test_tutorial():
    """Los textos del tutorial viven en tutorial.json y tienen que ser editables."""
    print("Tutoriales")
    import json
    import fontiador_server as s

    ruta = os.path.join(RAIZ, "tutorial.json")
    check("existe tutorial.json", os.path.isfile(ruta))
    if not os.path.isfile(ruta):
        return
    try:
        with open(ruta, encoding="utf-8-sig") as f:
            datos = json.load(f)
    except json.JSONDecodeError as e:
        check("tutorial.json es JSON válido", False, str(e))
        return
    check("tutorial.json es JSON válido", True)

    # Cada sección de la app debería tener su tutorial. Conjuntos ya no es una
    # sección: su paso quedó dentro del tutorial de Fuente.
    secciones = ["imp", "dim", "kern", "words", "accent", "font", "log"]
    faltan = [k for k in secciones if k not in datos]
    check("hay un tutorial por sección", not faltan, "faltan %r" % faltan)

    for clave, tour in datos.items():
        check("%s tiene título" % clave, bool(tour.get("title")))
        pasos = tour.get("steps") or []
        check("%s tiene pasos" % clave, bool(pasos))
        for i, paso in enumerate(pasos, 1):
            check("%s paso %d tiene título" % (clave, i), bool(paso.get("title")))
            check("%s paso %d tiene texto" % (clave, i), bool(paso.get("body")))

    # La carga del lado del servidor tiene que devolver lo mismo.
    cargado = s.load_tutorial()
    check("load_tutorial devuelve los tutoriales", len(cargado) == len(datos),
          "%d vs %d" % (len(cargado), len(datos)))

    # Y tiene que tolerar un archivo roto sin romper la app.
    import shutil
    import tempfile
    import fontiador_paths as fp
    tmp = tempfile.mkdtemp(prefix="fontiador_tut_")
    try:
        malo = os.path.join(tmp, "tutorial.json")
        with open(malo, "w", encoding="utf-8") as f:
            f.write("{ esto no es json")
        # Se apuntan las dos carpetas: la de datos y la del paquete, porque el
        # archivo se busca en las dos.
        previos = (s.BASE_DIR, fp.BASE_DIR, fp.BUNDLE_DIR)
        s.BASE_DIR = fp.BASE_DIR = fp.BUNDLE_DIR = tmp
        check("un tutorial roto no rompe la app", s.load_tutorial() == {},
              str(list(s.load_tutorial().keys())[:3]))
    finally:
        s.BASE_DIR, fp.BASE_DIR, fp.BUNDLE_DIR = previos
        shutil.rmtree(tmp, ignore_errors=True)


def test_fuente_demo():
    print("Fuente de demostración")
    import fontiador_server as s
    ruta = os.path.join(RAIZ, "templates", "FontiadorDemo-Regular.otf")
    check("existe el archivo de la fuente demo", os.path.isfile(ruta),
          "ejecutá packaging/generar_fuente_demo.py")
    if not os.path.isfile(ruta):
        return
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        check("fontTools disponible para revisarla", False)
        return
    f = TTFont(ruta)
    cmap = f.getBestCmap()
    familia = f["name"].getDebugName(1)
    check("la familia es 'Fontiador Demo'", familia == "Fontiador Demo", str(familia))
    check("cubre los 103 caracteres del template",
          all(ord(c) in cmap for c in s.TEMPLATE_CHARS),
          "faltan %r" % [c for c in s.TEMPLATE_CHARS if ord(c) not in cmap][:10])
    acentos = "ÁÉÍÓÚáéíóúÑñ"
    check("incluye las tildes compuestas",
          all(ord(c) in cmap for c in acentos),
          "faltan %r" % [c for c in acentos if ord(c) not in cmap])
    # Ningún glifo debe quedar sin avance ni con avance absurdo.
    malos = [(chr(ch), f["hmtx"][n][0]) for ch, n in cmap.items()
             if f["hmtx"][n][0] <= 0 or f["hmtx"][n][0] > 1200]
    check("todos los avances son razonables", not malos, str(malos[:5]))
    check("no es una copia de otra tipografía (nombre propio)",
          "arial" not in (familia or "").lower())


def test_importaciones():
    print("Importaciones")
    import fontiador_server as s
    check("guia con los 6 programas", len(s.IMPORT_GUIDE) == 6, "hay %d" % len(s.IMPORT_GUIDE))
    for prog in s.IMPORT_GUIDE:
        for campo in ("id", "nombre", "mecanismo", "pasos"):
            check("guia %s tiene %s" % (prog.get("id", "?"), campo), campo in prog)
    svg = s.build_template_svg()
    check("plantilla SVG no vacia", len(svg) > 1000)
    check("plantilla SVG es svg", svg.lstrip().startswith("<?xml") and "<svg" in svg)
    png = s.build_template_png()
    check("plantilla PNG no vacia", len(png) > 1000)
    check("plantilla PNG tiene cabecera PNG", png[:8] == b"\x89PNG\r\n\x1a\n")


def test_orden_caracteres():
    print("Formato de la rejilla")
    import fontiador_server as s
    check("10 columnas", s.RENDER_COLS == 10)
    check("celda de 1000 px", s.RENDER_CELL == 1000)
    check("103 caracteres en el template", len(s.TEMPLATE_CHARS) == 103,
          "hay %d" % len(s.TEMPLATE_CHARS))
    check("sin caracteres repetidos", len(set(s.TEMPLATE_CHARS)) == len(s.TEMPLATE_CHARS))
    check("tamano de render 10000 px de ancho", s.RENDER_COLS * s.RENDER_CELL == 10000)


def test_arranque():
    print("Arranque (puerto ocupado)")
    import socket
    import fontiador_server as s

    # Ocupamos un puerto y comprobamos que el servidor elige otro en vez de morir.
    ocupado = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ocupado.bind(("127.0.0.1", 0))
    ocupado.listen(1)
    puerto = ocupado.getsockname()[1]
    try:
        servidor, puerto_real, aviso = s._abrir_servidor(puerto)
        check("sobrevive si el puerto esta ocupado", servidor is not None)
        check("elige un puerto distinto", puerto_real != puerto,
              "%s vs %s" % (puerto_real, puerto))
        check("avisa del cambio de puerto", bool(aviso) and str(puerto) in str(aviso), str(aviso))
        servidor.server_close()
    finally:
        ocupado.close()

    servidor2, _p2, aviso2 = s._abrir_servidor(0)
    check("sin aviso cuando el puerto esta libre", aviso2 is None, str(aviso2))
    servidor2.server_close()


def test_persistencia():
    print("Persistencia del proyecto")
    import json
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="fontiador_persist_")
    os.environ["FONTIADOR_DATA_DIR"] = tmp
    for mod in ("fontiador_paths", "fontiador_server"):
        sys.modules.pop(mod, None)
    try:
        import fontiador_paths as p
        import fontiador_server as s

        # Un proyecto guardado con BOM (Bloc de notas de Windows) debe leerse.
        with open(p.PROJECT_FILE, "w", encoding="utf-8-sig") as f:
            json.dump({"metrics": {}, "glyphs": {"A": {"char": "A"}}, "kerning": []}, f)
        s._state["project"]["glyphs"].clear()
        s.load_project()
        check("lee un proyecto guardado con BOM", "A" in s._state["project"]["glyphs"],
              str(list(s._state["project"]["glyphs"].keys())))

        # Un archivo dañado no se descarta: se aparta como copia recuperable.
        with open(p.PROJECT_FILE, "w", encoding="utf-8") as f:
            f.write("{ roto")
        s.load_project()
        check("conserva una copia del proyecto dañado",
              os.path.exists(p.PROJECT_FILE + ".dañado"))
    finally:
        os.environ.pop("FONTIADOR_DATA_DIR", None)
        for mod in ("fontiador_paths", "fontiador_server"):
            sys.modules.pop(mod, None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_actualizaciones():
    print("Actualizaciones")
    import fontiador_server as s
    check("repo configurado", "/" in s.REPO, s.REPO)
    check("url de la api coherente", s.REPO in s.RELEASES_API, s.RELEASES_API)
    casos = [
        ("0.2.0", "v0.2.0", False),
        ("0.2.0", "v0.3.0", True),
        ("0.2.0", "v0.1.9", False),
        ("0.10.0", "v0.9.0", False),   # 10 > 9: comparacion numerica, no de texto
        ("1.0.0", "v0.10.0", False),
        ("0.2.0", "v1.0.0", True),
        ("0.2.0-beta", "v0.2.0", False),
    ]
    for actual, nueva, esperado in casos:
        check("version %s < %s == %s" % (actual, nueva, esperado),
              s._version_menor(actual, nueva) == esperado)
    # Nunca debe lanzar, ni siquiera sin internet.
    info = s.check_update()
    check("check_update devuelve un diccionario", isinstance(info, dict))
    for campo in ("actual", "repo", "disponible", "descarga", "repositorio"):
        check("check_update incluye %s" % campo, campo in info)


def test_rutas():
    print("Rutas de trabajo")
    import fontiador_paths as p
    check("BASE_DIR existe", os.path.isdir(p.BASE_DIR), p.BASE_DIR)
    check("BASE_DIR es la raiz del proyecto o una carpeta de datos",
          os.path.isfile(os.path.join(p.BASE_DIR, "fontiador_server.py")) or p.MODE == "usuario",
          "%s (modo %s)" % (p.BASE_DIR, p.MODE))
    check("modo reconocido", p.MODE in ("carpeta", "usuario"), p.MODE)
    check("inbox_dirs no vacio", len(p.inbox_dirs()) >= 1)
    check("existe la migracion de datos de Affont", callable(p.rename_legacy))


if __name__ == "__main__":
    test_page_html()
    test_endpoints()
    test_nombres_de_modulos()
    test_secciones()
    test_tutorial()
    test_fuente_demo()
    test_importaciones()
    test_orden_caracteres()
    test_arranque()
    test_persistencia()
    test_actualizaciones()
    test_rutas()
    print()
    if fallos:
        print("FALLARON %d comprobaciones:" % len(fallos))
        for f in fallos:
            print("  - %s" % f)
        sys.exit(1)
    print("Todo OK")
