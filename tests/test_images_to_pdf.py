import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image, ImageCms, ImageOps
from editor_common import digest
from editor_store import ArtworkStore, json_bytes
from images_to_pdf import images_to_pdf
from pdf_tools import read_pdf, signature


class ImagesToPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def image(self, name, size, color, **options):
        path = self.root/name
        Image.new('RGB', size, color).save(path, **options)
        return path

    def test_requested_order_and_individual_sizes_have_no_borders_or_resampling(self):
        first = self.image('z.png', (40, 20), 'red', dpi=(300, 300))
        second = self.image('a.webp', (16, 32), 'blue', lossless=True)
        before = {path: path.read_bytes() for path in (first, second)}
        encoded = images_to_pdf([first, second, first])
        self.assertEqual(encoded['pages'], 3)
        for pdf in (encoded['original'], encoded['data']):
            reader = read_pdf(pdf)
            self.assertEqual([tuple(page.mediabox) for page in reader.pages], [(0, 0, 40, 20), (0, 0, 16, 32), (0, 0, 40, 20)])
            for page, color, size in zip(reader.pages, ('red', 'blue', 'red'), ((40, 20), (16, 32), (40, 20))):
                actual = page.images[0].image.convert('RGB')
                self.assertEqual(actual.size, size)
                self.assertEqual(actual.tobytes(), Image.new('RGB', size, color).tobytes())
                command = page.get_contents().get_data().decode('ascii')
                self.assertIn(f'{size[0]:.8f} 0 0 {size[1]:.8f} 0 0 cm', command)
        self.assertEqual([page['filename'] for page in encoded['image_pages']], ['z.png', 'a.webp', 'z.png'])
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(encoded['image_pages'][0]['sha256'], digest(before[first]))

    def test_palette_and_partial_transparency_are_preserved_losslessly(self):
        path = self.root/'palette.png'
        image = Image.new('P', (30, 20))
        image.putpalette([255, 0, 0, 0, 255, 0] + [0]*762)
        image.putpixel((0, 0), 1)
        image.save(path, transparency=bytes([255, 80]+[255]*254))
        encoded = images_to_pdf([path])
        for pdf in (encoded['original'], encoded['data']):
            page = read_pdf(pdf).pages[0]
            obj = page['/Resources']['/XObject']['/PageImage']
            self.assertEqual(obj['/ColorSpace'][0], '/Indexed')
            self.assertIn('/SMask', obj)
            with Image.open(path) as source:
                self.assertEqual(page.images[0].image.convert('RGBA').tobytes(), source.convert('RGBA').tobytes())

    def test_rgb_transparency_and_icc_profile_are_retained(self):
        path = self.root/'alpha.png'
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.new('RGBA', (20, 30), (20, 40, 60, 80)).save(path, icc_profile=profile)
        encoded = images_to_pdf([path])
        for pdf in (encoded['original'], encoded['data']):
            obj = read_pdf(pdf).pages[0]['/Resources']['/XObject']['/PageImage']
            self.assertEqual(obj['/ColorSpace'][0], '/ICCBased')
            self.assertEqual(obj['/ColorSpace'][1].get_object().get_data(), profile)
            self.assertEqual(obj['/SMask'].get_data(), bytes([80]) * 600)

    def test_existing_jpeg_stream_is_embedded_without_an_extra_loss(self):
        path = self.image('scan.jpg', (60, 40), 'orange', quality=90)
        encoded = images_to_pdf([path])
        obj = read_pdf(encoded['original']).pages[0]['/Resources']['/XObject']['/PageImage']
        self.assertEqual(obj['/Filter'], '/DCTDecode')
        self.assertEqual(obj._data, path.read_bytes())

    def test_exif_rotation_changes_page_dimensions_and_preserves_oriented_pixels(self):
        path = self.root/'rotate.jpg'
        image = Image.new('RGB', (20, 40), 'red')
        for x in range(10):
            for y in range(40):
                image.putpixel((x, y), (0, 0, 255))
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, exif=exif)
        encoded = images_to_pdf([path])
        page = read_pdf(encoded['original']).pages[0]
        self.assertEqual(tuple(page.mediabox), (0, 0, 40, 20))
        with Image.open(path) as original:
            self.assertEqual(page.images[0].image.convert('RGB').tobytes(), ImageOps.exif_transpose(original).tobytes())

    def test_smallest_pdf_candidate_is_used_without_changing_page_layout(self):
        path = self.root/'noise.png'
        Image.frombytes('RGB', (160, 100), random.Random(42).randbytes(160*100*3)).save(path)
        encoded = images_to_pdf([path])
        self.assertEqual(encoded['bytes'], min(encoded['compression']['candidate_bytes'].values()))
        self.assertLess(len(encoded['data']), len(encoded['original']))
        self.assertEqual(signature(read_pdf(encoded['original'])), signature(read_pdf(encoded['data'])))

    def test_resized_jpeg_with_icc_is_smaller_and_preserves_its_color_profile(self):
        path = self.root/'icc-scan.jpg'
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.frombytes('RGB', (800, 600), random.Random(42).randbytes(800*600*3)).save(
            path, quality=85, icc_profile=profile)
        with patch('images_to_pdf.MAX_PAGE_IMAGE_SIZE', (1000, 1000)):
            full = images_to_pdf([path])
        with patch('images_to_pdf.MAX_PAGE_IMAGE_SIZE', (512, 512)):
            resized = images_to_pdf([path])
        self.assertLess(resized['bytes'], full['bytes'])
        self.assertLess(resized['bytes'], len(resized['original'])/2)
        self.assertEqual(resized['compression']['recompressed_images'], 1)
        self.assertEqual(resized['compression']['skipped_images'], 0)
        obj = read_pdf(resized['data']).pages[0]['/Resources']['/XObject']['/PageImage']
        self.assertEqual(obj['/Filter'], '/DCTDecode')
        self.assertEqual((obj['/Width'], obj['/Height']), (512, 384))
        self.assertEqual(obj['/ColorSpace'][0], '/ICCBased')
        self.assertEqual(obj['/ColorSpace'][1].get_object().get_data(), profile)

    def test_recompression_preserves_image_metadata_and_removes_old_filter_parameters(self):
        from io import BytesIO
        from pypdf.generic import BooleanObject, DictionaryObject, NameObject, NumberObject
        from pdf_tools import optimize_pdf_data, pdf_api
        path = self.root/'icc.png'
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.frombytes('RGB', (160, 100), random.Random(42).randbytes(160*100*3)).save(path, icc_profile=profile)
        encoded = images_to_pdf([path])
        _, PdfWriter = pdf_api()
        writer = PdfWriter(clone_from=read_pdf(encoded['original']))
        obj = writer.pages[0]['/Resources']['/XObject']['/PageImage']
        obj[NameObject('/Interpolate')] = BooleanObject(True)
        obj[NameObject('/DecodeParms')] = DictionaryObject({NameObject('/Predictor'): NumberObject(1)})
        buffer = BytesIO()
        writer.write(buffer)
        optimized = optimize_pdf_data(buffer.getvalue())
        page = read_pdf(optimized['data']).pages[0]
        obj = page['/Resources']['/XObject']['/PageImage']
        self.assertEqual(obj['/Filter'], '/DCTDecode')
        self.assertTrue(obj['/Interpolate'])
        self.assertNotIn('/DecodeParms', obj)
        self.assertEqual(page.images[0].image.size, (160, 100))
        self.assertEqual(obj['/ColorSpace'][1].get_object().get_data(), profile)

    def test_nondefault_sample_mapping_is_preserved_without_jpeg_conversion(self):
        from io import BytesIO
        from pypdf.generic import ArrayObject, NameObject, NumberObject
        from pdf_tools import optimize_pdf_data, pdf_api
        path = self.root/'noise-decode.png'
        Image.frombytes('RGB', (160, 100), random.Random(42).randbytes(160*100*3)).save(path)
        encoded = images_to_pdf([path])
        _, PdfWriter = pdf_api()
        writer = PdfWriter(clone_from=read_pdf(encoded['original']))
        obj = writer.pages[0]['/Resources']['/XObject']['/PageImage']
        obj[NameObject('/Decode')] = ArrayObject([NumberObject(value) for value in [1, 0]*3])
        buffer = BytesIO()
        writer.write(buffer)
        optimized = optimize_pdf_data(buffer.getvalue())
        obj = read_pdf(optimized['data']).pages[0]['/Resources']['/XObject']['/PageImage']
        self.assertEqual(obj['/Filter'], '/FlateDecode')
        self.assertEqual(obj['/Decode'], [1, 0]*3)
        self.assertEqual(optimized['compression']['recompressed_images'], 0)
        self.assertTrue(optimized['compression']['lossless'])

    def test_long_narrow_page_is_reduced_to_the_width_limit(self):
        path = self.image('long.png', (15000, 2), 'red')
        encoded = images_to_pdf([path])
        page = read_pdf(encoded['data']).pages[0]
        self.assertEqual(tuple(page.mediabox), (0, 0, 3840, 1))
        self.assertEqual(page.images[0].image.size, (3840, 1))

    def test_width_height_and_both_limits_resize_actual_pdf_images_and_pages(self):
        for name, size, expected in [('wide.jpg', (4000, 1000), (3840, 960)),
                                     ('tall.png', (1000, 3000), (720, 2160)),
                                     ('both.webp', (4000, 3000), (2880, 2160)),
                                     ('small.png', (100, 200), (100, 200))]:
            with self.subTest(name=name):
                path = self.image(name, size, 'red')
                before = path.read_bytes()
                encoded = images_to_pdf([path])
                for pdf in (encoded['original'], encoded['data']):
                    page = read_pdf(pdf).pages[0]
                    self.assertEqual(tuple(page.mediabox), (0, 0, *expected))
                    self.assertEqual(page.images[0].image.size, expected)
                record = encoded['image_pages'][0]
                self.assertEqual((record['width'], record['height']), expected)
                self.assertEqual((record['source_width'], record['source_height']), size)
                self.assertEqual(path.read_bytes(), before)

    def test_resizing_uses_exif_oriented_dimensions_and_reencodes_large_jpeg(self):
        exif = Image.Exif()
        exif[274] = 6
        path = self.image('tall-rotated.jpg', (1000, 4000), 'blue', exif=exif)
        encoded = images_to_pdf([path])
        page = read_pdf(encoded['original']).pages[0]
        self.assertEqual(tuple(page.mediabox), (0, 0, 3840, 960))
        self.assertEqual(page.images[0].image.size, (3840, 960))
        self.assertEqual(encoded['image_pages'][0]['source_width'], 4000)

    def test_downscaled_indexed_image_retains_transparency(self):
        path = self.root/'wide-palette.png'
        image = Image.new('P', (4000, 40), 1)
        image.putpalette([255, 0, 0, 0, 255, 0] + [0]*762)
        image.save(path, transparency=bytes([255, 80]+[255]*254))
        encoded = images_to_pdf([path])
        page = read_pdf(encoded['data']).pages[0]
        self.assertEqual(page.images[0].image.size, (3840, 38))
        self.assertEqual(page.images[0].image.convert('RGBA').getchannel('A').getextrema(), (80, 80))

    def test_invalid_lists_animated_or_unsupported_images_do_not_create_output(self):
        for paths in ([], [Path('missing.png')]*2001):
            with self.assertRaises(ValueError):
                images_to_pdf(paths)
        animated = self.root/'animated.png'
        Image.new('RGB', (10, 10), 'red').save(animated, save_all=True, append_images=[Image.new('RGB', (10, 10), 'blue')])
        with self.assertRaises(ValueError):
            images_to_pdf([animated])
        gif = self.root/'image.gif'
        Image.new('RGB', (10, 10), 'red').save(gif)
        with self.assertRaises(ValueError):
            images_to_pdf([gif])

    def test_import_updates_catalogue_provenance_and_can_be_undone(self):
        output = self.root/'generated/Console'
        output.mkdir(parents=True)
        original = {'schema_version': 2, 'status': 'complete', 'system': 'Console',
                    'games': {'ID': {'serial': 'ID', 'entries': [{'name': 'Game'}], 'images': {}}}}
        (output/'catalog.json').write_bytes(json_bytes(original))
        store = ArtworkStore(self.root)
        path = self.image('page.png', (20, 30), 'red')
        encoded = images_to_pdf([path])
        store.save(output, 'ID', 'manual', 'manual', encoded, create_only=True)
        record = store.read_catalog(output)['games']['ID']['images']['manual']
        self.assertEqual(record['image_pages'], encoded['image_pages'])
        self.assertEqual((output/'ID/manual.pdf').read_bytes(), encoded['data'])
        store.verification_view(output, store.read_catalog(output))
        store.undo(output, 'ID')
        self.assertEqual(store.read_catalog(output), original)
        self.assertFalse((output/'ID/manual.pdf').exists())


if __name__ == '__main__':
    unittest.main()
