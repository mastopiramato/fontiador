"""Importaciones: abrir archivos desde la app y describir el formato esperado.

Dos responsabilidades:

1. **Selector de archivos nativo.** Hasta ahora la única entrada era copiar el
   archivo a mano dentro de ``inbox/``. Acá se abre el diálogo del sistema y se
   devuelve la ruta elegida. Se usan los diálogos que ya trae el sistema
   (PowerShell en Windows, osascript en macOS, zenity/kdialog en Linux) en vez de
   ``webview.create_file_dialog`` porque ese diálogo tiene que abrirse desde el
   hilo principal de la ventana, y las peticiones HTTP corren en otro hilo.

2. **Contrato del formato.** La rejilla de celdas (10 columnas de 1000x1000 px,
   línea base a 800) y el orden de los 103 caracteres se exponen como datos para
   poder mostrarlos en la interfaz y generar la plantilla descargable.
"""

import os
import subprocess
import sys

# Filtros del diálogo por sistema operativo.
_EXT_PNG = [".png", ".jpg", ".jpeg", ".svg", ".json"]
_EXT_JSON = [".json"]


def platform_name():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def dialog_available():
    """¿Hay algún mecanismo de diálogo disponible en este sistema?"""
    plat = platform_name()
    if plat == "windows":
        return True  # PowerShell siempre está en Windows
    if plat == "macos":
        return os.path.exists("/usr/bin/osascript")
    for exe in ("zenity", "kdialog", "yad"):
        if _which(exe):
            return True
    return False


