#!/usr/bin/env bash
# Arma Fontiador.app y un DMG a partir de dist/Fontiador (salida de PyInstaller).
#
#   bash packaging/macos/build-dmg.sh
#
# La variable ARCH (arm64 | x86_64) decide el nombre del DMG.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^APP_VERSION *= *"\([^"]*\)".*/\1/p' "$RAIZ/fontiador_server.py" | head -1)"
APP="$RAIZ/dist/Fontiador"
SALIDA="$RAIZ/dist/installer"
ARCH="${ARCH:-$(uname -m)}"
BUNDLE_ID="io.github.mastopiramato.fontiador"

echo "Version: $VERSION  Arquitectura: $ARCH"
[ -d "$APP" ] || { echo "Falta $APP: ejecuta antes pyinstaller packaging/fontiador.spec"; exit 1; }
mkdir -p "$SALIDA"

APPDIR="$RAIZ/build/Fontiador.app"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/Contents/MacOS" "$APPDIR/Contents/Resources"

# ------------------------------------------------------------------ .icns
ICNS="$RAIZ/packaging/icons/fontiador.icns"
if [ ! -f "$ICNS" ]; then
  ICONSET="$RAIZ/build/fontiador.iconset"
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for s in 16 32 64 128 256 512; do
    sips -z $s $s "$RAIZ/packaging/icons/fontiador-512.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2))
    sips -z $d $d "$RAIZ/packaging/icons/fontiador-512.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$ICNS"
fi
cp "$ICNS" "$APPDIR/Contents/Resources/fontiador.icns"

# ------------------------------------------------------------- contenido
cp -r "$APP/." "$APPDIR/Contents/MacOS/"
chmod +x "$APPDIR/Contents/MacOS/Fontiador"

cat > "$APPDIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Fontiador</string>
  <key>CFBundleDisplayName</key><string>Fontiador</string>
  <key>CFBundleExecutable</key><string>Fontiador</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>fontiador.icns</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSRequiresAquaSystemAppearance</key><false/>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>Proyecto de Fontiador</string>
      <key>CFBundleTypeExtensions</key><array><string>fontiadorproj</string></array>
      <key>CFBundleTypeRole</key><string>Editor</string>
    </dict>
  </array>
</dict>
</plist>
EOF

# Un .app sin firmar con cuarentena no arranca: se firma ad-hoc para que al
# menos funcione en la maquina que lo compilo y en las pruebas.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APPDIR" 2>/dev/null || \
    echo "Aviso: no se pudo firmar ad-hoc (seguirá funcionando igual)"
fi

# ------------------------------------------------------------------ DMG
STAGE="$RAIZ/build/dmg"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APPDIR" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

DMG="$SALIDA/Fontiador-$VERSION-macos-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "Fontiador $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"

echo "Listo: $DMG"
ls -lh "$DMG"
