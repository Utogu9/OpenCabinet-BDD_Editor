import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from dat_catalog import DatCache
from editor_store import ArtworkStore, encode_import
from game_registration import GameRegistration
import game_registration


def dat(games, system='Sony - PlayStation'):
    return ('<datafile><header><name>'+system+'</name><version>fixture</version></header>'+games+'</datafile>').encode()


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = ArtworkStore(self.root)
        self.registry = GameRegistration(self.store)
        self.output = self.root/'generated/Sony - PlayStation'
        self.output.mkdir(parents=True)
        self.cache = DatCache(self.root/'cache')
        self.catalog = self.cache.import_bytes('Sony - PlayStation','redump',dat(
            '<game id="2" name="New Game (USA)"><serial>SLUS 12345, SLUS-12346</serial></game>'
            '<game id="3" name="Other Edition (USA)"><serial>SLUS-12345</serial></game>'))
        original = self.root/'original.png'
        Image.new('RGB',(8,8),'red').save(original)
        encoded = encode_import(original)
        folder = self.output/'SLUS-00001'
        folder.mkdir()
        (folder/'cover_front.webp').write_bytes(encoded['data'])
        asset = {k:encoded[k] for k in ('sha256','bytes','width','height','alpha','compression')}
        asset.update({'path':'SLUS-00001/cover_front.webp','kind':'cover_front','sources':[]})
        self.initial = {'schema_version':2,'system':'Sony - PlayStation','status':'complete',
            'dat':{'sha256':'original-dat-hash'},'games':{'SLUS-00001':{
                'serial':'SLUS-00001','serial_identifiers':['SLUS-00001'],
                'entries':[{'name':'Existing (USA)','provider':'redump','redump_id':'1'}],
                'images':{'cover_front':asset}}}}
        self.write(self.initial)
        imported = self.root/'import.png'
        Image.new('RGBA',(8,8),(5,100,190,160)).save(imported)
        self.encoded = encode_import(imported)

    def write(self, value):
        (self.output/'catalog.json').write_text(json.dumps(value),encoding='utf-8')

    def read(self):
        return json.loads((self.output/'catalog.json').read_text(encoding='utf-8'))

    def test_multiple_ids_shared_serial_and_no_duplicate_registration(self):
        self.registry.add(self.output,self.catalog,'2',['SLUS-12345','SLUS-12346'])
        self.assertTrue((self.output/'SLUS-12346').is_dir())
        self.assertEqual(self.read()['dat'],self.initial['dat'])
        game = self.read()['games']['SLUS-12345']
        self.assertEqual(game['entries'][0]['name'],'New Game (USA)')
        self.assertEqual(game['editor_added_entries'][0]['dat']['sha256'],self.catalog.provenance['sha256'])
        self.registry.add(self.output,self.catalog,'3',['SLUS-12345'])
        self.assertEqual(len(self.read()['games']['SLUS-12345']['entries']),2)
        history = self.registry.paths(self.output)[0].read_bytes()
        self.assertTrue(self.registry.add(self.output,self.catalog,'3',['SLUS-12345'])[0]['existing'])
        self.assertEqual(history,self.registry.paths(self.output)[0].read_bytes())
        self.registry.undo(self.output)
        self.assertEqual(len(self.read()['games']['SLUS-12345']['entries']),1)
        self.registry.undo(self.output)
        self.assertEqual(self.read(),self.initial)

    def test_registration_undo_preserves_later_metadata_edits_on_existing_game(self):
        from metadata_store import MetadataStore
        new = self.cache.import_bytes('Sony - PlayStation','redump',dat(
            '<game id="4" name="Another Revision (USA)"><serial>SLUS-00001</serial></game>'))
        self.registry.add(self.output, new, '4', ['SLUS-00001'])
        editor = MetadataStore(self.store)
        snap = editor.snapshot(self.output, 'SLUS-00001')
        value = {'descriptions': {'en': 'Keep this metadata'}}
        editor.save(self.output, 'SLUS-00001', value, snap['token'])
        self.registry.undo(self.output)
        game = self.read()['games']['SLUS-00001']
        self.assertEqual(game['entries'], self.initial['games']['SLUS-00001']['entries'])
        self.assertEqual(game['metadata_overrides'], value)
        self.assertEqual(game['images'], self.initial['games']['SLUS-00001']['images'])

    def test_manual_artwork_history_and_new_games_survive_each_other(self):
        self.store.save(self.output,'SLUS-00001','cover_front','cover_front',self.encoded)
        self.registry.add(self.output,self.catalog,'2',['SLUS-12345'])
        self.assertEqual((self.output/'SLUS-00001/cover_front.webp').read_bytes(),self.encoded['data'])
        self.store.undo(self.output,'SLUS-00001')
        self.assertIn('SLUS-12345',self.read()['games'])
        self.store.save(self.output,'SLUS-12345','cover_front','cover_front',self.encoded)
        before = (self.output/'catalog.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'images'):
            self.registry.undo(self.output)
        self.assertEqual((self.output/'catalog.json').read_bytes(),before)
        self.store.undo(self.output,'SLUS-12345')
        self.registry.undo(self.output)
        self.assertNotIn('SLUS-12345',self.read()['games'])
        self.assertFalse((self.output/'SLUS-12345').exists())

    def test_registration_rollback_keeps_catalogue_and_manual_state(self):
        self.store.save(self.output,'SLUS-00001','cover_front','cover_front',self.encoded)
        before = (self.output/'catalog.json').read_bytes()
        state = self.store.state_path(self.output).read_bytes()
        real = game_registration.atomic_bytes
        failed = False
        def write(path, data):
            nonlocal failed
            if Path(path).name == 'history.json' and not failed:
                failed = True
                raise OSError('Simulated disk failure')
            return real(path,data)
        with patch.object(game_registration,'atomic_bytes',side_effect=write), self.assertRaises(OSError):
            self.registry.add(self.output,self.catalog,'2',['SLUS-12345'])
        self.assertEqual((self.output/'catalog.json').read_bytes(),before)
        self.assertEqual(self.store.state_path(self.output).read_bytes(),state)
        self.assertFalse((self.output/'SLUS-12345').exists())
        self.assertFalse(self.registry.has_pending(self.output))

    def test_durable_journal_recovers_interrupted_registration(self):
        self.store.save(self.output,'SLUS-00001','cover_front','cover_front',self.encoded)
        before = (self.output/'catalog.json').read_bytes()
        real_write = game_registration.atomic_bytes
        def fail_history(path,data):
            if Path(path).name == 'history.json':
                raise OSError('Interrupted write')
            real_write(path,data)
        # Initial recovery is empty; interrupt the immediate rollback as if
        # the process stopped. A fresh call must recover from the durable log.
        with patch.object(game_registration,'atomic_bytes',side_effect=fail_history), \
             patch.object(self.registry,'_recover',side_effect=[None,OSError('Process stopped')]), \
             self.assertRaises(OSError):
            self.registry.add(self.output,self.catalog,'2',['SLUS-12345'])
        self.assertTrue(self.registry.has_pending(self.output))
        self.registry.recover(self.output)
        self.assertEqual((self.output/'catalog.json').read_bytes(),before)
        self.assertFalse((self.output/'SLUS-12345').exists())
        self.assertEqual((self.output/'SLUS-00001/cover_front.webp').read_bytes(),self.encoded['data'])

    def test_collisions_with_old_catalogue_and_unknown_folders_are_refused(self):
        another = self.cache.import_bytes('Sony - PlayStation','redump',dat(
            '<game id="5" name="Slash (USA)"><serial>ABC/123</serial></game>'))
        current = self.read()
        current['games']['ABC-123']={'serial':'ABC-123','serial_identifiers':['ABC-123'],'entries':[],'images':{}}
        self.write(current)
        with self.assertRaisesRegex(ValueError,'another identifier'):
            self.registry.add(self.output,another,'5',['ABC/123'])
        (self.output/'SLUS-12345').mkdir()
        (self.output/'SLUS-12345/keep.txt').write_text('do not delete')
        with self.assertRaisesRegex(ValueError,'will not be overwritten'):
            self.registry.add(self.output,self.catalog,'2',['SLUS-12345'])
        self.assertTrue((self.output/'SLUS-12345/keep.txt').exists())

    def test_invalid_selection_lock_and_unfinished_conversion_do_not_write(self):
        before = (self.output/'catalog.json').read_bytes()
        with self.assertRaises(ValueError):
            self.registry.add(self.output,self.catalog,'2',['invented'])
        with self.store.writer(), self.assertRaises(ValueError):
            self.registry.add(self.output,self.catalog,'2',['SLUS-12345'])
        (self.output/'checkpoint.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.registry.add(self.output,self.catalog,'2',['SLUS-12345'])
        self.assertEqual((self.output/'catalog.json').read_bytes(),before)

    def test_new_console_uses_schema_two_and_keeps_official_serial(self):
        output = self.root/'generated/Nintendo - Game Boy Advance'
        gba = self.cache.import_bytes('Nintendo - Game Boy Advance','no-intro',dat(
            '<game id="1" name="Example (USA)"><serial>AGB-TEST-USA</serial></game>',
            'Nintendo - Game Boy Advance'))
        self.registry.add(output,gba,'1',['AGB-TEST-USA'])
        catalog = json.loads((output/'catalog.json').read_text(encoding='utf-8'))
        self.assertEqual(catalog['schema_version'],2)
        self.assertEqual(catalog['games']['AGB-TEST-USA']['serial_identifiers'],['AGB-TEST-USA'])


if __name__=='__main__':
    unittest.main()
