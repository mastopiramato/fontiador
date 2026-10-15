#!/usr/bin/env bash
# Arma un AppImage portable de Fontiador a partir de dist/Fontiador (salida de PyInstaller).
#
#   bash packaging/linux/build-appimage.sh
#
# Genera dist/installer/Fontiador-<version>-x86_64.AppImage
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^APP_VERSION *= *"\([^"]*\)".*/\1/p' "$RAIZ/fontiador_server.py" | head -1)"
APP="$RAIZ/dist/Fontiador"
SALIDA="$RAIZ/dist/installer"
APPID="io.github.mastopiramato.fontiador"

echo "Version detectada: $VERSION"
[ -d "$APP" ] || { echo "Falta $APP: ejecuta antes pyinstaller packaging/fontiador.spec"; exit 1; }

APPDIR="$RAIZ/build/Fontiador.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" "$APPDIR/usr/share/metainfo"

# La aplicacion completa va a usr/bin
cp -r "$APP/." "$APPDIR/usr/bin/"

# Icono y descriptor de escritorio
cp "$RAIZ/packaging/icons/fontiador.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/fontiador.png"
cp "$RAIZ/packaging/icons/fontiador.png" "$APPDIR/fontiador.png"

cat > "$APPDIR/usr/share/applications/fontiador.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fontiador
Comment=Genera fuentes OpenType desde exportaciones de programas de diseño
Exec=Fontiador
Icon=fontiador
Terminal=false
Categories=Graphics;VectorGraphics;
Keywords=font;tipografia;fuente;otf;affinity;
StartupWMClass=Fontiador
EOF
cp "$APPDIR/usr/share/applications/fontiador.desktop" "$APPDIR/fontiador.desktop"

cat > "$APPDIR/usr/share/metainfo/$APPID.appdata.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>$APPID</id>
  <name>Fontiador</name>
  <summary>Genera fuentes OpenType desde exportaciones de programas de diseño</summary>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>MIT</project_license>
  <url type="homepage">https://github.com/mastopiramato/fontiador</url>
  <description>
    <p>Fontiador toma la exportación de una rejilla de glifos hecha en Affinity, Illustrator,
    Inkscape, Figma o CorelDRAW y genera una fuente OpenType, con herramientas para ajustar
    dimensiones, kerning, tildes y conjuntos de caracteres.</p>
  </description>
  <launchable type="desktop-id">fontiador.desktop</launchable>
  <releases><release version="$VERSION" date="$(date +%Y-%m-%d)"/></releases>
</component>
EOF

# AppRun: apunta al ejecutable real
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
AQUI="$(dirname "$(readlink -f "$0")")"
exec "$AQUI/usr/bin/Fontiador" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Herramienta de empaquetado
TOOL="$RAIZ/build/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
  echo "Descargando appimagetool..."
  curl -fsSL -o "$TOOL" \
    https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi

mkdir -p "$SALIDA"
export ARCH=x86_64
# --appimage-extract-and-run evita necesitar FUSE en el runner de CI
"$TOOL" --appimage-extract-and-run \
  "$APPDIR" "$SALIDA/Fontiador-$VERSION-x86_64.AppImage"

echo "Listo: $SALIDA/Fontiador-$VERSION-x86_64.AppImage"
ls -lh "$SALIDA"/*.AppImage
