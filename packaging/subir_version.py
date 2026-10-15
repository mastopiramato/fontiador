"""Sube la version del proyecto en todos los lugares donde figura.

    py _subir_version.py 0.2.2

Uso: cada vez que se quiera publicar, se sube la version, se commitea y se
empuja la etiqueta. El flujo de release compila y publica los paquetes.
"""

import re
import sys

NUEVA = sys.argv[1] if len(sys.argv) > 1 else "0.2.1"
ANTERIOR = sys.argv[2] if len(sys.argv) > 2 else "0.2.0"

CAMBIOS = [
    ("fontiador_server.py", [('APP_VERSION = "%s"' % ANTERIOR, 'APP_VERSION = "%s"' % NUEVA)]),
    ("packaging/windows/fontiador.iss", [('#define MiVersion    "%s"' % ANTERIOR,
                                          '#define MiVersion    "%s"' % NUEVA)]),
    ("docs/index.html", [
        ("versión %s" % ANTERIOR, "versión %s" % NUEVA),
        ("Fontiador-%s-win-x64-setup.exe" % ANTERIOR,
         "Fontiador-%s-win-x64-setup.exe" % NUEVA),
        ("Fontiador-%s-x86_64.AppImage" % ANTERIOR,
         "Fontiador-%s-x86_64.AppImage" % NUEVA),
    ]),
    ("docs/INSTALACION.md", [("0.2.0", NUEVA)]),
    ("README.md", [("Affont-%s" % ANTERIOR, "Fontiador-%s" % NUEVA)]),
]

for ruta, pares in CAMBIOS:
    try:
        t = open(ruta, encoding="utf-8").read()
    except OSError:
        print("  falta: %s" % ruta)
        continue
    antes = t
    for viejo, nuevo in pares:
        t = t.replace(viejo, nuevo)
    if t != antes:
        open(ruta, "w", encoding="utf-8", newline="\n").write(t)
        print("  %-34s actualizado" % ruta)
    else:
        print("  %-34s sin cambios" % ruta)

t = open("fontiador_server.py", encoding="utf-8").read()
m = re.search(r'APP_VERSION = "([^"]+)"', t)
print("\nAPP_VERSION ahora: %s" % (m.group(1) if m else "?"))
