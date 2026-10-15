# Historial de cambios

Todas las versiones notables del proyecto. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado es
[SemVer](https://semver.org/lang/es/).

## [0.2.0] — 2026-10-15

Primera versión publicada.

### Añadido

- **Fontiador Demo**, una fuente de ejemplo lista para usar: una sans serif
  geométrica original, con los 103 caracteres del template y las tildes ya
  compuestas. Se descarga desde la pestaña *Importaciones*, con instrucciones de
  instalación para cada sistema, y sirve para ver cómo funciona una fuente
  terminada y para probar la app sin dibujar nada. No es Arial ni una copia de
  Arial: está dibujada desde cero en `packaging/generar_fuente_demo.py`.
- **Importaciones**, la pantalla de inicio: elegís el archivo desde la app con el
  diálogo del sistema (Windows, macOS y Linux), con guía paso a paso por programa
  (Affinity, Illustrator, Inkscape, Figma, CorelDRAW y otros), plantilla base
  descargable en SVG y PNG, correspondencia celda por celda y estado de las
  carpetas vigiladas.
- **Tutoriales animados** en cada sección, que se muestran la primera vez y se
  pueden repetir con el botón **?**. Se pueden restablecer desde *Conjuntos*.
- **Buscar actualizaciones** en la pestaña *Fuente*, con la versión actual, el
  enlace de descarga y las notas del cambio. Consulta la última release publicada
  y no rompe nada si no hay conexión.
- Instaladores y paquetes: instalador por usuario para Windows (Inno Setup),
  DMG para macOS (arm64 e Intel) y AppImage, `.deb` y `.rpm` para Linux.
- Flujos de GitHub Actions: integración continua en los tres sistemas y
  publicación automática al etiquetar una versión.
- Guía de instalación y compilación en `docs/INSTALACION.md`.
- Página de inicio del proyecto en `docs/index.html`.
- Pruebas: estructura de la página y los endpoints, y construcción de una fuente
  de punta a punta en una carpeta temporal.

### Corregido

- Las curvas de un JSON de exportación se perdían: el constructor de fuentes
  aplanaba todos los contornos a segmentos, con lo que los círculos salían
  deformes y los glifos con contrapunzón (la O, la a, el 8) podían quedar vacíos
  o como un manchón relleno. Ahora los comandos M/L/C/Q se usan tal cual.
- **La app moría en silencio si el puerto 8765 estaba ocupado.** Ahora pide un
  puerto libre al sistema y lo informa. Además, `stdout`/`stderr` van al registro
  siempre que la app esté empaquetada, y cualquier fallo de arranque se registra
  y se muestra en un cuadro de diálogo en vez de desaparecer sin rastro.
- Un proyecto guardado con BOM (por ejemplo desde el Bloc de notas) hacía que la
  app empezara de cero en silencio. Ahora se lee correctamente, y un archivo
  realmente dañado se conserva como copia en vez de descartarse.
- La app solo se servía en la ruta exacta `/`, así que cualquier dirección con
  parámetros daba 404.
- Los mensajes de error al importar explican qué hacer, no solo qué falló.
- En macOS y Linux, los scripts de empaquetado usaban `grep -oP`, que no existe
  en BSD grep.

### Notas

- Los artefactos todavía **no están firmados**: Windows SmartScreen avisa la
  primera vez y en macOS hay que abrir la app con clic derecho → Abrir.

[0.2.0]: https://github.com/mastopiramato/fontiador/releases/tag/v0.2.0
