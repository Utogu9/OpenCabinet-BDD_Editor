# Changelog

## v1.6.0

- Add `cover_full_material` for full-cover bump height, roughness and specular intensity. Import 8-bit RGBA PNG or lossless WebP and save lossless RGBA PNG, preserving hidden RGB values and original dimensions independently of the artwork encoding preference.
- Support material map variants, replacement, primary selection, deletion and undo with both JSON and SQLite catalogues.
- Add console-scoped locks for compatible importers, allowing different consoles to be imported concurrently while keeping the editor protected from active writes.
- Document material maps in English and Spanish and verify their lossless encoding in the packaged Windows executable self-test.
