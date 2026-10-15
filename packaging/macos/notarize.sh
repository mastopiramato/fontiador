#!/usr/bin/env bash
# Firma y notariza el DMG de macOS.
#
#   APPLE_ID=... APPLE_TEAM_ID=... APPLE_APP_PASSWORD=... bash packaging/macos/notarize.sh
#
# Sin esto el DMG funciona, pero macOS muestra el aviso de "desarrollador no
# identificado" y hay que abrirlo con clic derecho la primera vez.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^APP_VERSION *= *"\([^"]*\)".*/\1/p' "$RAIZ/fontiador_server.py" | head -1)"
ARCH="${ARCH:-$(uname -m)}"
DMG="$RAIZ/dist/installer/Fontiador-$VERSION-macos-$ARCH.dmg"

: "${APPLE_ID:?Falta APPLE_ID}"
: "${APPLE_TEAM_ID:?Falta APPLE_TEAM_ID}"
: "${APPLE_APP_PASSWORD:?Falta APPLE_APP_PASSWORD}"
[ -f "$DMG" ] || { echo "No existe $DMG"; exit 1; }

echo "Notarizando $DMG ..."
xcrun notarytool submit "$DMG" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_PASSWORD" \
  --wait

echo "Engrapando el ticket a $DMG ..."
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

echo "Listo: $DMG notarizado y engrapado"
