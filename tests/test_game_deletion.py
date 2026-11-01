from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from PIL import Image
from editor_store import ArtworkStore, encode_import, json_bytes
from game_deletion import GameDeletion
from game_registration import GameRegistration
from metadata_store import MetadataStore
import game_registration


class GameDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = ArtworkStore(self.root)
        self.deletion = GameDeletion(self.store)
        self.output = self.root / 'generated/Console'
        self.output.mkdir(parents=True)
        image = self.root / 'source.png'
        Image.new('RGB', (8, 8), 'blue').save(image)
        self.encoded = encode_import(image)
        games = {}
        for serial in ('ID-1', 'ID-2'):
            folder = self.output / serial
            folder.mkdir()
            (folder / 'cover_front.webp').write_bytes(self.encoded['data'])
            games[serial] = {'serial': serial, 'entries': [{'name': f'Game {serial} (USA)'}],
                             'metadata_id': 'wikidata:Q1', 'images': {'cover_front': {
                                 'kind': 'cover_front', 'path': f'{serial}/cover_front.webp',
                                 'sha256': self.encoded['sha256'], 'bytes': self.encoded['bytes']}}}
        self.initial = {'schema_version': 2, 'system': 'Console', 'status': 'complete',
                        'games': games, 'metadata': {'wikidata:Q1': {'labels': {'en': 'Shared'}}}}
        (self.output / 'catalog.json').write_bytes(json_bytes(self.initial))

    def read(self):
        return json.loads((self.output / 'catalog.json').read_bytes())

    def delete(self, serial='ID-1'):
        preview = self.deletion.preview(self.output, serial)
        return self.deletion.delete(self.output, serial, preview['token'])

    def files(self, directory):
        return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob('*') if p.is_file()}

    def test_removes_entire_folder_and_entry_but_preserves_other_games_and_shared_metadata(self):
        nested = self.output / 'ID-1/extra/empty'
        nested.mkdir(parents=True)
        (nested.parent / 'manual.cbz').write_bytes(b'uncatalogued manual')
        (self.output / 'ID-1/notes.txt').write_text('unlisted file')
        before = self.files(self.output)
        snapshot = self.delete()
        self.assertEqual(snapshot['file_count'], 3)
        self.assertFalse((self.output / 'ID-1').exists())
        catalog = self.read()
        self.assertNotIn('ID-1', catalog['games'])
        self.assertEqual(catalog['games']['ID-2'], self.initial['games']['ID-2'])
        self.assertEqual(catalog['metadata'], self.initial['metadata'])
        self.assertTrue(self.deletion.can_undo(self.output))
        self.assertEqual(self.deletion.undo(self.output), 'ID-1')
        self.assertEqual(self.files(self.output), before)
        self.assertTrue(nested.is_dir())
        self.assertFalse(self.deletion.can_undo(self.output))

    def test_editor_state_and_private_histories_are_retired_and_restored_exactly(self):
        self.store.save(self.output, 'ID-1', 'label', 'label', self.encoded)
        self.store.save(self.output, 'ID-2', 'disc', 'disc', self.encoded)
        metadata = MetadataStore(self.store)
        for serial in ('ID-1', 'ID-2'):
            snapshot = metadata.snapshot(self.output, serial)
            metadata.save(self.output, serial, {'labels': {'en': serial}}, snapshot['token'])
        registration = GameRegistration(self.store)
        path, _ = registration.paths(self.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json_bytes([{'at': 'fixture', 'before': {'ID-1': None, 'ID-2': None},
                                     'after': deepcopy(self.initial['games']), 'created': ['ID-1', 'ID-2']}]))
        before = self.files(self.output)
        private_paths = [self.store.manifest_path('Console', 'ID-1'), self.store.state_path(self.output),
                         metadata.paths(self.output)[0], registration.paths(self.output)[0]]
        private = {p: p.read_bytes() for p in private_paths}
        self.delete()
        self.assertFalse(private_paths[0].exists())
        state = json.loads(private_paths[1].read_bytes())
        self.assertTrue(all(not key.startswith('ID-1/') for key in state['files']))
        base = json.loads(self.store.read_blob(state['base_catalog']))
        self.assertNotIn('ID-1', base['games'])
        events = json.loads(private_paths[2].read_bytes())
        self.assertEqual([e['serial'] for e in events], ['ID-2'])
        registrations = json.loads(private_paths[3].read_bytes())
        self.assertEqual(set(registrations[0]['after']), {'ID-2'})
        self.deletion.undo(self.output)
        self.assertEqual(self.files(self.output), before)
        self.assertEqual({p: p.read_bytes() for p in private_paths}, private)
        self.store.undo(self.output, 'ID-1')
        self.assertFalse((self.output / 'ID-1/label.webp').exists())

    def test_other_artwork_edits_do_not_resurrect_deleted_files_or_catalogue_entries(self):
        self.store.save(self.output, 'ID-1', 'label', 'label', self.encoded)
        self.delete()
        self.store.save(self.output, 'ID-2', 'disc', 'disc', self.encoded)
        self.assertNotIn('ID-1', self.read()['games'])
        self.assertFalse((self.output / 'ID-1').exists())
        self.store.undo(self.output, 'ID-2')
        self.deletion.undo(self.output)
        self.assertTrue((self.output / 'ID-1/label.webp').is_file())

    def test_stale_confirmation_and_changed_restore_destination_do_not_overwrite(self):
        preview = self.deletion.preview(self.output, 'ID-1')
        (self.output / 'ID-1/late.webp').write_bytes(b'new file')
        before = self.files(self.output)
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            self.deletion.delete(self.output, 'ID-1', preview['token'])
        self.assertEqual(self.files(self.output), before)
        self.delete()
        (self.output / 'ID-1').mkdir()
        (self.output / 'ID-1/keep.txt').write_bytes(b'keep')
        before = self.files(self.output)
        with self.assertRaisesRegex(ValueError, 'changed after deletion'):
            self.deletion.undo(self.output)
        self.assertEqual(self.files(self.output), before)

    def test_catalogue_changes_after_deletion_block_undo(self):
        self.delete()
        catalog = self.read()
        catalog['games']['ID-2']['custom'] = 'keep later edit'
        (self.output / 'catalog.json').write_bytes(json_bytes(catalog))
        before = self.files(self.output)
        with self.assertRaisesRegex(ValueError, 'changed after deletion'):
            self.deletion.undo(self.output)
        self.assertEqual(self.files(self.output), before)

    def test_rollback_after_directory_removal_restores_nested_files_and_editor_state(self):
        self.store.save(self.output, 'ID-1', 'label', 'label', self.encoded)
        folder = self.output / 'ID-1/nested'
        folder.mkdir()
        (folder / 'notes.txt').write_bytes(b'backup me')
        before = self.files(self.output)
        state = self.store.state_path(self.output).read_bytes()
        rmdir = Path.rmdir
        def fail(path):
            if path == self.output / 'ID-1':
                raise OSError('Simulated removal failure')
            return rmdir(path)
        with patch.object(Path, 'rmdir', fail), self.assertRaisesRegex(OSError, 'Simulated'):
            self.delete()
        self.assertEqual(self.files(self.output), before)
        self.assertEqual(self.store.state_path(self.output).read_bytes(), state)
        self.assertFalse(self.deletion.has_pending(self.output))

    def test_durable_journal_recovers_interrupted_deletion(self):
        before = self.files(self.output)
        real = game_registration.atomic_bytes
        def fail(path, data):
            if path == self.deletion.paths(self.output)[0]:
                raise OSError('Interrupted write')
            return real(path, data)
        preview = self.deletion.preview(self.output, 'ID-1')
        with patch.object(game_registration, 'atomic_bytes', side_effect=fail), \
             patch.object(self.deletion, '_recover', side_effect=[None, OSError('Process stopped')]), \
             self.assertRaises(OSError):
            self.deletion.delete(self.output, 'ID-1', preview['token'])
        self.assertTrue(self.deletion.has_pending(self.output))
        GameDeletion(self.store).recover(self.output)
        self.assertEqual(self.files(self.output), before)
        self.assertFalse(self.deletion.has_pending(self.output))

    def test_invalid_paths_foreign_asset_and_unfinished_console_are_refused(self):
        before = self.files(self.output)
        for serial in ('..', '../ID-1', 'missing'):
            with self.assertRaises(ValueError):
                self.deletion.preview(self.output, serial)
        with self.store.writer(), self.assertRaises(ValueError):
            self.deletion.preview(self.output, 'ID-1')
        (self.output / 'checkpoint.json').write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.deletion.preview(self.output, 'ID-1')
        (self.output / 'checkpoint.json').unlink()
        self.assertEqual(self.files(self.output), before)
        catalog = self.read()
        catalog['games']['ID-1']['images']['cover_front']['path'] = 'ID-2/cover_front.webp'
        (self.output / 'catalog.json').write_bytes(json_bytes(catalog))
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.deletion.preview(self.output, 'ID-1')

    def test_links_are_refused_without_touching_their_targets(self):
        target = self.root / 'external.txt'
        target.write_bytes(b'do not touch')
        link = self.output / 'ID-1/link.txt'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Symlink creation requires developer mode or privileges')
        with self.assertRaises(ValueError):
            self.deletion.preview(self.output, 'ID-1')
        self.assertEqual(target.read_bytes(), b'do not touch')
        self.assertIn('ID-1', self.read()['games'])


if __name__ == '__main__':
    unittest.main()
