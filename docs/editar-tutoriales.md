# Cómo editar los tutoriales

Los textos de los tutoriales que aparecen dentro de la app están todos en
[`tutorial.json`](../tutorial.json), en la raíz del proyecto. No hay que tocar
ningún archivo de código para cambiarlos.

Después de editar el archivo, **recargá la página de la app** (F5). Alcanza con
eso: la app lee el archivo cada vez que arranca.

## Forma del archivo

```json
{
  "dim": {
    "title": "Dimensiones",
    "steps": [
      {
        "target": "#dimChars",
        "title": "Elegí un carácter",
        "body": "Cada botón es un glifo.",
        "keys": ["clic"]
      }
    ]
  }
}
```

- La clave de arriba (`dim`, `kern`, `imp`, `words`, `accent`, `sets`, `font`,
  `log`) es la sección. Tiene que coincidir con el nombre de la pestaña.
- `title`: el título de la tarjeta del paso.
- `body`: el texto. Ver el formato más abajo.
- `keys`: las fichas de teclas o gestos que se muestran debajo. Es opcional.
- `target`: **el elemento de la interfaz que se resalta** mientras se muestra el
  paso. Es opcional; si se deja vacío, no se resalta nada.

## Formato del texto (`body`)

Se escribe simple y la app lo convierte sola:

| Escribís | Se ve |
|---|---|
| `**negrita**` | **negrita** |
| `` `código` `` | `código` |
| `1.` `2.` al principio de línea | lista numerada |
| `-` al principio de línea | lista con viñetas |
| salto de línea | separa párrafos |

No hace falta saber HTML. Todo lo que escribas se muestra como texto, así que no
hay forma de romper la interfaz desde acá.

## Cómo saber qué resaltar

`target` es un selector de CSS. Los más útiles, por sección:

| Sección | Elementos |
|---|---|
| Inicio (`imp`) | `#impZona` (la zona para elegir archivo), `#impAccesos` (los accesos), `#impCarpetas` |
| Dimensiones (`dim`) | `#dimChars` (la rejilla), `#tab-dim .panel.ctl` (los controles), `#tab-dim` (toda la sección) |
| Kerning (`kern`) | `.ksubtab` (las dos solapas), `#kvS` (el valor), `#kbL` (lado izquierdo), `#kbApply` (aplicar al lote), `#ksub-pair .chars.batchgrid` (la rejilla del asistente) |
| Palabras (`words`) | `#wordIn` |
| Tildes (`accent`) | `#accS`, `#tab-accent` |
| Conjuntos (`sets`) | `#cs_upper` |
| Fuente (`font`) | `#family`, `#build` |
| Registro (`log`) | `#log` |

Con `#tab-<sección>` se resalta la sección entera, que sirve cuando el paso habla
de algo general.

## Paso con animación

Algunos pasos muestran una animación. Se pide con `demo`, y hay que indicar el
marco con `viewBox`:

```json
{
  "target": "#tab-dim .panel.ctl",
  "title": "Altura, ancho y proporción",
  "body": "El candado mantiene la proporción.",
  "demo": "scale",
  "viewBox": "-300 0 2000 1000",
  "loop": true
}
```

Animaciones disponibles: `scale`, `pair`, `kern`, `word`, `accent`, `sets`,
`build`, `template`. `loop: true` la repite sin parar; `cursor: true` mueve el
recuadro rosa por la rejilla de caracteres.

## Si algo queda mal

- Si el archivo tiene un error de sintaxis, la app arranca igual pero **sin
  tutoriales**. Para revisarlo: `py -c "import json; json.load(open('tutorial.json', encoding='utf-8'))"`.
- Si un `target` no existe, ese paso se muestra sin resaltar nada; no se rompe.
- Se puede restablecer el aviso de "ya visto" desde **Conjuntos → Restablecer
  tutoriales**.