def _which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, name)
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def _run(cmd, timeout=300):
    """Ejecuta y devuelve la salida, sin dejar restos si el usuario cancela."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout or "").strip()


def _clean(path):
    """Normaliza la ruta y descarta lo que no sea un archivo real."""
    if not path:
        return None
    path = path.strip().strip('"').strip("'")
    if not path:
        return None
    path = os.path.abspath(os.path.expanduser(path))
    return path if os.path.isfile(path) else None


def pick_file(mode="render"):
    """Abre el diálogo de archivo del sistema y devuelve la ruta o None.

    ``mode`` es ``"render"`` (imagen, SVG o JSON) o ``"json"`` (solo JSON).
    """
    plat = platform_name()
    if mode == "json":
        titulo = "Elegí el archivo export_*.json"
    else:
        titulo = "Elegí el render o la exportación de glifos"

    if plat == "windows":
        if mode == "json":
            filtro = "Exportación de glifos (*.json)|*.json|Todos los archivos (*.*)|*.*"
        else:
            filtro = ("Render o exportación (*.png;*.jpg;*.jpeg;*.svg;*.json)|*.png;*.jpg;*.jpeg;*.svg;*.json|"
                      "Imágenes (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg|"
                      "Vectorial (*.svg)|*.svg|Exportación de glifos (*.json)|*.json|"
                      "Todos los archivos (*.*)|*.*")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = '%s'; "
            "$d.Filter = '%s'; "
            "$d.Multiselect = $false; "
            "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.FileName }"
        ) % (titulo.replace("'", "''"), filtro.replace("'", "''"))
        return _clean(_run(["powershell", "-NoProfile", "-STA", "-Command", ps]))

    if plat == "macos":
        # osascript devuelve la ruta con "alias" con formato HFS; se convierte a POSIX.
        script = (
            'set f to choose file with prompt "%s"\n'
            'return POSIX path of f' % titulo
        )
        return _clean(_run(["osascript", "-e", script]))

    # Linux: zenity, kdialog o yad, segun lo que haya instalado.
    zenity = _which("zenity")
    if zenity:
        cmd = [zenity, "--file-selection", "--title=" + titulo]
        if mode == "json":
            cmd.append("--file-filter=Exportación de glifos | *.json")
        else:
            cmd.append("--file-filter=Render o exportación | *.png *.jpg *.jpeg *.svg *.json")
        return _clean(_run(cmd))
    kdialog = _which("kdialog")
    if kdialog:
        filtro = "*.json" if mode == "json" else "*.png *.jpg *.jpeg *.svg *.json"
        return _clean(_run([kdialog, "--getopenfilename", os.path.expanduser("~"), filtro,
                            "--title", titulo]))
    yad = _which("yad")
    if yad:
        return _clean(_run([yad, "--file", "--title=" + titulo]))
    return None


def pick_many(mode="render"):
    """Igual que pick_file pero permite elegir varios (Windows y Linux/zenity)."""
    plat = platform_name()
    titulo = "Elegí uno o varios archivos para importar"
    if plat == "windows":
        filtro = ("Render o exportación (*.png;*.jpg;*.jpeg;*.svg;*.json)|*.png;*.jpg;*.jpeg;*.svg;*.json|"
                  "Todos los archivos (*.*)|*.*")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            "$d.Title = '%s'; $d.Filter = '%s'; $d.Multiselect = $true; "
            "if ($d.ShowDialog() -eq 'OK') { $d.FileNames | ForEach-Object { Write-Output $_ } }"
        ) % (titulo, filtro)
        out = _run(["powershell", "-NoProfile", "-STA", "-Command", ps]) or ""
        return [p for p in (_clean(l) for l in out.splitlines()) if p]

    if plat == "macos":
        # osascript puede devolver varias rutas separadas por salto de linea.
        script = (
            'set fs to choose file with prompt "%s" with multiple selections allowed\n'
            'set out to ""\n'
            'repeat with f in fs\n'
            'set out to out & (POSIX path of f) & linefeed\n'
            'end repeat\n'
            'return out' % titulo
        )
        out = _run(["osascript", "-e", script]) or ""
        return [p for p in (_clean(l) for l in out.splitlines()) if p]

    zenity = _which("zenity")
    if zenity:
        out = _run([zenity, "--file-selection", "--multiple", "--separator=\n",
                    "--title=" + titulo,
                    "--file-filter=Render o exportación | *.png *.jpg *.jpeg *.svg *.json"]) or ""
        return [p for p in (_clean(l) for l in out.splitlines()) if p]

    one = pick_file(mode)
    return [one] if one else []


def order_reference(template_chars, cols, cell):
    """Mapa posición -> carácter, para mostrar el orden esperado en la interfaz.

    Devuelve una lista de filas; cada fila es una lista de diccionarios con el
    índice global, la fila y la columna (1-based) y el carácter.
    """
    filas = []
    for i, ch in enumerate(template_chars):
        r, c = divmod(i, cols)
        while len(filas) <= r:
            filas.append([])
        filas[r].append({"i": i + 1, "fila": r + 1, "col": c + 1, "char": ch,
                         "x": c * cell, "y": r * cell})
    return filas


def describe_file(path):
    """Clasifica un archivo elegido para que la interfaz diga qué va a pasar."""
    ext = os.path.splitext(path)[1].lower()
    base = os.path.basename(path)
    if ext == ".json":
        return {"tipo": "vectores", "ext": ext,
                "detalle": "Exportación JSON de glifos: se importan los contornos tal cual, "
                           "sin re-trazar. Es la vía de mayor calidad."}
    if ext == ".svg":
        return {"tipo": "vectorial", "ext": ext,
                "detalle": "SVG: hoy se procesa como imagen rasterizada en la rejilla. "
                           "Para vectores exactos conviene exportar JSON."}
    if ext in (".png", ".jpg", ".jpeg"):
        return {"tipo": "render", "ext": ext,
                "detalle": "Imagen de la rejilla: se recorta celda por celda y se traza cada glifo."}
    return {"tipo": "desconocido", "ext": ext,
            "detalle": "Extensión no reconocida: la importación probablemente falle."}


def watched_state(inbox_dirs):
    """Resumen del contenido de las carpetas vigiladas, para mostrarlo en la interfaz."""
    carpetas = []
    for d in inbox_dirs:
        try:
            archivos = sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
        except OSError:
            archivos = []
        sub = {}
        for nombre in ("procesado", "errores"):
            p = os.path.join(d, nombre)
            try:
                sub[nombre] = sorted(f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f)))
            except OSError:
                sub[nombre] = []
        carpetas.append({"ruta": d, "pendientes": archivos,
                         "procesado": sub["procesado"], "errores": sub["errores"]})
    return carpetas
