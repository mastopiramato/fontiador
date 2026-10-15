# Instalación y compilación

Esta guía es para quien quiere compilar los instaladores o entender cómo se
distribuye la app. Si solo querés usarla, mirá el [README](../README.md).

## Resumen

| Sistema | Artefacto | Cómo se compila |
|---|---|---|
| Windows | `Fontiador-<v>-win-x64-setup.exe` | PyInstaller + Inno Setup |
| Linux | `.AppImage`, `.deb`, `.rpm` | PyInstaller + AppImageKit / dpkg / rpmbuild |

La app se empaqueta en **modo carpeta** (`--onedir`) y no en un único archivo:
un ejecutable de un solo archivo se descomprime en una carpeta temporal en cada
arranque, y además la app necesita encontrar sus carpetas `inbox/` y `output/`
junto al ejecutable.

> macOS queda **fuera** de este proyecto: no se empaqueta ni se publica para ese
> sistema.

## Compilar en Windows

```powershell
py -m pip install -r requirements.txt pyinstaller
py packaging\make_icon.py
py -m PyInstaller packaging\fontiador.spec --noconfirm --distpath dist --workpath build
iscc packaging\windows\fontiador.iss
```

El instalador queda en `dist\installer\`.

Para probarlo sin ensuciar tu instalación:

```powershell
$dest = "$env:TEMP\FontiadorTest"
.\dist\installer\Fontiador-<versión>-win-x64-setup.exe /VERYSILENT "/DIR=$dest"
```

**El instalador por usuario no borra los datos del usuario.** Al desinstalar se
elimina el programa, pero `inbox/`, `output/`, `fontiador_project.json` y
`fontiador.log` quedan donde estaban, para no destruir trabajo por accidente.

## Compilar en Linux

```bash
sudo apt-get install -y python3-gi gir1.2-webkit2-4.0 libfuse2 rpm
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller packaging/fontiador.spec --noconfirm
bash packaging/linux/build-appimage.sh
bash packaging/linux/build-packages.sh
```

El `.deb` instala en `/opt/fontiador` y deja un lanzador en `/usr/bin/fontiador` que
apunta los datos a `~/.local/share/Fontiador`, porque `/opt` es de solo lectura.

## Firma de código

Los artefactos salen **sin firmar** por ahora. En Windows, SmartScreen muestra
"Windows protegió tu PC" la primera vez.

El paso de firma ya está escrito en `.github/workflows/release.yml`, comentado.
Para activarlo alcanza con cargar los secretos `AZURE_TENANT_ID`,
`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` y las variables `SIGNING_ACCOUNT` y
`SIGNING_PROFILE`.

## Publicar una versión

Cada versión publicada es un conjunto nuevo de paquetes: las descargas de
`releases/latest` siempre apuntan a la última. Para publicar:

1. Subí la versión en todos lados de una sola vez:

   ```bash
   py packaging/subir_version.py 0.2.3 0.2.2
   ```

2. Commiteá y empujá el código.
3. Creá y empujá la etiqueta:

   ```bash
   git tag -a v0.2.3 -m "Fontiador 0.2.3" && git push origin v0.2.3
   ```

4. El flujo `Release` compila Windows y Linux, calcula `SHA256SUMS` y publica la
   versión con los cuatro paquetes adjuntos (`setup.exe`, `.AppImage`, `.deb` y
   `.rpm`).

Si hace falta recompilar una versión ya publicada sin volver a etiquetar,
se puede lanzar el flujo a mano (`workflow_dispatch`): toma la etiqueta a partir
de `APP_VERSION` y actualiza esa release en lugar de crear otra.

Conviene borrar las releases viejas cuando quedan obsoletas, para que nadie baje
por error un paquete con errores. Las etiquetas se pueden dejar.

## Pruebas

```bash
python tests/test_estructura.py     # página HTML, endpoints, guía, plantillas
python tests/test_construccion.py   # importa un export y construye una fuente
```

`test_construccion.py` redirige los datos a una carpeta temporal con
`FONTIADOR_DATA_DIR`, así que **no toca las fuentes del usuario**. Conviene mantener
esa regla en cualquier prueba nueva que construya fuentes.
