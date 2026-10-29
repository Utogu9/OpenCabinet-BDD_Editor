# OpenCabinet-BDD_Editor

[English](README.md) · [Español](README.es.md)

Artwork, manual and metadata editor for [OpenCabinet-BDD](https://github.com/Utogu9/OpenCabinet-BDD).

**Windows:** download `OpenCabinet-BDD_Editor.exe` from [Releases](https://github.com/Utogu9/OpenCabinet-BDD_Editor/releases/latest), run it and select your library. Python is included; no installation is required. Settings are stored in `%LOCALAPPDATA%\OpenCabinet-BDD_Editor`.

To run from source:

1. Install **Python 3.10 or later**, with Tkinter, and enable the `py` launcher or add Python to PATH.
2. Run **Run-Editor.cmd**. On first launch, it installs dependencies in its own environment; Internet access is only required for that installation.
3. Select the folder containing the consoles and their `catalog.json` files. It can have any name and be stored anywhere.

Search games, replace images, add variants, console artwork and CBZ manuals. For artwork, the editor compares lossless WebP with quality 90 WebP and keeps the smaller file; manual pages use quality 90 directly. Changes are saved to the selected library and its catalogues are updated.

**Import image** and **+ Variant** add a new numbered file when that type already exists (for example, `logo2.svg`, `screenshot2.webp` or `manual2.cbz`). **Replace** changes only the selected file. This applies to both game and console artwork; byte-identical duplicates are rejected, and changes can be undone.

**Delete** removes the selected file and its catalogue entry, keeping a backup for **Undo change**. **Make primary** swaps a numbered variant with the main file (or promotes it if the main file is missing), preserving the original bytes, credits and metadata. These actions also support CBZ manuals. **Compare** opens two images from the current game or console side by side, with shared zoom and pan, dimensions and file sizes; SVG logos are supported. The `inlay` type is for the inside face of a back cover or full cover.

Backups and history are stored in `_editor` inside the selected library; if the library is named `generated`, they are stored in `manual` alongside it. Keep these backups to undo changes.

Console logos support original SVG files as well as WebP. SVGs are previewed locally without changing the original; replacing a logo between SVG and WebP preserves undo history and attribution. Other image types use the WebP comparison described above.

Select `manual` and click **IMG to CBZ** to create a manual from PNG, JPG or WebP images. Add pages, review their previews and arrange the numbered list with **Move up/down**. Images exceeding **3840 pixels wide or 2160 pixels high** are reduced proportionally with Lanczos resampling; smaller images are not enlarged. Manual pages are encoded directly as WebP at quality 90, without generating a lossless candidate, with transparency and colour profiles preserved. The CBZ contains `0001.webp`, `0002.webp`, etc., in the selected order, without margins or cropping. Progress is shown while encoding pages.

New manuals use `manual.cbz`, `manual2.cbz`, etc., preserving existing manuals and supporting catalogue updates and undo. Ordered page paths, source filenames, hashes, source/result dimensions and per-page encoding decisions are recorded in `image_pages`; source images are unchanged. **Import image** also accepts existing CBZ manuals. Imported CBZ archives are checked and preserved without recompression; generated CBZ files use the WebP and size rules above. Manuals open in the associated external reader, which must support CBZ archives containing WebP pages.

This folder contains only the editor. Download the artwork separately; DAT files, the batch converter and the original project are not required.

To test the interface using temporary files: `Run-Editor.cmd --self-test`.

## Editing metadata

Select a game and click **Edit metadata**. The form displays its shared metadata, including Wikidata values when available. Enable **Custom value** beside a field to enter your own value; disable it to use the shared value again. Changes affect only the selected serial. Fields can also be filled for games with no Wikidata record. Names, brief descriptions and full descriptions support English and Spanish.

Game fields include developer, publisher, genre, minimum/maximum players, game mode, release date and platform. Enter one value per line, a positive integer for player counts, and `YYYY`, `YYYY-MM` or `YYYY-MM-DD` for dates. An enabled custom field left empty deliberately hides the shared value.

For a console, select **Console artwork** and then **Edit metadata**. Its fields are **Release Date**, **Developer** and **Manufacturer**, plus names and descriptions. The **Custom metadata / source** tab accepts additional fields as a JSON object and displays the original shared game record for reference.

**Save metadata** updates the selected console's `catalog.json`. Per-game edits are stored in `games[serial].metadata_overrides`; console data is stored in the root `console_metadata` object. Both use language dictionaries (`labels`, `short_descriptions`, `descriptions`), a `fields` dictionary of statement arrays, and optional `custom` data. A consumer resolves game data by overlaying these field/language keys on the record referenced by `metadata_id`; explicit empty values take precedence. Unedited statements retain their qualifiers and references. Manually entered field statements have `source: "manual"`; the shared record's license and provenance describe that original record, not the user's new content. Metadata names do not rename DAT entries or folders.

**Undo metadata change** reverses the latest metadata edit for the current game or console. Metadata and artwork have separate undo histories and keep each other's changes. Backups and pending-write recovery use the editor's private history folder. The editor does not download metadata automatically or change the original shared Wikidata records.

## Adding a missing game

Click **Add game from DAT**, choose the console and provider, then **Download / update DAT** or **Import DAT/ZIP**. Search by name or serial, select the exact region/revision/disc entry and confirm the identifiers to create. Existing game folders are reused; their images are preserved. New consoles can also be added to the selected library.

Only No-Intro and Redump identifiers are accepted, using the same serial normalization, folder substitutions, collision checks and placeholder exclusions as Run-Library. A search result is a candidate for explicit selection, never an automatic assignment to a different region or revision. Entries without a valid identifier cannot be created. Wii supports Redump disc serials and No-Intro Wii Digital CDN title IDs.

DAT files are cached locally with their hashes and source information. If No-Intro requires an interactive download, open its website and import the official Standard DAT/ZIP. If that export lacks serials, import the original **DB Export** XML/ZIP afterwards: only missing serials are filled from primary media/digital fields, matching complete game names. PCB numbers, ROM hashes and database entry numbers are never used as game folder identifiers. The selected entry and DAT provenance are recorded in `catalog.json`; its existing primary DAT metadata is preserved.

**Undo last game registration** reverses the last registration for the selected console. New game folders must be empty: undo their imported images first. Registration preserves existing image history and has a recovery journal for interrupted writes. The private `dat-cache` folder is not part of an artwork contribution.
