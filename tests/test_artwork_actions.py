from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from artwork_actions import change_game, change_console
from console_artwork import ConsoleArtwork
from editor_store import ArtworkStore, encode_import, atomic_bytes, json_bytes
from metadata_store import MetadataStore
from pdf_tools import pdf_api, optimize_pdf
from svg_tools import encode_svg


class ArtworkActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root/'generated/Console'
        (self.output/'ID').mkdir(parents=True)
        self.store = ArtworkStore(self.root)
        self.console = ConsoleArtwork(self.store)
        self.source = self.root/'source.png'
        self.encoded = []
        for color in ('red', 'green', 'blue'):
            Image.new('RGB', (20, 24), color).save(self.source)
            self.encoded.append(encode_import(self.source))
        self.original = {'schema_version': 2, 'system': 'Console', 'status': 'complete',
                         'games': {'ID': {'serial': 'ID', 'entries': [{'name': 'Game (USA)'}], 'images': {}}}}
        for label, encoded in zip(('cover_front', 'cover_front2'), self.encoded):
            asset = {k: deepcopy(encoded[k]) for k in ('sha256', 'bytes', 'width', 'height', 'alpha', 'compression')}
            asset.update({'kind': 'cover_front', 'path': f'ID/{label}.webp',
                          'sources': [{'author': label, 'license': 'keep'}], 'custom': {'keep': label}})
            self.original['games']['ID']['images'][label] = asset
            (self.output/asset['path']).write_bytes(encoded['data'])
        (self.output/'catalog.json').write_bytes(json_bytes(self.original))

    def catalog(self):
        return self.store.read_catalog(self.output)

    def test_delete_existing_file_and_undo_restore_exact_bytes_credits_and_catalogue(self):
        before = (self.output/'catalog.json').read_bytes()
        change_game(self.store, self.output, 'ID', 'cover_front', 'delete')
        self.assertNotIn('cover_front', self.catalog()['games']['ID']['images'])
        self.assertFalse((self.output/'ID/cover_front.webp').exists())
        self.store.verification_view(self.output, self.catalog())
        self.store.undo(self.output, 'ID')
        self.assertEqual((self.output/'catalog.json').read_bytes(), before)
        self.assertEqual((self.output/'ID/cover_front.webp').read_bytes(), self.encoded[0]['data'])

    def test_swap_existing_files_preserves_full_records_and_one_undo_restores_both(self):
        change_game(self.store, self.output, 'ID', 'cover_front2', 'primary')
        images = self.catalog()['games']['ID']['images']
        for target, source, encoded in [('cover_front', 'cover_front2', self.encoded[1]), ('cover_front2', 'cover_front', self.encoded[0])]:
            expected = {**self.original['games']['ID']['images'][source], 'path': f'ID/{target}.webp'}
            self.assertEqual(images[target], expected)
            self.assertEqual((self.output/images[target]['path']).read_bytes(), encoded['data'])
        self.store.verification_view(self.output, self.catalog())
        self.store.undo(self.output, 'ID')
        self.assertEqual(self.catalog(), self.original)

    def test_promotion_when_primary_is_missing_and_metadata_changes_survive_undo(self):
        change_game(self.store, self.output, 'ID', 'cover_front', 'delete')
        change_game(self.store, self.output, 'ID', 'cover_front2', 'primary')
        self.assertFalse((self.output/'ID/cover_front2.webp').exists())
        self.assertEqual((self.output/'ID/cover_front.webp').read_bytes(), self.encoded[1]['data'])
        metadata = MetadataStore(self.store)
        snapshot = metadata.snapshot(self.output, 'ID')
        metadata.save(self.output, 'ID', {'descriptions': {'en': 'Keep my metadata'}}, snapshot['token'])
        self.store.undo(self.output, 'ID')
        self.assertFalse((self.output/'ID/cover_front.webp').exists())
        self.assertEqual((self.output/'ID/cover_front2.webp').read_bytes(), self.encoded[1]['data'])
        self.assertEqual(self.catalog()['games']['ID']['metadata_overrides']['descriptions']['en'], 'Keep my metadata')
        self.store.undo(self.output, 'ID')
        self.assertEqual((self.output/'ID/cover_front.webp').read_bytes(), self.encoded[0]['data'])

    def test_new_import_can_be_deleted_undone_and_replaced_after_swap(self):
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front3', self.encoded[2], create_only=True)
        change_game(self.store, self.output, 'ID', 'cover_front3', 'delete')
        self.store.undo(self.output, 'ID')
        change_game(self.store, self.output, 'ID', 'cover_front3', 'primary')
        self.assertEqual((self.output/'ID/cover_front.webp').read_bytes(), self.encoded[2]['data'])
        self.store.verification_view(self.output, self.catalog())
        Image.new('RGB', (20, 24), 'yellow').save(self.source)
        self.store.save(self.output, 'ID', 'cover_front', 'cover_front', encode_import(self.source))
        self.store.undo(self.output, 'ID')
        self.assertEqual((self.output/'ID/cover_front.webp').read_bytes(), self.encoded[2]['data'])
        self.store.undo(self.output, 'ID')
        self.store.undo(self.output, 'ID')
        self.assertFalse((self.output/'ID/cover_front3.webp').exists())
        self.assertEqual(self.catalog(), self.original)

    def test_untracked_png_delete_swap_and_undo_preserve_original_untracked_state(self):
        self.source = self.output/'ID/inlay2.png'
        Image.new('RGB', (32, 24), 'purple').save(self.source)
        raw = self.source.read_bytes()
        change_game(self.store, self.output, 'ID', 'inlay2', 'delete')
        self.assertFalse(self.source.exists())
        self.store.undo(self.output, 'ID')
        self.assertEqual(self.source.read_bytes(), raw)
        change_game(self.store, self.output, 'ID', 'inlay2', 'primary')
        self.assertEqual((self.output/'ID/inlay.png').read_bytes(), raw)
        self.assertFalse(self.source.exists())
        self.store.verification_view(self.output, self.catalog())
        self.store.undo(self.output, 'ID')
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertFalse((self.output/'ID/inlay.png').exists())
        self.assertEqual(self.catalog(), self.original)

    def test_pdf_manual_variants_swap_delete_and_undo_without_recompression(self):
        for number in range(2):
            source = self.root/f'manual{number}.pdf'
            _, PdfWriter = pdf_api()
            writer = PdfWriter()
            writer.add_blank_page(width=200+number, height=300)
            writer.write(source)
            self.store.save(self.output, 'ID', 'manual', 'manual' if number == 0 else 'manual2', optimize_pdf(source), create_only=True)
        first, second = [(self.output/'ID'/name).read_bytes() for name in ('manual.pdf', 'manual2.pdf')]
        change_game(self.store, self.output, 'ID', 'manual2', 'primary')
        self.assertEqual((self.output/'ID/manual.pdf').read_bytes(), second)
        self.assertEqual((self.output/'ID/manual2.pdf').read_bytes(), first)
        self.store.verification_view(self.output, self.catalog())
        change_game(self.store, self.output, 'ID', 'manual', 'delete')
        self.store.undo(self.output, 'ID')
        self.store.undo(self.output, 'ID')
        self.assertEqual((self.output/'ID/manual.pdf').read_bytes(), first)
        self.assertEqual((self.output/'ID/manual2.pdf').read_bytes(), second)

    def test_replacement_after_promoting_untracked_png_keeps_undo_chain(self):
        before = {}
        for label, color in [('inlay', 'purple'), ('inlay2', 'yellow')]:
            path = self.output/'ID'/f'{label}.png'
            Image.new('RGB', (32, 24), color).save(path)
            before[label] = path.read_bytes()
        change_game(self.store, self.output, 'ID', 'inlay2', 'primary')
        self.store.save(self.output, 'ID', 'inlay', 'inlay', self.encoded[2])
        self.assertFalse((self.output/'ID/inlay.png').exists())
        self.assertEqual((self.output/'ID/inlay.webp').read_bytes(), self.encoded[2]['data'])
        self.store.verification_view(self.output, self.catalog())
        self.store.undo(self.output, 'ID')
        self.assertEqual((self.output/'ID/inlay.png').read_bytes(), before['inlay2'])
        self.store.undo(self.output, 'ID')
        self.assertEqual(self.catalog(), self.original)
        for label, raw in before.items():
            self.assertEqual((self.output/'ID'/f'{label}.png').read_bytes(), raw)

    def test_stale_game_asset_and_locked_library_are_not_changed(self):
        expected = self.encoded[1]['sha256']
        target = self.output/'ID/cover_front2.webp'
        target.write_bytes(b'Changed externally')
        with self.assertRaises(ValueError):
            change_game(self.store, self.output, 'ID', 'cover_front2', 'primary', expected)
        self.assertEqual(target.read_bytes(), b'Changed externally')
        self.assertEqual(self.catalog(), self.original)
        with self.store.writer(), self.assertRaises(ValueError):
            change_game(self.store, self.output, 'ID', 'cover_front', 'delete')

    def test_failed_game_swap_rolls_back_files_manifest_and_catalogue(self):
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path.name == 'cover_front2.webp' and not failed:
                failed = True
                raise OSError('disk failure')
            return atomic_bytes(path, data)
        with patch('editor_store.atomic_bytes', side_effect=fail_once), self.assertRaises(OSError):
            change_game(self.store, self.output, 'ID', 'cover_front2', 'primary')
        self.assertEqual(self.catalog(), self.original)
        for label, encoded in zip(('cover_front', 'cover_front2'), self.encoded):
            self.assertEqual((self.output/'ID'/f'{label}.webp').read_bytes(), encoded['data'])

    def test_console_svg_webp_swap_preserves_attribution_and_undo(self):
        source = self.root/'logo.svg'
        source.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="50" height="30"><rect width="50" height="30" fill="red"/></svg>')
        svg = encode_svg(source)
        svg['sources'] = [{'author': 'SVG artist', 'license': 'CC BY-SA'}]
        svg['manual'] = False
        original = self.console.save(self.output, 'logo', svg)
        variant = self.console.save(self.output, 'logo', self.encoded[1], 'logo2', create_only=True)
        change_console(self.console, self.output, 'logo2', 'primary')
        images = self.console.images(self.output)
        self.assertEqual(images['logo']['path'], 'logo.webp')
        self.assertEqual(images['logo2']['path'], 'logo2.svg')
        self.assertEqual(images['logo2']['sources'], svg['sources'])
        self.assertEqual((self.output/'logo2.svg').read_bytes(), svg['data'])
        self.console.undo(self.output, 'logo')
        metadata = json.loads((self.output/'console_artwork.json').read_bytes())
        self.assertEqual(metadata['images']['logo'], original)
        self.assertEqual(metadata['images']['logo2'], variant)
        self.assertFalse((self.output/'logo2.svg').exists())
        self.assertFalse((self.output/'logo.webp').exists())
        change_console(self.console, self.output, 'logo', 'delete')
        self.assertFalse((self.output/'logo.svg').exists())
        self.console.undo(self.output)
        self.assertEqual((self.output/'logo.svg').read_bytes(), svg['data'])

    def test_untracked_console_delete_and_promote_then_undo(self):
        raw = self.encoded[0]['data']
        (self.output/'render2.webp').write_bytes(raw)
        change_console(self.console, self.output, 'render2', 'primary')
        self.assertEqual((self.output/'render.webp').read_bytes(), raw)
        self.assertFalse((self.output/'render2.webp').exists())
        self.console.undo(self.output)
        self.assertEqual((self.output/'render2.webp').read_bytes(), raw)
        change_console(self.console, self.output, 'render2', 'delete')
        self.console.undo(self.output)
        self.assertEqual((self.output/'render2.webp').read_bytes(), raw)
        self.assertEqual(json.loads((self.output/'console_artwork.json').read_bytes())['images'], {})

    def test_console_undo_refuses_external_changes(self):
        self.console.save(self.output, 'render', self.encoded[0])
        self.console.save(self.output, 'render', self.encoded[1], 'render2')
        change_console(self.console, self.output, 'render2', 'primary')
        (self.output/'render.webp').write_bytes(b'external')
        with self.assertRaises(ValueError):
            self.console.undo(self.output)
        self.assertEqual((self.output/'render.webp').read_bytes(), b'external')

    def test_failed_console_swap_rolls_back_and_delete_refuses_occupied_undo_path(self):
        self.console.save(self.output, 'render', self.encoded[0])
        self.console.save(self.output, 'render', self.encoded[1], 'render2')
        before = (self.output/'console_artwork.json').read_bytes()
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path.name == 'render2.webp' and not failed:
                failed = True
                raise OSError('disk failure')
            return atomic_bytes(path, data)
        with patch('console_artwork.atomic_bytes', side_effect=fail_once), self.assertRaises(OSError):
            change_console(self.console, self.output, 'render2', 'primary')
        self.assertEqual((self.output/'console_artwork.json').read_bytes(), before)
        self.assertEqual((self.output/'render.webp').read_bytes(), self.encoded[0]['data'])
        self.assertEqual((self.output/'render2.webp').read_bytes(), self.encoded[1]['data'])
        change_console(self.console, self.output, 'render2', 'delete')
        (self.output/'render2.webp').write_bytes(b'new external file')
        with self.assertRaises(ValueError):
            self.console.undo(self.output)
        self.assertEqual((self.output/'render2.webp').read_bytes(), b'new external file')


if __name__ == '__main__':
    unittest.main()
