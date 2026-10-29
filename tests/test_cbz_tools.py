from io import BytesIO
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image, ImageCms
from cbz_tools import images_to_cbz, inspect_cbz, import_cbz, verify_cbz
from editor_common import digest
from editor_store import ArtworkStore, json_bytes
from artwork_actions import change_game
from pdf_tools import pdf_api, optimize_pdf


class CbzManualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.first = self.root/'z-first.png'
        self.second = self.root/'a-second.png'
        Image.new('RGBA', (40, 20), (255, 0, 0, 180)).save(self.first)
        Image.new('RGB', (30, 60), 'blue').save(self.second)

    def test_requested_order_determinism_and_per_page_webp_rules(self):
        progress = []
        result = images_to_cbz([self.first, self.second, self.first], lambda i, n: progress.append((i, n)))
        self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])
        self.assertEqual(result['format'], 'CBZ')
        self.assertEqual(result['data'], images_to_cbz([self.first, self.second, self.first])['data'])
        with ZipFile(BytesIO(result['data'])) as archive:
            self.assertEqual(archive.namelist(), ['0001.webp', '0002.webp', '0003.webp'])
            for entry, expected, source in zip(archive.infolist(), result['image_pages'], [self.first, self.second, self.first]):
                self.assertEqual(entry.compress_type, ZIP_STORED)
                raw = archive.read(entry)
                self.assertEqual(digest(raw), expected['sha256'])
                self.assertEqual(expected['source_sha256'], digest(source.read_bytes()))
                self.assertEqual(len(raw), min(expected['compression']['candidate_bytes'].values()))
                with Image.open(BytesIO(raw)) as image, Image.open(source) as original:
                    self.assertEqual(image.format, 'WEBP')
                    self.assertEqual(image.size, original.size)
                    self.assertFalse(expected['compression']['lossless'])
                    self.assertEqual(expected['compression']['quality'], 90)
                    self.assertEqual(image.convert('RGBA').getchannel('A').tobytes(), original.convert('RGBA').getchannel('A').tobytes())
        verify_cbz(result['data'], result)

    def test_photo_uses_quality_90_and_preserves_icc(self):
        path = self.root/'scan.png'
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.frombytes('RGB', (180, 100), random.Random(42).randbytes(180*100*3)).save(path, icc_profile=profile)
        result = images_to_cbz([path])
        self.assertFalse(result['image_pages'][0]['compression']['lossless'])
        with ZipFile(BytesIO(result['data'])) as archive, Image.open(BytesIO(archive.read('0001.webp'))) as image:
            self.assertEqual(image.info['icc_profile'], profile)

    def test_each_page_is_encoded_once_with_quality_90_and_never_lossless(self):
        save = Image.Image.save
        with patch('editor_common.compare_encodings', side_effect=AssertionError('Do not compare manual encodings')), \
             patch.object(Image.Image, 'save', autospec=True, side_effect=save) as encode:
            result = images_to_cbz([self.first, self.second])
        self.assertEqual(encode.call_count, 2)
        for call in encode.call_args_list:
            self.assertEqual(call.kwargs['format'], 'WEBP')
            self.assertIs(call.kwargs['lossless'], False)
            self.assertEqual(call.kwargs['quality'], 90)
        self.assertEqual(result['compression']['policy'], 'cbz-webp90-pages-v1')
        verify_cbz(result['data'], result)

    def test_older_smallest_webp_manuals_still_verify(self):
        from editor_common import compare_encodings
        with Image.open(self.first) as source:
            image = source.convert('RGBA')
            data, decision = compare_encodings(image)
        buffer = BytesIO()
        with ZipFile(buffer, 'w', compression=ZIP_STORED) as archive:
            archive.writestr('0001.webp', data)
        cbz = buffer.getvalue()
        asset = {'pages': 1, 'bytes': len(cbz), 'compression': {'policy': 'cbz-smallest-webp-pages-v1'},
                 'image_pages': [{'path': '0001.webp', 'sha256': digest(data), 'bytes': len(data),
                                  'width': image.width, 'height': image.height, 'compression': decision}]}
        verify_cbz(cbz, asset)

    def test_resize_limits_preserve_proportions_orientation_and_sources(self):
        for size, expected in [((4000, 1000), (3840, 960)), ((1000, 3000), (720, 2160)),
                               ((4000, 3000), (2880, 2160)), ((20, 30), (20, 30))]:
            with self.subTest(size=size):
                path = self.root/'large.png'
                Image.new('RGB', size, 'red').save(path)
                before = path.read_bytes()
                result = images_to_cbz([path])
                actual = inspect_cbz(result['data'])[0]
                self.assertEqual((actual['width'], actual['height']), expected)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual((result['image_pages'][0]['source_width'], result['image_pages'][0]['source_height']), size)
                verify_cbz(result['data'], result)
        exif = Image.Exif()
        exif[274] = 6
        path = self.root/'rotated.jpg'
        Image.new('RGB', (1000, 4000), 'blue').save(path, exif=exif)
        record = inspect_cbz(images_to_cbz([path])['data'])[0]
        self.assertEqual((record['width'], record['height']), (3840, 960))

    def test_import_keeps_cbz_bytes_and_uses_natural_page_order(self):
        buffer = BytesIO()
        with ZipFile(buffer, 'w') as archive:
            for name in ('10.png', '2.png', '1.png'):
                archive.writestr(name, self.first.read_bytes())
            archive.writestr('ComicInfo.xml', b'<ComicInfo/>')
        path = self.root/'existing.cbz'
        path.write_bytes(buffer.getvalue())
        result = import_cbz(path)
        self.assertEqual(result['data'], path.read_bytes())
        self.assertEqual([p['path'] for p in result['image_pages']], ['1.png', '2.png', '10.png'])
        verify_cbz(result['data'], result)

    def test_bad_archives_and_unsafe_paths_are_rejected_without_extraction(self):
        for name in ('../page.png', '/page.png', 'C:/page.png', 'folder\\page.png'):
            buffer = BytesIO()
            with ZipFile(buffer, 'w') as archive:
                archive.writestr(name, self.first.read_bytes())
            raw = buffer.getvalue()
            if '\\' in name:
                # Windows normalizes names when writing ZIP entries. Exercise
                # a file received from another system with literal backslashes.
                raw = raw.replace(name.replace('\\', '/').encode(), name.encode())
            with self.subTest(name=name), self.assertRaises(ValueError):
                inspect_cbz(raw)
        for raw in (b'not a ZIP', b''):
            with self.assertRaises(ValueError):
                inspect_cbz(raw)
        buffer = BytesIO()
        with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('page.png', b'0'*100_000)
        with patch('cbz_tools.MAX_CBZ_BYTES', 2000), self.assertRaises(ValueError):
            inspect_cbz(buffer.getvalue())
        with self.assertRaises(ValueError):
            images_to_cbz([])
        self.assertFalse((self.root.parent/'page.png').exists())

    def test_verifier_rejects_wrong_page_order_hash_and_size(self):
        from copy import deepcopy
        result = images_to_cbz([self.first, self.second])
        for key, value in [('pages', 99), ('bytes', 1)]:
            bad = {**result, key: value}
            with self.assertRaises(ValueError):
                verify_cbz(result['data'], bad)
        bad = deepcopy(result)
        bad['image_pages'].reverse()
        with self.assertRaises(ValueError):
            verify_cbz(result['data'], bad)
        bad = deepcopy(result)
        bad['image_pages'][0]['compression']['lossless'] = True
        with self.assertRaises(ValueError):
            verify_cbz(result['data'], bad)

    def test_manual_pdf_cbz_replace_primary_delete_and_undo_preserve_all_files(self):
        output = self.root/'generated/Console'
        output.mkdir(parents=True)
        original = {'schema_version': 2, 'system': 'Console', 'status': 'complete',
                    'games': {'ID': {'serial': 'ID', 'entries': [], 'images': {}}}}
        (output/'catalog.json').write_bytes(json_bytes(original))
        store = ArtworkStore(self.root)
        pdf_path = self.root/'manual.pdf'
        _, PdfWriter = pdf_api()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.write(pdf_path)
        pdf = optimize_pdf(pdf_path)
        cbz = images_to_cbz([self.first, self.second])
        store.save(output, 'ID', 'manual', 'manual', pdf, create_only=True)
        store.save(output, 'ID', 'manual', 'manual', cbz)
        self.assertFalse((output/'ID/manual.pdf').exists())
        self.assertEqual((output/'ID/manual.cbz').read_bytes(), cbz['data'])
        store.verification_view(output, store.read_catalog(output))
        store.undo(output, 'ID')
        self.assertEqual((output/'ID/manual.pdf').read_bytes(), pdf['data'])
        store.save(output, 'ID', 'manual', 'manual2', cbz, create_only=True)
        change_game(store, output, 'ID', 'manual2', 'primary')
        self.assertEqual((output/'ID/manual.cbz').read_bytes(), cbz['data'])
        self.assertEqual((output/'ID/manual2.pdf').read_bytes(), pdf['data'])
        store.verification_view(output, store.read_catalog(output))
        change_game(store, output, 'ID', 'manual', 'delete')
        store.undo(output, 'ID')
        store.undo(output, 'ID')
        self.assertEqual((output/'ID/manual.pdf').read_bytes(), pdf['data'])
        self.assertEqual((output/'ID/manual2.cbz').read_bytes(), cbz['data'])
        store.undo(output, 'ID')
        store.undo(output, 'ID')
        self.assertEqual(store.read_catalog(output), original)


if __name__ == '__main__':
    unittest.main()
