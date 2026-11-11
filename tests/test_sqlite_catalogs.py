"""SQLite libraries exercise the same journals and editing actions as JSON."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
import catalog_sqlite
from catalog_io import catalog_path, read_catalog, encode_catalog, decode_catalog
from editor_store import ArtworkStore, encode_import
from editor_location import valid_library, selected_library
from game_registration import GameRegistration
from game_deletion import GameDeletion
from metadata_store import MetadataStore
from console_artwork import ConsoleArtwork
from artwork_actions import change_game
from dat_catalog import DatCache
import game_registration


class SqliteCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root/'generated'/'Sony - PlayStation'
        self.output.mkdir(parents=True)
        self.store = ArtworkStore(self.root)
        self.path = self.output/'catalog.sqlite'
        self.original = {'schema_version': 2, 'system': 'Sony - PlayStation', 'status': 'complete',
                         'games': {'ID': {'serial': 'ID', 'serial_identifiers': ['ID'],
                             'entries': [{'name': 'Game (USA)'}], 'images': {}, 'metadata_id': 'shared'}},
                         'metadata': {'shared': {'labels': {'en': 'Game', 'es': 'Juego'},
                             'fields': {'developer': [{'value': 'Developer', 'rank': 'normal'}]}}},
                         'custom': {'null': None, 'empty': {}, 'array': [], 'bool': False,
                                    'int': 0, 'float': 1.25, 'text': '\u65e5\u672c\u8a9e'}}
        self.path.write_bytes(encode_catalog(self.original, self.path))
        source = self.root/'import.png'
        Image.new('RGB', (12, 10), 'red').save(source)
        self.webp = encode_import(source)
        self.avif = encode_import(source, encoding='avif')

    def read(self):
        self.assertFalse((self.output/'catalog.json').exists())
        return self.store.read_catalog(self.output)

    def test_lossless_native_relational_round_trip_and_deduplication(self):
        self.assertEqual(self.read(), self.original)
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual(db.execute('SELECT serial FROM games').fetchall(), [('ID',)])
        self.assertEqual(db.execute('SELECT count(*) FROM texts WHERE value=?', ('normal',)).fetchone()[0], 1)
        self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())

    def test_discovery_sqlite_precedence_and_checkpoint(self):
        self.assertTrue(valid_library(self.output.parent))
        self.assertEqual(selected_library(self.root), self.output.parent)
        self.assertEqual(self.store.libraries()[0]['index'], self.path)
        stale = self.output/'catalog.json'
        stale.write_text('{"stale":true}')
        self.assertEqual(catalog_path(self.output), self.path)
        metadata = MetadataStore(self.store)
        snap = metadata.snapshot(self.output, 'ID')
        metadata.save(self.output, 'ID', {'labels': {'en': 'Edited'}}, snap['token'])
        self.assertEqual(stale.read_text(), '{"stale":true}')
        checkpoint = self.output/'checkpoint.json'
        checkpoint.write_text(json.dumps(self.original))
        self.assertEqual(self.store.catalog_path(self.output, checkpoint=True), checkpoint)
        with self.assertRaisesRegex(ValueError, 'pending conversion'):
            GameRegistration(self.store).add_manual(self.output, 'Sony - PlayStation', 'New', 'SLUS-12345')

    def test_artwork_formats_metadata_and_independent_undo(self):
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front', self.webp)
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front', self.avif)
        asset = self.read()['games']['ID']['images']['cover_front']
        self.assertEqual(asset['path'], 'ID/cover_front.avif')
        metadata = MetadataStore(self.store)
        value = {'descriptions': {'en': 'Custom description'}}
        snap = metadata.snapshot(self.output, 'ID')
        metadata.save(self.output, 'ID', value, snap['token'])
        self.store.verification_view(self.output, self.read())
        self.store.undo(self.output, 'ID')
        self.assertEqual((self.output/'ID/cover_front.webp').read_bytes(), self.webp['data'])
        self.assertEqual(self.read()['games']['ID']['metadata_overrides'], value)
        self.store.undo(self.output, 'ID')
        self.assertFalse((self.output/'ID/cover_front.avif').exists())
        snap = metadata.snapshot(self.output, 'ID')
        metadata.undo(self.output, 'ID', snap['token'])
        self.assertEqual(self.read(), self.original)

    def test_variant_promotion_delete_and_undo(self):
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front', self.webp)
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front2', self.avif)
        change_game(self.store, self.output, 'ID', 'cover_front2', 'primary')
        self.assertEqual(self.read()['games']['ID']['images']['cover_front']['format'], 'AVIF')
        change_game(self.store, self.output, 'ID', 'cover_front', 'delete')
        self.assertNotIn('cover_front', self.read()['games']['ID']['images'])
        self.store.undo(self.output, 'ID')
        self.store.undo(self.output, 'ID')
        self.assertEqual(self.read()['games']['ID']['images']['cover_front']['format'], 'WEBP')

    def test_dat_manual_registration_and_undo(self):
        cache = DatCache(self.root/'cache')
        dat = cache.import_bytes('Sony - PlayStation', 'redump',
            b'<datafile><header><name>Sony - PlayStation</name></header>'
            b'<game id="1" name="New Game (USA)"><serial>SLUS-12345</serial></game></datafile>')
        registration = GameRegistration(self.store)
        registration.add(self.output, dat, '1', ['SLUS-12345'])
        self.assertIn('SLUS-12345', self.read()['games'])
        registration.undo(self.output)
        self.assertEqual(self.read(), self.original)
        registration.add_manual(self.output, 'Sony - PlayStation', 'Manual Game (USA)', 'SLUS-99999')
        self.assertIn('SLUS-99999', self.read()['games'])
        registration.undo(self.output)
        self.assertEqual(self.read(), self.original)

    def test_game_deletion_and_byte_exact_restore_with_other_edits(self):
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front', self.avif)
        before = self.path.read_bytes()
        deletion = GameDeletion(self.store)
        snap = deletion.preview(self.output, 'ID')
        deletion.delete(self.output, 'ID', snap['token'])
        self.assertNotIn('ID', self.read()['games'])
        self.assertFalse((self.output/'ID').exists())
        deletion.undo(self.output)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.output/'ID/cover_front.avif').read_bytes(), self.avif['data'])
        self.store.verification_view(self.output, self.read())

    def test_console_metadata_artwork_and_undo(self):
        metadata = MetadataStore(self.store)
        snap = metadata.snapshot(self.output)
        value = {'fields': {'manufacturer': [{'value': 'Sony'}]}}
        metadata.save(self.output, None, value, snap['token'])
        console = ConsoleArtwork(self.store)
        console.save(self.output, 'logo', self.avif)
        self.assertTrue((self.output/'logo.avif').exists())
        console.undo(self.output)
        snap = metadata.snapshot(self.output)
        metadata.undo(self.output, None, snap['token'])
        self.assertEqual(self.read(), self.original)

    def test_failed_metadata_write_restores_original_binary(self):
        before = self.path.read_bytes()
        metadata = MetadataStore(self.store)
        snap = metadata.snapshot(self.output, 'ID')
        real_write = game_registration.atomic_bytes
        calls = 0
        def fail(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated failure')
            real_write(path, data)
        with patch.object(game_registration, 'atomic_bytes', side_effect=fail):
            with self.assertRaises(OSError):
                metadata.save(self.output, 'ID', {'labels': {'en': 'Edit'}}, snap['token'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(metadata.has_pending(self.output))

    def test_external_sqlite_changes_are_not_overwritten(self):
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front', self.webp)
        modified = self.read()
        modified['external'] = True
        self.path.write_bytes(encode_catalog(modified, self.path))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.store.undo(self.output, 'ID')
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_sqlite_and_unknown_versions_do_not_fall_back_to_json(self):
        (self.output/'catalog.json').write_text(json.dumps(self.original))
        self.path.write_bytes(b'not a database')
        self.assertFalse(valid_library(self.output.parent))
        with self.assertRaises(ValueError):
            self.store.read_catalog(self.output)
        self.path.write_bytes(encode_catalog(self.original, self.path))
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA user_version=999')
        db.close()
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            self.store.read_catalog(self.output)

    def test_active_external_database_journal_blocks_edits(self):
        before = self.path.read_bytes()
        self.path.with_name('catalog.sqlite-wal').write_bytes(b'active external transaction')
        with self.assertRaisesRegex(ValueError, 'active journal'):
            self.store.read_catalog(self.output)
        self.assertEqual(self.path.read_bytes(), before)

    def test_python_310_reader_uses_temporary_file_fallback(self):
        real_connect = sqlite3.connect
        class WithoutDeserialize:
            def __init__(self, db):
                self.db = db
            def __getattr__(self, key):
                if key == 'deserialize':
                    raise AttributeError(key)
                return getattr(self.db, key)
        def connect(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            return WithoutDeserialize(db) if args[0] == ':memory:' else db
        with patch.object(catalog_sqlite.sqlite3, 'connect', side_effect=connect):
            self.assertEqual(self.read(), self.original)


if __name__ == '__main__':
    unittest.main()
