# Historial de cambios

Todas las versiones notables del proyecto. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado es
[SemVer](https://semver.org/lang/es/).

﻿﻿﻿## [0.2.6] — 2026-10-16

### Añadido

- **La actualización se descarga e instala desde la app**, con barra de progreso:
  *Buscar actualizaciones* (en Inicio → Versión) ofrece **Descargar e instalar**
  y, al terminar, **Instalar y reiniciar**. En Windows corre el instalador y
  reinicia la app; en Linux reemplaza el AppImage (o abre el paquete del
  sistema).

### Corregido

- **La comprobación de actualizaciones ya no usa la API de GitHub.** Sin
  credenciales permite 60 consultas por hora y responde 403 enseguida, con lo
  que la app decía "El repositorio respondió 403". Ahora se leen dos direcciones
  normales del sitio (la redirección de `releases/latest` y la página que lista
  los adjuntos), que no tienen ese límite.

### Cambiado

- **Fuente**: se fueron el botón *Restablecer tutoriales* y la pestaña
  *Avanzado*. Los conjuntos de caracteres se ven siempre, sin botón.
- **Dimensiones**: la caja de ajustes ocupa el ancho que sobra y los
  deslizadores van en dos columnas, así entran todos sin recortes.
- **Kerning**: *Kerning manual* · *Kerning base* · *Pares guardados* (la tabla de
  pares pasó a su propia solapa). Las dos primeras comparten diseño: el
  visualizador a la izquierda y los controles a la derecha.
- Las instrucciones ya no nombran teclas: los atajos se muestran aparte, con más
  aire entre uno y otro y con la explicación sin recuadro y en cursiva.

## [0.2.5] — 2026-10-16

### Cambiado

- **Pestañas en lugar de paneles que crecían.** Antes, abrir un bloque estiraba
  la página y aparecía la barra de scroll; ahora las pestañas cambian en el mismo
  lugar y el cuerpo se desplaza por dentro. Con esto, ninguna de las seis
  secciones necesita scroll de página, ni siquiera con la pestaña abierta.
  - *Dimensiones*: Ajustes · Trazado del pincel · Comparar tamaños
  - *Inicio*: Registro · Formato · Versión
  - *Fuente*: Conjuntos · Avanzado
- **La página Registro desapareció**: el registro es ahora una pestaña de Inicio.
- **Inicio se enfoca en la plantilla**: se fueron *Carpetas vigiladas* y
  *Correspondencia de cada celda*, y el detalle del formato pasó a una pestaña,
  dejando a la vista la descarga de la plantilla.
- **Atajos de teclado**: ahora se distinguen las teclas de lo que hacen. Cada
  atajo va aparte, las teclas llevan recuadro y la explicación va sin borde y en
  otro color.
- **Barra lateral**: se quitó el contador de glifos.
- Atajos nuevos: **Alt+↑ / Alt+↓** cambian de pestaña dentro de la sección.

### Corregido

- La barra de progreso del trabajo no se mostraba: había quedado detrás de un
  elemento que ya no existe.

## [0.2.4] — 2026-10-16

### Cambiado

- **Ninguna sección necesita scroll.** Los bloques que no se usan todo el tiempo
  ahora son **paneles plegables**, cerrados por defecto: *Trazado del pincel* y
  *Comparar tamaños* en Dimensiones, y *Formato de la rejilla*,
  *Correspondencia de cada celda* y *Carpetas vigiladas* en Inicio.
  En una ventana de 1280x800 las siete secciones entran sin barra de scroll.
- **Buscar actualizaciones** pasó de *Fuente* a *Inicio*, junto a la versión.
  Fuente quedó solo con lo que se usa al construir.
- El encabezado de Inicio es más directo: la zona para elegir el archivo primero,
  sin el párrafo introductorio.

### Añadido

- Atajos para los paneles: **Alt+↑ / Alt+↓** pasa de uno a otro y lo abre,
  **Alt+Enter** abre o cierra el primero de la sección. Las flechas verticales
  con modificador ya no cambian de sección: para eso están **Ctrl+← / Ctrl+→**,
  que evita el choque entre ambos.

## [0.2.3] — 2026-10-16

### Cambiado

- **Conjuntos de caracteres** pasó a estar dentro de *Fuente*, que es donde se
  usa. La pestaña *Conjuntos* ya no existe.
- **Tildes** se movió arriba de *Palabras* en el menú.
- La barra lateral ya no repite el estado de las carpetas (vigilando, revisión y
  pendientes): esa información está en *Inicio*.
- Los **atajos de teclado** se muestran como fichas iguales a las del menú, y
  cada sección tiene las suyas (por ejemplo, *Enter* para aplicar en Kerning).
- Las **rejillas de Kerning** tienen el mismo filtro por categoría que
  *Dimensiones*: mayúsculas, minúsculas, números, puntuación, especiales, tildes.

## [0.2.2] — 2026-10-15

### Corregido

- La app **instalada** no mostraba ningún tutorial: `tutorial.json` no viajaba
  dentro del paquete. Ahora se incluye, y la búsqueda de recursos propios
  contempla la carpeta del paquete además de la raíz del proyecto.
- La **fuente de ejemplo** daba 404 en la app instalada por el mismo motivo:
  se la buscaba en la carpeta de datos del usuario, cuando viaja dentro del
  paquete. Se unifica en `fontiador_paths.buscar_recurso()`, que prueba la
  carpeta de datos, la del paquete y la del proyecto, en ese orden.

### Añadido

- `packaging/subir_version.py`, para subir la versión en todos los archivos de
  una sola vez.

### Cambiado

- Se quitaron varios subtítulos que explicaban lo que ya se ve o lo que el
  tutorial ya cuenta. Se conservan los atajos de teclado.

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
- Instaladores y paquetes: instalador por usuario para Windows (Inno Setup) y
  AppImage, `.deb` y `.rpm` para Linux.
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

### Notas

- Los artefactos todavía **no están firmados**: en Windows, SmartScreen avisa la
  primera vez. En Linux, al AppImage hay que darle permiso de ejecución.
- macOS queda fuera del proyecto: no se empaqueta ni se publica para ese sistema.

[0.2.0]: https://github.com/mastopiramato/fontiador/releases/tag/v0.2.0
