# Fontiador

Aplicación de escritorio para armar una fuente OpenType a partir de la rejilla de
glifos que dibujás en tu programa de diseño. Trae el render, lo traza, y te deja
ajustar dimensiones, kerning, tildes y conjuntos de caracteres antes de exportar
la fuente.

Funciona **local y sin conexión**: tus archivos no salen de tu computadora y no
hay cuentas, ni telemetría, ni servidores.

Disponible para **Windows y Linux**.

- Repositorio: <https://github.com/mastopiramato/fontiador>
- Descargas: <https://github.com/mastopiramato/fontiador/releases/latest>

## Instalación

### Windows

1. Descargá `Fontiador-<versión>-win-x64-setup.exe` desde la página de descargas.
2. Ejecutalo. Se instala **solo para tu usuario**, sin pedir permisos de
   administrador, en `%LOCALAPPDATA%\Programs\Fontiador`.
3. Como el instalador todavía no está firmado, Windows SmartScreen va a mostrar
   un aviso: *Más información* → *Ejecutar de todas formas*.

### Linux

**AppImage** (recomendado, no instala nada):

```bash
chmod +x Fontiador-<versión>-x86_64.AppImage
./Fontiador-<versión>-x86_64.AppImage
```

**Debian / Ubuntu**

```bash
sudo dpkg -i fontiador_<versión>_amd64.deb
```

**Fedora / openSUSE**

```bash
sudo rpm -i fontiador-<versión>-1.x86_64.rpm
```

### Desde el código fuente (para desarrollo)

```bash
git clone https://github.com/mastopiramato/fontiador
cd fontiador
python -m pip install -r requirements.txt
python fontiador_server.py
```

## Cómo se usa

Antes de dibujar nada, en la pestaña **Importaciones** podés descargar
**Fontiador Demo**: una fuente de ejemplo original ya terminada, con los 103
caracteres y las tildes, para ver cómo queda una fuente completa e instalarla en
tu sistema.

1. **Descargá la plantilla base** desde la pestaña *Importaciones*. Ya trae la
   cuadrícula, las líneas guía y el orden de los 103 caracteres.
2. **Dibujá** cada glifo sobre la línea base, dentro de su celda.
3. **Exportá** el render (PNG a 600 ppp, 10 000 px de ancho) o, si tu programa
   puede, un JSON con los contornos.
4. **Importá** el archivo desde la pestaña *Importaciones*: con el botón
   *Elegir archivo…* se abre el diálogo del sistema y se importa solo.
5. **Ajustá** lo que haga falta en *Dimensiones*, *Kerning* y *Tildes*.
6. **Reconstruí** la fuente en la pestaña *Fuente*. El `.otf` queda en `output/`.

Cada sección muestra un tutorial la primera vez que la abrís, y podés repetirlo
con el botón **?** de la esquina, o con la tecla <kbd>?</kbd> en cualquier
momento.

### Teclado

| Teclas | Qué hace |
|---|---|
| <kbd>←</kbd> <kbd>→</kbd> | Recorren lo que estés usando: la rejilla de caracteres, el asistente de kerning, los valores |
| <kbd>Ctrl</kbd> + <kbd>←</kbd> / <kbd>→</kbd> | Cambian de sección desde cualquier lado (también sirve <kbd>Alt</kbd>) |
| <kbd>?</kbd> | Abre el tutorial de la sección actual |
| <kbd>Esc</kbd> | Cierra el tutorial, o vuelve atrás en el asistente de kerning |
| <kbd>Enter</kbd> | Avanza de paso, o activa el acceso que tenga el foco |

### Editar los textos del tutorial

Los textos de los tutoriales están en [`tutorial.json`](tutorial.json), no dentro
del código. Se editan ahí y la app los lee al arrancar. El formato es sencillo:
`**negrita**`, `` `código` ``, listas con `1.` o `- `, y saltos de línea. Cada
paso tiene además la sección y el elemento que se resalta (`target`).

### El formato de la rejilla

| | |
|---|---|
| Cuadrícula | 10 columnas × 11 filas (103 caracteres) |
| Celda | 1000 × 1000 px |
| Ancho total del render | 10 000 px |
| Línea base | 800 px desde el borde superior de cada celda |

El orden de los caracteres es estricto: si cambia, los glifos se asignan al
carácter equivocado. La pestaña *Importaciones* muestra la correspondencia
celda por celda.

### Programas de diseño soportados

La app no depende de Affinity. Cualquier programa que pueda producir esa rejilla
sirve. Hay guía paso a paso dentro de la app para **Affinity Designer/Photo**,
**Adobe Illustrator**, **Inkscape**, **Figma**, **CorelDRAW** y cualquier otro.

Los vectores siempre dan mejor resultado que el trazado: si tu programa puede
exportar los contornos a JSON, la calidad es mayor y no hay que re-trazar.

## Dónde guarda los datos

- Si la carpeta de la app es escribible (**modo portable**), todo queda ahí al
  lado: `inbox/`, `output/`, `fontiador_project.json` y `fontiador.log`.
- Si no lo es (una instalación de sistema), los datos van a la carpeta del
  usuario: `%LOCALAPPDATA%\Fontiador`, `~/Library/Application Support/Fontiador` o
  `~/.local/share/Fontiador`.

Se puede forzar la carpeta con la variable de entorno `FONTIADOR_DATA_DIR`.

## Desarrollo

```bash
python tests/test_estructura.py     # página, endpoints, guía y plantillas
python tests/test_construccion.py   # importa y construye una fuente de verdad
```

Para empaquetar:

```bash
python packaging/make_icon.py                                  # iconos
python -m PyInstaller packaging/fontiador.spec --noconfirm     # dist/Fontiador/
iscc packaging/windows/fontiador.iss                           # Windows
bash packaging/linux/build-appimage.sh                         # Linux (AppImage)
bash packaging/linux/build-packages.sh                         # Linux (.deb y .rpm)
```

## Licencia

MIT. Ver [LICENSE](LICENSE).

Fontiador es un proyecto independiente: no está afiliado a Serif, ni a Adobe, ni a
ninguna de las empresas cuyos programas se mencionan. Los nombres se usan
únicamente para explicar cómo exportar desde cada uno.
