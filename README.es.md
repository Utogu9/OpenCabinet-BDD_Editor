# OpenCabinet-BDD_Editor

[English](README.md) · [Español](README.es.md)

Editor de imágenes, manuales y metadatos de [OpenCabinet-BDD](https://github.com/Utogu9/OpenCabinet-BDD).

**Windows:** descargá `OpenCabinet-BDD_Editor.exe` desde [Releases](https://github.com/Utogu9/OpenCabinet-BDD_Editor/releases/latest), ejecutalo y seleccioná tu biblioteca. Incluye Python; no requiere instalación. La configuración se guarda en `%LOCALAPPDATA%\OpenCabinet-BDD_Editor`.

Para ejecutar desde el código fuente:

1. Instalá **Python 3.10 o posterior**, con Tkinter, y habilitá el lanzador `py` o agregá Python al PATH.
2. Ejecutá **Run-Editor.cmd**. La primera vez instala sus dependencias en un entorno propio; necesita Internet solo para esa instalación.
3. Elegí la carpeta que contiene las consolas y sus `catalog.json`. Puede estar en cualquier ubicación y tener cualquier nombre.

Permite buscar juegos, reemplazar imágenes, agregar variantes, imágenes de consola y manuales CBZ. Para las imágenes, compara WebP sin pérdida y calidad 90 y conserva el menor; las páginas de manuales usan calidad 90 directamente. Guarda los cambios en la biblioteca seleccionada y actualiza sus catálogos.

**Importar imagen** y **+ Variante** agregan un archivo numerado cuando ya existe ese tipo (por ejemplo, `logo2.svg`, `screenshot2.webp` o `manual2.cbz`). **Reemplazar** modifica únicamente el archivo seleccionado. Se aplica a imágenes de juegos y consolas y a los manuales; no se crean duplicados idénticos byte por byte y los cambios se pueden deshacer.

**Eliminar** quita el archivo seleccionado y su entrada del catálogo, conservando un respaldo para **Deshacer cambio**. **Elegir como principal** intercambia una variante numerada con el archivo principal (o la promueve si no existe el principal), conservando sus bytes, créditos y metadatos. Estas acciones también admiten manuales CBZ. **Comparar** muestra dos imágenes del juego o consola actual lado a lado, con zoom y desplazamiento sincronizados, dimensiones y peso; admite logos SVG. El tipo `inlay` corresponde a la cara interna de una contraportada o portada completa.

Los respaldos e historial quedan en `_editor` dentro de la biblioteca elegida; si se llama `generated`, quedan en `manual` junto a ella. Conservalos para poder deshacer cambios.

Los logos de consola admiten SVG originales además de WebP. Las vistas previas SVG se generan localmente y conservan el archivo original; los reemplazos entre SVG y WebP mantienen el historial y la atribución al deshacerlos. Los demás tipos de imagen usan la comparación WebP indicada arriba.

Seleccioná `manual` y pulsá **IMG a CBZ** para crear un manual con imágenes PNG, JPG o WebP. Agregá páginas, revisá las vistas previas y ordená la lista numerada con **Subir/Bajar**. Las imágenes que superen **3840 píxeles de ancho o 2160 de alto** se reducen proporcionalmente con remuestreo Lanczos; las más pequeñas no se amplían. Las páginas del manual se convierten directamente a WebP al 90 %, sin generar una alternativa sin pérdida, conservando transparencias y perfiles de color. El CBZ contiene `0001.webp`, `0002.webp`, etc., en el orden elegido, sin márgenes ni recortes. Se muestra el avance durante la conversión.

Los nuevos manuales usan `manual.cbz`, `manual2.cbz`, etc., conservan los manuales existentes, actualizan el catálogo y admiten deshacer. Las rutas de las páginas, nombres de origen, hashes, dimensiones originales/resultantes y decisiones de compresión de cada página quedan en `image_pages`; las imágenes originales no se modifican. **Importar imagen** también acepta manuales CBZ existentes. Los CBZ importados se comprueban y conservan sin recompresión; los generados usan las reglas WebP y de tamaño indicadas arriba. Los manuales se abren en el lector externo asociado, que debe admitir archivos CBZ con páginas WebP.

Esta carpeta contiene únicamente el editor. Las imágenes se descargan aparte; no necesita los DAT, el conversor ni el proyecto original.

Para comprobar la interfaz con archivos temporales: `Run-Editor.cmd --self-test`.

## Editar metadatos

Seleccioná un juego y pulsá **Editar metadatos**. El formulario muestra sus datos compartidos, incluidos los de Wikidata cuando existen. Activá **Valor propio** junto a un campo para escribir tu dato; desactivalo para volver al valor compartido. Los cambios afectan únicamente al serial elegido. También se pueden completar juegos sin ficha de Wikidata. Los nombres, descripciones breves y descripciones completas admiten inglés y español.

Los campos del juego incluyen desarrollador, editor, género, jugadores mínimos/máximos, modo de juego, fecha de lanzamiento y plataforma. Ingresá un valor por línea, un entero positivo para los jugadores y `AAAA`, `AAAA-MM` o `AAAA-MM-DD` para las fechas. Un valor propio activado pero vacío oculta deliberadamente el valor compartido.

Para una consola, seleccioná **Imágenes de la consola** y luego **Editar metadatos**. Sus campos son **Fecha de lanzamiento**, **Desarrollador** y **Fabricante**, además de nombres y descripciones. La pestaña **Metadatos personalizados / fuente** admite campos adicionales como objeto JSON y muestra la ficha compartida original del juego como referencia.

**Guardar metadatos** actualiza el `catalog.json` de la consola elegida. Las ediciones por juego se guardan en `games[serial].metadata_overrides`; los datos de la consola, en el objeto raíz `console_metadata`. Ambos usan diccionarios por idioma (`labels`, `short_descriptions`, `descriptions`), un diccionario `fields` con listas de declaraciones y datos `custom` opcionales. Las aplicaciones obtienen los datos del juego superponiendo esas claves de campo/idioma a la ficha indicada por `metadata_id`; los valores vacíos explícitos tienen prioridad. Las declaraciones sin editar conservan sus calificadores y referencias. Las ingresadas a mano tienen `source: "manual"`; la licencia y procedencia de la ficha compartida describen esa ficha original, no el contenido nuevo del usuario. Los nombres de metadatos no renombran entradas del DAT ni carpetas.

**Deshacer cambio de metadatos** revierte la última edición de la selección actual, sea un juego o una consola. Los metadatos y las imágenes tienen historiales separados y conservan los cambios del otro. Los respaldos y la recuperación de escrituras interrumpidas usan la carpeta privada del editor. El editor no descarga metadatos automáticamente ni modifica las fichas compartidas originales de Wikidata.

## Agregar un juego que falta

Pulsá **Agregar juego desde DAT**, elegí la consola y el proveedor, y usá **Descargar / actualizar DAT** o **Importar DAT/ZIP**. Buscá por nombre o serial, seleccioná la entrada exacta de región/revisión/disco y confirmá los identificadores que querés crear. Las carpetas de juegos existentes se reutilizan y conservan sus imágenes. También se pueden agregar consolas nuevas a la biblioteca seleccionada.

Solo se admiten identificadores de No-Intro y Redump, con las mismas normalizaciones de seriales, sustituciones de caracteres de carpeta, comprobaciones de colisiones y exclusiones de marcadores que Run-Library. Los resultados requieren una selección explícita: nunca se asigna automáticamente otra región o revisión. No se crean entradas sin un identificador válido. Wii admite seriales de discos Redump y Title IDs de No-Intro Wii Digital CDN.

Los DAT quedan en una caché local con sus hashes y procedencia. Si No-Intro requiere una descarga interactiva, abrí su sitio e importá el DAT/ZIP Standard oficial. Si faltan seriales, importá después el XML/ZIP original **DB Export**: solo se completan los seriales ausentes usando los campos primarios de medio/digital y la coincidencia del nombre completo. Nunca se usan códigos de PCB, hashes de ROM ni números internos de entrada como identificadores de carpeta. La entrada seleccionada y la procedencia del DAT quedan en `catalog.json`; se conservan los metadatos del DAT principal existente.

**Deshacer última alta de juego** revierte la última incorporación de la consola seleccionada. Las carpetas de juegos nuevos deben estar vacías: primero deshacé sus imágenes importadas. Las altas preservan el historial de imágenes existente y tienen un registro de recuperación ante escrituras interrumpidas. La carpeta privada `dat-cache` no forma parte de una contribución de imágenes.
