# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado de Fontiador con PyInstaller (modo carpeta, `--onedir`).

Se usa onedir y no onefile a propósito:
  * onefile se descomprime en una carpeta temporal en cada arranque (tarda y
    confunde al antivirus),
  * y sobre todo, en onefile `sys.executable` no es el directorio del usuario,
    con lo que la app no encontraría sus carpetas inbox/ y output/.

Para compilar:
    pyinstaller packaging/fontiador.spec --noconfirm
El resultado queda en dist/Fontiador/.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))

datas = []
binaries = []
hiddenimports = []

# Estas librerías cargan datos o submódulos por nombre en tiempo de ejecución,
# así que hay que incluirlas enteras.
for paquete in ("shapely", "fontTools", "webview", "potrace"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("shapely")
hiddenimports += ["fontiador_paths", "fontiador_builder"]

# Backends de ventana: solo se incluye lo que existe en esta plataforma.
for backend in ("webview.platforms.winforms", "webview.platforms.edgechromium",
                "webview.platforms.cocoa", "webview.platforms.gtk",
                "webview.platforms.qt", "webview.platforms.cef"):
    hiddenimports.append(backend)

# Recursos propios del proyecto (guías y plantillas de referencia).
for extra in ("docs", "templates", "packaging"):
    p = os.path.join(PROJECT_ROOT, extra)
    if os.path.isdir(p):
        datas.append((p, extra))

# Icono (si no existe, se compila sin icono). Solo Windows y Linux: macOS queda
# fuera de este proyecto.
ICONO = None
_ic = os.path.join(PROJECT_ROOT, "packaging", "icons", "fontiador.ico") \
    if sys.platform.startswith("win") else None
if _ic and os.path.exists(_ic):
    ICONO = _ic
    print("Icono:", ICONO)

a = Analysis(
    [os.path.join(PROJECT_ROOT, "fontiador_server.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Nada de esto hace falta y engorda el paquete.
        "tkinter", "matplotlib", "pytest", "IPython", "notebook",
        "PyQt5", "PyQt6", "PySide2", "wx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fontiador",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # aplicacion de ventana, sin consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICONO,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Fontiador",
)
