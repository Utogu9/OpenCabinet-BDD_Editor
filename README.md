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

To publish a Windows release, push a version tag such as `v1.0.0`. GitHub Actions runs the tests, builds and tests the standalone executable, then attaches the `.exe` and its SHA-256 checksum to the Release. The workflow can also be run manually from **Actions** to produce a downloadable build artifact.

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

Para publicar una versión de Windows, subí una etiqueta de versión como `v1.0.0`. GitHub Actions ejecuta las pruebas, compila y prueba el ejecutable independiente y adjunta el `.exe` con su checksum SHA-256 a la Release. También se puede ejecutar manualmente desde **Actions** para obtener una compilación descargable.
