from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from PIL import Image
from editor_store import ArtworkStore, encode_import
from editor_common import write_json
from metadata_store import MetadataStore, effective_metadata, parse_field, format_field, validate
from game_registration import GameRegistration
from dat_catalog import DatCache
import game_registration


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'generated' / 'Sony - PlayStation'
        self.output.mkdir(parents=True)
        self.store = ArtworkStore(self.root)
        self.metadata = MetadataStore(self.store)
        self.record = {'wikidata_id': 'Q123', 'source_url': 'https://www.wikidata.org/wiki/Q123',
                       'license': 'CC0-1.0', 'fields': {'developer': [
                           {'value': {'id': 'Q456'}, 'labels': {'en': 'Shared developer'},
                            'qualifiers': {'P400': [{'value': 'original qualifier'}]},
                            'references': [{'hash': 'keep'}]}]}, 'labels': {'en': 'Shared title'}}
        self.original = {'schema_version': 2, 'system': 'Sony - PlayStation', 'status': 'complete',
                         'dat': {'sha256': 'keep'}, 'games': {
                             serial: {'serial': serial, 'entries': [{'name': 'Game (' + region + ')'}],
                                      'images': {}, 'metadata_id': 'wikidata:Q123'}
                             for serial, region in [('ID-USA', 'USA'), ('ID-EU', 'Europe')]},
                         'metadata': {'wikidata:Q123': self.record},
                         'metadata_sources': {'wikidata': {'license': 'CC0-1.0'}}}
        write_json(self.output / 'catalog.json', self.original)

    def read(self):
        return json.loads((self.output / 'catalog.json').read_text(encoding='utf-8'))

    def save(self, value, serial='ID-USA'):
        snap = self.metadata.snapshot(self.output, serial)
        return self.metadata.save(self.output, serial, value, snap['token'])

    def test_per_serial_changes_preserve_shared_data_other_regions_and_unknown_fields(self):
        value = {'fields': {'developer': parse_field('developer', 'My developer')},
                 'descriptions': {'en': 'My complete synopsis'}, 'custom': {'rating': 5}, 'unknown': {'keep': True}}
        self.assertTrue(self.save(value))
        actual = self.read()
        self.assertEqual(actual['games']['ID-USA']['metadata_overrides'], value)
        self.assertEqual(actual['games']['ID-EU'], self.original['games']['ID-EU'])
        self.assertEqual(actual['metadata'], self.original['metadata'])
        self.assertEqual(actual['metadata_sources'], self.original['metadata_sources'])
        raw = (self.output / 'catalog.json').read_bytes()
        self.assertFalse(self.save(value))
        self.assertEqual((self.output / 'catalog.json').read_bytes(), raw)

    def test_console_fields_and_independent_undo_history(self):
        game = {'fields': {'publisher': parse_field('publisher', 'My publisher')}}
        self.save(game)
        console = {'fields': {'release_date': parse_field('release_date', '1994-12-03'),
                              'developer': parse_field('developer', 'Sony'),
                              'manufacturer': parse_field('manufacturer', 'Sony')}}
        self.save(console, None)
        self.assertEqual(self.read()['console_metadata'], console)
        snap = self.metadata.snapshot(self.output, None)
        self.metadata.undo(self.output, None, snap['token'])
        self.assertNotIn('console_metadata', self.read())
        self.assertEqual(self.read()['games']['ID-USA']['metadata_overrides'], game)
        snap = self.metadata.snapshot(self.output, 'ID-USA')
        self.metadata.undo(self.output, 'ID-USA', snap['token'])
        self.assertEqual(self.read(), self.original)

    def test_empty_override_masks_shared_and_removal_restores_inheritance(self):
        hidden = effective_metadata(self.record, {'fields': {'developer': []}})
        self.assertEqual(hidden['fields']['developer'], [])
        self.assertEqual(effective_metadata(self.record, {})['fields']['developer'], self.record['fields']['developer'])

    def test_stale_dialog_and_batch_lock_prevent_writes(self):
        snap = self.metadata.snapshot(self.output, 'ID-USA')
        self.save({'custom': {'first': True}})
        with self.assertRaisesRegex(ValueError, 'changed while'):
            self.metadata.save(self.output, 'ID-USA', {}, snap['token'])
        raw = (self.output / 'catalog.json').read_bytes()
        with self.store.writer():
            with self.assertRaises(ValueError):
                self.metadata.snapshot(self.output, 'ID-USA')
        self.assertEqual((self.output / 'catalog.json').read_bytes(), raw)

    def test_dates_numbers_validation_and_qualifier_preserving_display(self):
        for date, precision in [('1994', 9), ('1994-12', 10), ('1994-12-03', 11)]:
            values = parse_field('release_date', date)
            self.assertEqual(values[0]['value']['precision'], precision)
            self.assertEqual(format_field(values), date)
        for invalid in ['1994-13', '2023-02-29', 'tomorrow']:
            with self.assertRaises(ValueError):
                parse_field('release_date', invalid)
        for invalid in ['0', '-1', '1.5', '4\n8']:
            with self.assertRaises(ValueError):
                parse_field('max_players', invalid)
        with self.assertRaises(ValueError):
            validate({'fields': {'min_players': parse_field('min_players', '5'),
                                 'max_players': parse_field('max_players', '4')}})
        original = deepcopy(self.record)
        self.assertEqual(format_field(self.record['fields']['developer']), 'Shared developer')
        self.assertEqual(self.record, original)

    def test_metadata_survives_artwork_save_reset_and_base_catalog_restore(self):
        image = self.root / 'new.png'
        Image.new('RGB', (8, 8), 'red').save(image)
        self.store.save(self.output, 'ID-USA', 'cover_front', 'cover_front', encode_import(image))
        image_bytes = (self.output / 'ID-USA' / 'cover_front.webp').read_bytes()
        custom = {'descriptions': {'es': 'Descripción propia'}}
        self.save(custom)
        self.assertEqual((self.output / 'ID-USA' / 'cover_front.webp').read_bytes(), image_bytes)
        self.assertEqual(self.read()['games']['ID-USA']['metadata_overrides'], custom)
        # Validation checks that the artwork journal and its base catalog were
        # updated together; undoing an image must not erase metadata edits.
        self.store.verification_view(self.output, self.read())
        self.store.undo(self.output, 'ID-USA')
        self.assertEqual(self.read()['games']['ID-USA']['metadata_overrides'], custom)
        snap = self.metadata.snapshot(self.output, 'ID-USA')
        self.metadata.undo(self.output, 'ID-USA', snap['token'])
        self.assertEqual(self.read(), self.original)

    def test_interrupted_save_rolls_back_catalog_and_history(self):
        original_bytes = (self.output / 'catalog.json').read_bytes()
        actual_write = game_registration.atomic_bytes
        writes = 0
        def fail_second(path, data):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError('simulated write failure')
            return actual_write(path, data)
        with patch.object(game_registration, 'atomic_bytes', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.save({'custom': {'new': True}})
        self.assertEqual((self.output / 'catalog.json').read_bytes(), original_bytes)
        self.assertFalse(self.metadata.has_pending(self.output))

    def test_new_registration_requires_undoing_metadata_first(self):
        cache = DatCache(self.root / 'cache')
        dat = cache.import_bytes('Sony - PlayStation', 'redump',
            b'<datafile><header><name>Sony - PlayStation</name></header>'
            b'<game id="1" name="New Game (USA)"><serial>SLUS-12345</serial></game></datafile>')
        registration = GameRegistration(self.store)
        registration.add(self.output, dat, '1', ['SLUS-12345'])
        self.save({'descriptions': {'en': 'Keep this'}}, 'SLUS-12345')
        with self.assertRaisesRegex(ValueError, 'metadata changes'):
            registration.undo(self.output)
        snap = self.metadata.snapshot(self.output, 'SLUS-12345')
        self.metadata.undo(self.output, 'SLUS-12345', snap['token'])
        registration.undo(self.output)
        self.assertEqual(self.read(), self.original)


if __name__ == '__main__':
    unittest.main()
