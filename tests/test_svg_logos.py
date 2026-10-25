import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from PIL import Image
from console_artwork import ConsoleArtwork
from editor_store import ArtworkStore, encode_import
from svg_tools import encode_svg, preview_svg, svg_info

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><rect width="120" height="40" fill="red"/></svg>'


class SvgLogoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'generated' / 'Console'
        self.output.mkdir(parents=True)
        self.original_catalog = b'{"schema_version":2,"system":"Console","status":"complete","games":{}}'
        (self.output / 'catalog.json').write_bytes(self.original_catalog)
        self.svg = self.root / 'import.svg'
        self.svg.write_bytes(SVG)
        self.store = ArtworkStore(self.root)
        self.console = ConsoleArtwork(self.store)
        self.png = self.root / 'import.png'
        Image.new('RGBA', (20, 20), (20, 40, 60, 180)).save(self.png)

    def test_original_bytes_and_vector_aspect_ratio_are_preserved(self):
        result = encode_svg(self.svg)
        self.assertEqual(result['data'], SVG)
        self.assertEqual(result['original'], SVG)
        self.assertEqual((result['width'], result['height']), (120, 40))
        self.assertEqual(preview_svg(SVG, 300).size, (300, 100))
        asset = self.console.save(self.output, 'logo', result)
        self.assertEqual(asset['path'], 'logo.svg')
        self.assertEqual((self.output / 'logo.svg').read_bytes(), SVG)
        self.assertEqual(self.console.images(self.output)['logo']['format'], 'SVG')
        self.assertEqual((self.output / 'catalog.json').read_bytes(), self.original_catalog)

    def test_millimetres_and_adobe_namespace_and_color_entities(self):
        raw = b'''<?xml version="1.0"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"
[<!ENTITY ns_flows "http://ns.adobe.com/Flows/1.0/"><!ENTITY st0 "fill:#FF0000;">]>
<svg xmlns="http://www.w3.org/2000/svg" width="30mm" height="10mm" viewBox="0 0 30 10">
<rect width="30" height="10" style="&st0;"/></svg>'''
        image = preview_svg(raw, 300)
        self.assertLessEqual(abs(image.width / image.height - 3), .04)
        self.assertEqual(image.getpixel((20, 20)), (255, 0, 0, 255))

    def test_active_and_external_and_nested_entities_are_rejected(self):
        for content in [b'<script>alert(1)</script>', b'<image href="file:///C:/secret.png"/>',
                        b'<image href="https://example.com/image.png"/>', b'<rect onclick="alert(1)"/>',
                        b'<style>@import "https://example.com/style.css";</style>']:
            with self.assertRaises(ValueError):
                svg_info(b'<svg xmlns="http://www.w3.org/2000/svg">' + content + b'</svg>')
        with self.assertRaises(ValueError):
            svg_info(b'<!DOCTYPE svg [<!ENTITY st0 "&st0;&st0;">]>' + SVG)

    def test_svg_webp_replace_and_undo_switch_files_without_duplicates(self):
        self.console.save(self.output, 'logo', encode_svg(self.svg))
        self.console.save(self.output, 'logo', encode_import(self.png))
        self.assertFalse((self.output / 'logo.svg').exists())
        self.assertTrue((self.output / 'logo.webp').exists())
        self.console.undo(self.output, 'logo')
        self.assertEqual((self.output / 'logo.svg').read_bytes(), SVG)
        self.assertFalse((self.output / 'logo.webp').exists())
        self.console.undo(self.output, 'logo')
        self.assertFalse((self.output / 'logo.svg').exists())

    def test_untracked_svg_is_backed_up_when_replaced_and_restored(self):
        (self.output / 'logo.svg').write_bytes(SVG)
        self.console.save(self.output, 'logo', encode_import(self.png))
        self.console.undo(self.output, 'logo')
        self.assertEqual((self.output / 'logo.svg').read_bytes(), SVG)
        self.assertFalse((self.output / 'logo.webp').exists())
        self.assertEqual(self.console.images(self.output)['logo']['path'], 'logo.svg')

    def test_raster_to_svg_and_attribution_survive_undo(self):
        first = encode_import(self.png)
        first['sources'] = [{'provider': 'Commons', 'license': 'CC BY-SA 3.0', 'author': 'Artist'}]
        self.console.save(self.output, 'logo', first)
        self.console.save(self.output, 'logo', encode_svg(self.svg))
        self.console.undo(self.output, 'logo')
        record = json.loads((self.output / 'console_artwork.json').read_text())['images']['logo']
        self.assertEqual(record['sources'], first['sources'])
        self.assertEqual((self.output / 'logo.webp').read_bytes(), first['data'])
        self.assertFalse((self.output / 'logo.svg').exists())

    def test_svg_only_supported_for_console_logo_and_conflicting_target_is_preserved(self):
        with self.assertRaises(ValueError):
            self.console.save(self.output, 'render', encode_svg(self.svg))
        self.console.save(self.output, 'logo', encode_import(self.png))
        (self.output / 'logo.svg').write_bytes(b'Uncatalogued user content')
        with self.assertRaises(ValueError):
            self.console.save(self.output, 'logo', encode_svg(self.svg))
        self.assertEqual((self.output / 'logo.svg').read_bytes(), b'Uncatalogued user content')


if __name__ == '__main__':
    unittest.main()
