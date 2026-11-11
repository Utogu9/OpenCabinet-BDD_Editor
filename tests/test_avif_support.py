from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image, features
from editor_store import encode_import
from image_comparison import load_image
from cbz_tools import images_to_cbz, import_cbz, verify_cbz
from console_artwork import valid_filename


class AvifTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(features.check('avif'))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'page.avif'
        Image.new('RGBA', (48, 32), (50, 100, 150, 180)).save(self.path, format='AVIF')

    def test_import_converts_to_webp_and_preserves_dimensions_and_alpha(self):
        result = encode_import(self.path)
        self.assertEqual(result['source_format'], 'AVIF')
        self.assertEqual((result['width'], result['height']), (48, 32))
        self.assertTrue(result['alpha'])
        self.assertEqual(result['bytes'], min(result['compression']['candidate_bytes'].values()))
        with Image.open(BytesIO(result['data'])) as image:
            self.assertEqual(image.format, 'WEBP')

    def test_preview_and_console_filename(self):
        image = load_image(self.path)
        self.assertEqual(image['format'], 'AVIF')
        self.assertEqual(valid_filename('logo2', 'logo2.avif'), 'logo2.avif')

    def test_manual_creation_and_existing_avif_cbz(self):
        result = images_to_cbz([self.path])
        verify_cbz(result['data'], result)
        with ZipFile(BytesIO(result['data'])) as archive:
            self.assertEqual(archive.namelist(), ['0001.webp'])
        path = self.path.with_suffix('.cbz')
        with ZipFile(path, 'w') as archive:
            archive.write(self.path, '0001.avif')
        existing = import_cbz(path)
        verify_cbz(existing['data'], existing)
        self.assertEqual(existing['image_pages'][0]['path'], '0001.avif')

    def test_animated_avif_is_rejected(self):
        with Image.open(self.path) as image:
            image.save(self.path.with_name('animated.avif'), format='AVIF', save_all=True,
                       append_images=[Image.new('RGBA', image.size, 'red')], duration=100)
        with self.assertRaises(ValueError):
            encode_import(self.path.with_name('animated.avif'))


class EncodingSelectionTests(unittest.TestCase):
    def test_avif_game_replacement_verification_and_undo(self):
        import json
        from editor_store import ArtworkStore
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root/'generated/Console'
            output.mkdir(parents=True)
            (output/'catalog.json').write_text(json.dumps({
                'schema_version': 2, 'system': 'Console', 'status': 'complete',
                'games': {'ID': {'serial': 'ID', 'entries': [], 'images': {}}}}))
            source = root/'source.png'
            Image.new('RGB', (40, 30), 'blue').save(source)
            store = ArtworkStore(root)
            webp = encode_import(source, encoding='webp')
            avif = encode_import(source, encoding='avif')
            self.assertEqual(avif['extension'], 'avif')
            self.assertEqual(avif['compression']['quality'], 60)
            store.save(output, 'ID', 'cover_front', 'cover_front', webp)
            store.save(output, 'ID', 'cover_front', 'cover_front', avif)
            asset = store.read_catalog(output)['games']['ID']['images']['cover_front']
            self.assertEqual(asset['path'], 'ID/cover_front.avif')
            self.assertFalse((output/'ID/cover_front.webp').exists())
            store.verification_view(output, store.read_catalog(output))
            store.undo(output, 'ID')
            self.assertEqual((output/'ID/cover_front.webp').read_bytes(), webp['data'])
            self.assertFalse((output/'ID/cover_front.avif').exists())

    def test_console_avif_and_webp_replacement(self):
        import json
        from editor_store import ArtworkStore
        from console_artwork import ConsoleArtwork
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root/'generated/Console'
            output.mkdir(parents=True)
            (output/'catalog.json').write_text(json.dumps({
                'schema_version': 2, 'system': 'Console', 'status': 'complete', 'games': {}}))
            source = root/'source.png'
            Image.new('RGB', (40, 30), 'red').save(source)
            console = ConsoleArtwork(ArtworkStore(root))
            console.save(output, 'logo', encode_import(source, encoding='webp'))
            console.save(output, 'logo', encode_import(source, encoding='avif'))
            self.assertEqual(console.images(output)['logo']['path'], 'logo.avif')
            self.assertFalse((output/'logo.webp').exists())
            console.undo(output)
            self.assertTrue((output/'logo.webp').exists())
            self.assertFalse((output/'logo.avif').exists())

    def test_encoding_preference_preserves_other_settings(self):
        from editor_settings import update_settings, read_settings
        from artwork_editor import Editor
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'editor-setting.json'
            update_settings({'language': 'es', 'library': 'example'}, path)
            editor = Editor.__new__(Editor)
            editor.busy = False
            editor.image_encoding = 'avif'
            editor.settings_file = path
            editor.encoding_button = Mock()
            editor.toggle_encoding()
            self.assertEqual(read_settings(path)['image_encoding'], 'webp')
            self.assertEqual(read_settings(path)['language'], 'es')
            editor.toggle_encoding()
            self.assertEqual(read_settings(path)['image_encoding'], 'avif')
