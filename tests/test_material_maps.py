from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from PIL import Image
from artwork_actions import change_game
from artwork_editor import Editor, KINDS
from catalog_io import encode_catalog
from editor_store import ArtworkStore, encode_import
from material_maps import KIND, POLICY, encode_material


class MaterialMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'material.png'
        self.pixels = [(128, 255, 0, 0), (150, 35, 0, 210), (50, 100, 0, 0), (128, 100, 0, 255)]
        self.image = Image.new('RGBA', (2, 2))
        self.image.putdata(self.pixels)
        self.image.save(self.source)

    def test_preserves_every_rgba_value_including_hidden_rgb(self):
        encoded = encode_material(self.source)
        self.assertEqual((encoded['format'], encoded['extension']), ('PNG', 'png'))
        self.assertEqual(encoded['compression']['policy'], POLICY)
        self.assertTrue(encoded['compression']['lossless'])
        with Image.open(BytesIO(encoded['data'])) as image:
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.tobytes(), self.image.tobytes())
            self.assertEqual(image.getpixel((0, 0)), (128, 255, 0, 0))

    def test_lossless_webp_exact_import_and_lossy_rejection(self):
        source = self.source.with_suffix('.webp')
        self.image.save(source, format='WEBP', lossless=True, exact=True)
        encoded = encode_material(source)
        with Image.open(BytesIO(encoded['data'])) as image:
            self.assertEqual(image.tobytes(), self.image.tobytes())
        self.image.save(source, format='WEBP', quality=90)
        with self.assertRaisesRegex(ValueError, 'lossless|sin pérdida'):
            encode_material(source)

    def test_no_rotation_resizing_or_color_metadata(self):
        exif = Image.Exif()
        exif[274] = 6
        image = Image.new('RGBA', (2500, 3), (120, 30, 0, 80))
        image.save(self.source, exif=exif, icc_profile=b'profile is metadata, not a transform')
        encoded = encode_material(self.source)
        self.assertEqual((encoded['width'], encoded['height']), (2500, 3))
        with Image.open(BytesIO(encoded['data'])) as converted:
            self.assertEqual(converted.tobytes(), image.tobytes())
            self.assertFalse(converted.info)

    def test_rejects_non_rgba_png_jpeg_avif_and_animation(self):
        for mode, file_format in [('RGB', 'PNG'), ('P', 'PNG'), ('RGB', 'JPEG'), ('RGBA', 'AVIF')]:
            with self.subTest(mode=mode, format=file_format):
                source = self.root / ('source.' + file_format.lower())
                Image.new(mode, (8, 8)).save(source, format=file_format)
                with self.assertRaises(ValueError):
                    encode_material(source)
        self.image.save(self.source, save_all=True, append_images=[Image.new('RGBA', (2, 2), 'red')])
        with self.assertRaises(ValueError):
            encode_material(self.source)

    def test_ui_uses_material_encoder_even_when_avif_selected(self):
        editor = Editor.__new__(Editor)
        editor.can_edit = Mock(return_value=True)
        editor.console_mode = False
        editor.current_output, editor.serial = self.root, 'ID'
        editor.image_encoding = 'avif'
        editor.window = Mock()
        editor.note = Mock()
        editor.store = Mock()
        editor.update_buttons = Mock()
        editor.reload_game = Mock()
        editor.edit_failed = Mock()
        editor.task = lambda work, done, failed: done(work())
        with patch('artwork_editor.filedialog.askopenfilename', return_value=str(self.source)) as dialog, \
             patch('artwork_editor.encode_import', side_effect=AssertionError('Never use lossy artwork encoder')), \
             patch('artwork_editor.localize'):
            editor.import_image(KIND, KIND, create_only=True)
        encoded = editor.store.save.call_args.args[4]
        self.assertEqual(encoded['format'], 'PNG')
        self.assertTrue(editor.store.save.call_args.kwargs['create_only'])
        self.assertIn('*.png *.webp', str(dialog.call_args.kwargs['filetypes']))
        self.assertIn(KIND, KINDS)

    def test_json_sqlite_variants_replace_primary_delete_and_undo(self):
        for suffix in ('.json', '.sqlite'):
            with self.subTest(suffix=suffix):
                root = self.root / suffix[1:]
                output = root / 'generated/Console'
                output.mkdir(parents=True)
                store = ArtworkStore(root)
                index = output / ('catalog' + suffix)
                baseline = {'schema_version': 2, 'system': 'Console', 'status': 'complete',
                            'games': {'ID': {'serial': 'ID', 'entries': [], 'images': {}}}}
                index.write_bytes(encode_catalog(baseline, index))
                first = encode_material(self.source)
                store.save(output, 'ID', KIND, KIND, first, create_only=True)
                self.image.putpixel((0, 0), (100, 20, 0, 0))
                second_path = root / 'other.png'
                self.image.save(second_path)
                second = encode_material(second_path)
                store.save(output, 'ID', KIND, KIND + '2', second, create_only=True)
                with self.assertRaises(ValueError):
                    store.save(output, 'ID', KIND, KIND + '3', second, create_only=True)
                store.verification_view(output, store.read_catalog(output))
                change_game(store, output, 'ID', KIND + '2', 'primary')
                self.assertEqual((output / 'ID' / (KIND + '.png')).read_bytes(), second['data'])
                self.assertEqual((output / 'ID' / (KIND + '2.png')).read_bytes(), first['data'])
                store.undo(output, 'ID')
                self.image.putpixel((1, 0), (110, 80, 0, 255))
                self.image.save(second_path)
                replacement = encode_material(second_path)
                store.save(output, 'ID', KIND, KIND, replacement)
                store.verification_view(output, store.read_catalog(output))
                store.undo(output, 'ID')
                self.assertEqual((output / 'ID' / (KIND + '.png')).read_bytes(), first['data'])
                change_game(store, output, 'ID', KIND + '2', 'delete')
                self.assertFalse((output / 'ID' / (KIND + '2.png')).exists())
                store.undo(output, 'ID')
                self.assertEqual((output / 'ID' / (KIND + '2.png')).read_bytes(), second['data'])
                self.assertFalse(index.with_suffix('.sqlite' if suffix == '.json' else '.json').exists())
                # Restore the shared test image before exercising the next catalogue format.
                self.image.putdata(self.pixels)

    def test_store_rejects_regular_lossy_encoding_for_material(self):
        root = self.root
        output = root / 'generated/Console'
        output.mkdir(parents=True)
        with self.assertRaises(ValueError):
            ArtworkStore(root).save(output, 'ID', KIND, KIND, encode_import(self.source, encoding='avif'))


if __name__ == '__main__':
    unittest.main()
