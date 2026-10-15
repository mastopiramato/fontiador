"""Rutas de trabajo de Fontiador.

La app puede vivir en dos modos:

* **Modo carpeta** (portable): si el directorio del ejecutable es escribible, todo
  (inbox, output, proyecto, log) se guarda ahí al lado. Es el comportamiento de
  siempre y sirve para una carpeta compartida o un pendrive.
* **Modo instalado**: en una instalación de sistema el directorio del ejecutable
  puede ser de solo lectura (por ejemplo ``/Applications`` en macOS o
  ``/usr/lib`` en Linux). En ese caso los datos van a la carpeta de datos del
  usuario que corresponda al sistema.

La detección es por prueba real de escritura, no por sistema operativo: así
funciona igual en Windows, macOS y Linux sin ramas especiales.
"""

import os
import sys

APP_NAME = "Fontiador"
PORTABLE_FLAG = "fontiador_portable.flag"


def _exe_dir():
    """Directorio donde vive el ejecutable (congelado) o el código fuente.

    fontiador_paths.py está en la raíz del proyecto, así que en modo código fuente
    la raíz es el directorio que lo contiene, no su padre.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _user_data_dir():
    """Carpeta de datos del usuario segun la plataforma, sin dependencias externas."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/" + APP_NAME)
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME)


def _is_writable(path):
    """Comprueba de verdad que se puede escribir: crear y borrar un archivo."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".fontiador_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def resolve_dirs():
    """Devuelve (base, modo) eligiendo una carpeta base que sea escribible.

    ``modo`` es ``"carpeta"`` para la instalación portable y ``"usuario"`` cuando
    hubo que caer a la carpeta de datos del usuario.
    """
    exe = _exe_dir()
    forced = os.environ.get("FONTIADOR_DATA_DIR")
    if forced:
        return forced, "usuario"
    # Un archivo marcador fuerza el modo carpeta aunque el directorio no sea escribible,
    # para dejar claro al usuario por que la app no arranca como espera.
    if _is_writable(exe):
        return exe, "carpeta"
    data = _user_data_dir()
    if _is_writable(data):
        return data, "usuario"
    # Ultimo recurso: usar el directorio del ejecutable igual y dejar que falle con un
    # mensaje claro mas adelante, en vez de arrancar con una ruta inexistente.
    return exe, "carpeta"


BASE_DIR, MODE = resolve_dirs()

INBOX_DIR = os.path.join(BASE_DIR, "inbox")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PROJECT_FILE = os.path.join(BASE_DIR, "fontiador_project.json")
LOG_FILE = os.path.join(BASE_DIR, "fontiador.log")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# En modo usuario la app no puede ver los archivos que el usuario dejo junto al
# ejecutable, asi que tambien se vigila esa carpeta para no romper el flujo de
# "copiar el render al lado de la app".
EXTRA_INBOX = os.path.join(_exe_dir(), "inbox") if MODE == "usuario" else None

FROZEN = bool(getattr(sys, "frozen", False))


def inbox_dirs():
    """Carpetas que se vigilan, en orden de prioridad."""
    out = []
    for d in (INBOX_DIR, EXTRA_INBOX, os.path.join(BASE_DIR, "dist", "inbox")):
        if not d:
            continue
        d = os.path.normpath(d)
        if d not in out and (d == os.path.normpath(INBOX_DIR) or os.path.isdir(d)):
            out.append(d)
    return out


def rename_legacy():
    """Renombra los archivos de datos de la etapa "affont" a "fontiador".

    La app se llamó Affont antes de llamarse Fontiador. Sin esto, quien ya la
    tenía instalada abriría con el proyecto en blanco y no encontraría sus
    fuentes ni su registro. Se llama una sola vez al arrancar.
    """
    cambios = []
    pares = [
        (os.path.join(_exe_dir(), "affont_project.json"), PROJECT_FILE),
        (os.path.join(_exe_dir(), "affont.log"), LOG_FILE),
        (os.path.join(BASE_DIR, "affont_project.json"), PROJECT_FILE),
        (os.path.join(BASE_DIR, "affont.log"), LOG_FILE),
    ]
    for viejo, nuevo in pares:
        try:
            if os.path.exists(viejo) and not os.path.exists(nuevo):
                os.replace(viejo, nuevo)
                cambios.append(os.path.basename(nuevo))
        except OSError:
            pass
    return cambios


def ensure_dirs():
    """Crea las carpetas de trabajo y devuelve un resumen legible."""
    for d in (BASE_DIR, INBOX_DIR, OUTPUT_DIR, TEMPLATES_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    return BASE_DIR


def describe():
    """Linea de diagnostico para el log y la pestana Importaciones."""
    origen = "instalacion" if FROZEN else "codigo fuente"
    modo = "carpeta de la app (portable)" if MODE == "carpeta" else "carpeta de datos del usuario"
    return "Datos: %s [%s, %s]" % (BASE_DIR, modo, origen)
