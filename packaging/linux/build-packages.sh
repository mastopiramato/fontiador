#!/usr/bin/env bash
# Genera el .deb y el .rpm de Fontiador a partir de dist/Fontiador.
#
#   bash packaging/linux/build-packages.sh
#
# Usa dpkg-deb (si esta) y rpmbuild (si esta). Si no hay rpmbuild, solo hace el .deb.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^APP_VERSION *= *"\([^"]*\)".*/\1/p' "$RAIZ/fontiador_server.py" | head -1)"
APP="$RAIZ/dist/Fontiador"
SALIDA="$RAIZ/dist/installer"
NOMBRE="fontiador"
ARQ="amd64"

[ -d "$APP" ] || { echo "Falta $APP: ejecuta antes pyinstaller packaging/fontiador.spec"; exit 1; }
mkdir -p "$SALIDA"

echo "Version: $VERSION"

# ------------------------------------------------------------------ .deb
if command -v dpkg-deb >/dev/null 2>&1; then
  STAGE="$RAIZ/build/deb"
  rm -rf "$STAGE"
  mkdir -p "$STAGE/DEBIAN" \
           "$STAGE/opt/$NOMBRE" \
           "$STAGE/usr/bin" \
           "$STAGE/usr/share/applications" \
           "$STAGE/usr/share/icons/hicolor/256x256/apps"

  cp -r "$APP/." "$STAGE/opt/$NOMBRE/"
  cp "$RAIZ/packaging/icons/fontiador.png" "$STAGE/usr/share/icons/hicolor/256x256/apps/fontiador.png"

  # Lanzador que fija el directorio de trabajo (la app escribe inbox/ y output/)
  cat > "$STAGE/usr/bin/$NOMBRE" <<EOF
#!/bin/sh
# Los datos van a la carpeta del usuario para no pelear con los permisos de /opt
export FONTIADOR_DATA_DIR="\${FONTIADOR_DATA_DIR:-\$HOME/.local/share/Fontiador}"
mkdir -p "\$FONTIADOR_DATA_DIR"
exec /opt/$NOMBRE/Fontiador "\$@"
EOF
  chmod 755 "$STAGE/usr/bin/$NOMBRE"

  cat > "$STAGE/usr/share/applications/fontiador.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fontiador
Comment=Genera fuentes OpenType desde exportaciones de programas de diseño
Exec=$NOMBRE
Icon=fontiador
Terminal=false
Categories=Graphics;VectorGraphics;
Keywords=font;tipografia;fuente;otf;
EOF

  TAM=$(du -sk "$STAGE" | cut -f1)
  cat > "$STAGE/DEBIAN/control" <<EOF
Package: $NOMBRE
Version: $VERSION
Section: graphics
Priority: optional
Architecture: $ARQ
Installed-Size: $TAM
Maintainer: mastopiramato <luziriarte.su@gmail.com>
Homepage: https://github.com/mastopiramato/fontiador
Description: Generador de fuentes OpenType desde programas de diseno
 Fontiador toma la exportacion de una rejilla de glifos hecha en Affinity,
 Illustrator, Inkscape, Figma o CorelDRAW y construye una fuente OpenType,
 con herramientas para dimensiones, kerning, tildes y conjuntos de caracteres.
EOF

  cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ -x "$(command -v update-desktop-database)" ]; then
  update-desktop-database -q || true
fi
exit 0
EOF
  chmod 755 "$STAGE/DEBIAN/postinst"

  dpkg-deb --build --root-owner-group "$STAGE" "$SALIDA/${NOMBRE}_${VERSION}_${ARQ}.deb"
  echo "Listo: $SALIDA/${NOMBRE}_${VERSION}_${ARQ}.deb"
else
  echo "Sin dpkg-deb: no se genera el .deb"
fi

# ------------------------------------------------------------------ .rpm
if command -v rpmbuild >/dev/null 2>&1; then
  TOP="$RAIZ/build/rpm"
  # Se prepara todo en una carpeta aparte y NO en %{buildroot}: rpmbuild ya crea
  # su propio buildroot por version, y si se copia desde adentro de el mismo,
  # falla con "cannot copy a directory into itself".
  ORIGEN="$TOP/origen"
  rm -rf "$TOP"
  mkdir -p "$TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
  mkdir -p "$ORIGEN/opt/$NOMBRE" \
           "$ORIGEN/usr/bin" \
           "$ORIGEN/usr/share/applications" \
           "$ORIGEN/usr/share/icons/hicolor/256x256/apps"

  cp -r "$APP/." "$ORIGEN/opt/$NOMBRE/"
  cp "$RAIZ/packaging/icons/fontiador.png" "$ORIGEN/usr/share/icons/hicolor/256x256/apps/fontiador.png"

  # El lanzador y el acceso directo se reutilizan de lo que armó el .deb; si no
  # se generó, se escriben igual.
  if [ -f "$STAGE/usr/bin/$NOMBRE" ]; then
    cp "$STAGE/usr/bin/$NOMBRE" "$ORIGEN/usr/bin/$NOMBRE"
  else
    cat > "$ORIGEN/usr/bin/$NOMBRE" <<EOF
#!/bin/sh
export FONTIADOR_DATA_DIR="\${FONTIADOR_DATA_DIR:-\$HOME/.local/share/Fontiador}"
mkdir -p "\$FONTIADOR_DATA_DIR"
exec /opt/$NOMBRE/Fontiador "\$@"
EOF
    chmod 755 "$ORIGEN/usr/bin/$NOMBRE"
  fi
  if [ -f "$STAGE/usr/share/applications/fontiador.desktop" ]; then
    cp "$STAGE/usr/share/applications/fontiador.desktop" "$ORIGEN/usr/share/applications/"
  fi

  cat > "$TOP/SPECS/$NOMBRE.spec" <<EOF
Name:           $NOMBRE
Version:        $VERSION
Release:        1
Summary:        Generador de fuentes OpenType desde programas de diseno
License:        MIT
URL:            https://github.com/mastopiramato/fontiador
BuildArch:      x86_64
AutoReqProv:    no

%description
Fontiador toma la exportacion de una rejilla de glifos y construye una fuente
OpenType, con herramientas para dimensiones, kerning, tildes y conjuntos.

%install
mkdir -p %{buildroot}
cp -r $ORIGEN/. %{buildroot}/

%files
/opt/$NOMBRE
/usr/bin/$NOMBRE
/usr/share/applications/fontiador.desktop
/usr/share/icons/hicolor/256x256/apps/fontiador.png
EOF

  rpmbuild --define "_topdir $TOP" -bb "$TOP/SPECS/$NOMBRE.spec"
  find "$TOP/RPMS" -name '*.rpm' -exec cp {} "$SALIDA/" \;
  echo "Listo: $(ls "$SALIDA"/*.rpm 2>/dev/null || echo 'sin rpm')"
else
  echo "Sin rpmbuild: no se genera el .rpm"
fi

ls -lh "$SALIDA" 2>/dev/null || true
