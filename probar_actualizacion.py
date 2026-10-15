"""Abre la app haciendo de cuenta que es una versión vieja.

Sirve para probar el botón de actualizar sin esperar a que salga una versión
nueva: la app cree que tiene la versión que le digas, así la última publicada
cuenta como nueva y se puede probar la descarga y la instalación de punta a punta.

    py probar_actualizacion.py            (se hace pasar por la 0.2.0)
    py probar_actualizacion.py 0.2.5      (se hace pasar por la 0.2.5)

Usa una carpeta de datos aparte, así no toca tu proyecto ni tus fuentes.
"""

import os
import sys
import tempfile

# Tiene que estar puesto ANTES de importar el servidor.
simulada = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "0.2.0"
os.environ["FONTIADOR_VERSION_SIMULADA"] = simulada
os.environ.setdefault("FONTIADOR_DATA_DIR", tempfile.mkdtemp(prefix="fontiador_prueba_"))

sys.argv = ["fontiador_server.py", "--port", "8797"]

import fontiador_server  # noqa: E402

print("")
print("  Modo de prueba: la app dice tener la version %s." % simulada)
print("  La ultima publicada va a aparecer como nueva.")
print("  Los datos van a %s" % os.environ["FONTIADOR_DATA_DIR"])
print("")

fontiador_server.main()
