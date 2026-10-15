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
.\dist\installer\Fontiador-0.2.1-win-x64-setup.exe /VERYSILENT "/DIR=$dest"
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

1. Actualizá `APP_VERSION` en `fontiador_server.py` y la versión en
   `packaging/windows/fontiador.iss`.
2. `git tag v0.2.1 && git push origin v0.2.1`
3. El flujo `Release` compila las tres plataformas, calcula `SHA256SUMS` y crea
   un borrador de release con los artefactos adjuntos.

## Pruebas

```bash
python tests/test_estructura.py     # página HTML, endpoints, guía, plantillas
python tests/test_construccion.py   # importa un export y construye una fuente
```

`test_construccion.py` redirige los datos a una carpeta temporal con
`FONTIADOR_DATA_DIR`, así que **no toca las fuentes del usuario**. Conviene mantener
esa regla en cualquier prueba nueva que construya fuentes.
