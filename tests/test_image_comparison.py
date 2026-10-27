from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from image_comparison import load_image, viewport_image


class ImageComparisonTests(unittest.TestCase):
    def test_zoom_crops_before_resizing_and_displays_matching_pixels(self):
        image = Image.new('RGBA', (2000, 3000), 'red')
        image.putpixel((1000, 1500), (0, 255, 0, 255))
        record = {'image': image, 'width': 2000, 'height': 3000}
        tile, position = viewport_image(record, 4, (.5, .5), (400, 300))
        self.assertEqual(tile.size, (400, 300))
        self.assertEqual(position, (0, 0))
        self.assertEqual(tile.getpixel((200, 150)), (0, 255, 0, 255))
        tile, position = viewport_image(record, .05, (.5, .5), (400, 300))
        self.assertEqual(tile.size, (100, 150))
        self.assertEqual(position, (150, 75))

    def test_raster_and_svg_report_real_dimensions_sizes_and_read_only_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            png = Path(temporary)/'image.png'
            Image.new('RGBA', (10, 20), 'blue').save(png)
            svg = Path(temporary)/'logo.svg'
            svg.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><rect width="120" height="40" fill="red"/></svg>')
            for path, size, format in [(png, (10, 20), 'PNG'), (svg, (120, 40), 'SVG')]:
                before = path.read_bytes()
                record = load_image(path)
                self.assertEqual((record['width'], record['height']), size)
                self.assertEqual(record['bytes'], len(before))
                self.assertEqual(record['format'], format)
                self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
