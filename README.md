# OpenCabinet-BDD_Editor

[English](#english) · [Español](#español)

## English

Artwork and manual editor for [OpenCabinet-BDD](https://github.com/Utogu9/OpenCabinet-BDD).

**Windows:** download `OpenCabinet-BDD_Editor.exe` from [Releases](https://github.com/Utogu9/OpenCabinet-BDD_Editor/releases/latest), run it and select your library. Python is included; no installation is required. Settings are stored in `%LOCALAPPDATA%\OpenCabinet-BDD_Editor`.

To run from source:

1. Install **Python 3.10 or later**, with Tkinter, and enable the `py` launcher or add Python to PATH.
2. Run **Run-Editor.cmd**. On first launch, it installs dependencies in its own environment; Internet access is only required for that installation.
3. Select the folder containing the consoles and their `catalog.json` files. It can have any name and be stored anywhere.

Search games, replace images, add variants, console artwork and PDF manuals. The editor compares lossless WebP with quality 90 WebP and keeps the smaller file. Changes are saved to the selected library and its catalogues are updated.

Backups and history are stored in `_editor` inside the selected library; if the library is named `generated`, they are stored in `manual` alongside it. Keep these backups to undo changes.

This folder contains only the editor. Download the artwork separately; DAT files, the batch converter and the original project are not required.

To test the interface using temporary files: `Run-Editor.cmd --self-test`.

### Adding a missing game

Click **Add game from DAT**, choose the console and provider, then **Download / update DAT** or **Import DAT/ZIP**. Search by name or serial, select the exact region/revision/disc entry and confirm the identifiers to create. Existing game folders are reused; their images are preserved. New consoles can also be added to the selected library.

Only No-Intro and Redump identifiers are accepted, using the same serial normalization, folder substitutions, collision checks and placeholder exclusions as Run-Library. A search result is a candidate for explicit selection, never an automatic assignment to a different region or revision. Entries without a valid identifier cannot be created. Wii supports Redump disc serials and No-Intro Wii Digital CDN title IDs.

DAT files are cached locally with their hashes and source information. If No-Intro requires an interactive download, open its website and import the official Standard DAT/ZIP. If that export lacks serials, import the original **DB Export** XML/ZIP afterwards: only missing serials are filled from primary media/digital fields, matching complete game names. PCB numbers, ROM hashes and database entry numbers are never used as game folder identifiers. The selected entry and DAT provenance are recorded in `catalog.json`; its existing primary DAT metadata is preserved.

**Undo last game registration** reverses the last registration for the selected console. New game folders must be empty: undo their imported images first. Registration preserves existing image history and has a recovery journal for interrupted writes. The private `dat-cache` folder is not part of an artwork contribution.

## Español

Editor de imágenes y manuales de [OpenCabinet-BDD](https://github.com/Utogu9/OpenCabinet-BDD).

**Windows:** descargá `OpenCabinet-BDD_Editor.exe` desde [Releases](https://github.com/Utogu9/OpenCabinet-BDD_Editor/releases/latest), ejecutalo y seleccioná tu biblioteca. Incluye Python; no requiere instalación. La configuración se guarda en `%LOCALAPPDATA%\OpenCabinet-BDD_Editor`.

Para ejecutar desde el código fuente:

1. Instalá **Python 3.10 o posterior**, con Tkinter, y habilitá el lanzador `py` o agregá Python al PATH.
2. Ejecutá **Run-Editor.cmd**. La primera vez instala sus dependencias en un entorno propio; necesita Internet solo para esa instalación.
3. Elegí la carpeta que contiene las consolas y sus `catalog.json`. Puede estar en cualquier ubicación y tener cualquier nombre.

Permite buscar juegos, reemplazar imágenes, agregar variantes, imágenes de consola y manuales PDF. Compara WebP sin pérdida y calidad 90 y conserva el menor. Guarda los cambios en la biblioteca seleccionada y actualiza sus catálogos.

Los respaldos e historial quedan en `_editor` dentro de la biblioteca elegida; si se llama `generated`, quedan en `manual` junto a ella. Conservalos para poder deshacer cambios.

Esta carpeta contiene únicamente el editor. Las imágenes se descargan aparte; no necesita los DAT, el conversor ni el proyecto original.

Para comprobar la interfaz con archivos temporales: `Run-Editor.cmd --self-test`.

### Agregar un juego que falta

Pulsá **Agregar juego desde DAT**, elegí la consola y el proveedor, y usá **Descargar / actualizar DAT** o **Importar DAT/ZIP**. Buscá por nombre o serial, seleccioná la entrada exacta de región/revisión/disco y confirmá los identificadores que querés crear. Las carpetas de juegos existentes se reutilizan y conservan sus imágenes. También se pueden agregar consolas nuevas a la biblioteca seleccionada.

Solo se admiten identificadores de No-Intro y Redump, con las mismas normalizaciones de seriales, sustituciones de caracteres de carpeta, comprobaciones de colisiones y exclusiones de marcadores que Run-Library. Los resultados requieren una selección explícita: nunca se asigna automáticamente otra región o revisión. No se crean entradas sin un identificador válido. Wii admite seriales de discos Redump y Title IDs de No-Intro Wii Digital CDN.

Los DAT quedan en una caché local con sus hashes y procedencia. Si No-Intro requiere una descarga interactiva, abrí su sitio e importá el DAT/ZIP Standard oficial. Si faltan seriales, importá después el XML/ZIP original **DB Export**: solo se completan los seriales ausentes usando los campos primarios de medio/digital y la coincidencia del nombre completo. Nunca se usan códigos de PCB, hashes de ROM ni números internos de entrada como identificadores de carpeta. La entrada seleccionada y la procedencia del DAT quedan en `catalog.json`; se conservan los metadatos del DAT principal existente.

**Deshacer última alta de juego** revierte la última incorporación de la consola seleccionada. Las carpetas de juegos nuevos deben estar vacías: primero deshacé sus imágenes importadas. Las altas preservan el historial de imágenes existente y tienen un registro de recuperación ante escrituras interrumpidas. La carpeta privada `dat-cache` no forma parte de una contribución de imágenes.
