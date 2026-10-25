import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from console_artwork import ConsoleArtwork, CONSOLE_KINDS
from editor_store import ArtworkStore, encode_import


class ConsoleArtworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root/'generated/Console'
        self.output.mkdir(parents=True)
        self.catalog = b'{"schema_version":2,"system":"Console","status":"complete","games":{}}'
        (self.output/'catalog.json').write_bytes(self.catalog)
        (self.output/'GAME-ID').mkdir()
        (self.output/'GAME-ID/logo.webp').write_bytes(b'game asset untouched')
        self.image = self.root/'new.png'
        Image.new('RGBA', (24, 20), (30, 60, 210, 150)).save(self.image)
        self.store = ArtworkStore(self.root)
        self.console = ConsoleArtwork(self.store)

    def test_root_assets_do_not_change_games_or_catalogue(self):
        encoded = encode_import(self.image)
        for kind in CONSOLE_KINDS:
            self.console.save(self.output, kind, encoded)
            self.assertEqual((self.output/(kind+'.webp')).read_bytes(), encoded['data'])
        self.assertEqual(set(self.console.images(self.output)), set(CONSOLE_KINDS))
        self.assertEqual((self.output/'catalog.json').read_bytes(), self.catalog)
        self.assertEqual((self.output/'GAME-ID/logo.webp').read_bytes(), b'game asset untouched')
        asset = json.loads((self.output/'console_artwork.json').read_text())['images']['logo']
        self.assertEqual(asset['bytes'], min(asset['compression']['candidate_bytes'].values()))
        self.assertEqual(self.store.read_blob(asset['original_blob']), self.image.read_bytes())

    def test_replace_and_undo_restore_original_root_file(self):
        original = b'previous console artwork'
        (self.output/'logo.webp').write_bytes(original)
        first = encode_import(self.image)
        self.console.save(self.output, 'logo', first)
        Image.new('RGB', (30, 30), 'red').save(self.image)
        self.console.save(self.output, 'logo', encode_import(self.image))
        self.console.undo(self.output, 'logo')
        self.assertEqual((self.output/'logo.webp').read_bytes(), first['data'])
        self.console.undo(self.output)
        self.assertEqual((self.output/'logo.webp').read_bytes(), original)

    def test_batch_lock_and_unsafe_kind_prevent_writes(self):
        encoded = encode_import(self.image)
        with self.assertRaises(ValueError):
            self.console.save(self.output, '../outside', encoded)
        lock = self.root/'reports/batch.lock'
        lock.parent.mkdir()
        lock.write_text('{"pid":123}')
        with self.assertRaises(ValueError):
            self.console.save(self.output, 'logo', encoded)
        self.assertFalse((self.output/'logo.webp').exists())
        self.assertEqual((self.output/'catalog.json').read_bytes(), self.catalog)
        self.assertEqual(lock.read_text(), '{"pid":123}')

    def test_failed_publish_rolls_back_asset_and_metadata(self):
        from console_artwork import atomic_bytes
        def fail(path, data):
            if path.name == 'console_artwork.json':
                raise OSError('simulated write failure')
            return atomic_bytes(path, data)
        with patch('console_artwork.atomic_bytes', side_effect=fail):
            with self.assertRaises(OSError):
                self.console.save(self.output, 'render', encode_import(self.image))
        self.assertFalse((self.output/'render.webp').exists())
        self.assertFalse((self.output/'console_artwork.json').exists())
        self.assertEqual((self.output/'catalog.json').read_bytes(), self.catalog)

    def test_each_console_type_can_add_replace_and_undo_independent_variants(self):
        first = encode_import(self.image)
        Image.new('RGB', (30, 30), 'red').save(self.image)
        second = encode_import(self.image)
        Image.new('RGB', (30, 30), 'green').save(self.image)
        third = encode_import(self.image)
        for kind in CONSOLE_KINDS:
            with self.subTest(kind=kind):
                self.console.save(self.output, kind, first, create_only=True)
                label = self.console.next_label(self.output, kind)
                self.assertEqual(label, kind+'2')
                self.console.save(self.output, kind, second, label, create_only=True)
                self.console.save(self.output, kind, third, label)
                self.assertEqual((self.output/(kind+'.webp')).read_bytes(), first['data'])
                self.assertEqual((self.output/(label+'.webp')).read_bytes(), third['data'])
                self.assertEqual(self.console.images(self.output)[label]['kind'], kind)
                self.console.undo(self.output, label)
                self.assertEqual((self.output/(label+'.webp')).read_bytes(), second['data'])
                self.console.undo(self.output, label)
                self.assertFalse((self.output/(label+'.webp')).exists())
                self.assertEqual((self.output/(kind+'.webp')).read_bytes(), first['data'])

    def test_import_refuses_occupied_label_and_duplicate_bytes(self):
        encoded = encode_import(self.image)
        self.console.save(self.output, 'render', encoded, create_only=True)
        with self.assertRaises(ValueError):
            self.console.save(self.output, 'render', encoded, create_only=True)
        with self.assertRaises(ValueError):
            self.console.save(self.output, 'render', encoded, 'render2', create_only=True)
        self.assertFalse((self.output/'render2.webp').exists())
        (self.output/'render2.webp').write_bytes(b'untracked file')
        self.assertEqual(self.console.next_label(self.output, 'render'), 'render3')
        with self.assertRaises(ValueError):
            self.console.save(self.output, 'render', encoded, 'render2', create_only=True)
        self.assertEqual((self.output/'render2.webp').read_bytes(), b'untracked file')

    def test_variant_paths_are_validated(self):
        encoded = encode_import(self.image)
        for label in ('logo1', 'logo02', '../logo2', 'render2'):
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.console.save(self.output, 'logo', encoded, label)


if __name__ == '__main__':
    unittest.main()
