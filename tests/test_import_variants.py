"""Imports create separate image/PDF variants; replacements and undo target one label."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from editor_store import ArtworkStore, encode_import
from pdf_tools import optimize_pdf, pdf_api


class GameImportVariantTests(unittest.TestCase):
    def test_images_and_manuals_keep_the_first_file_and_undo_only_the_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root/'generated/Console'
            output.mkdir(parents=True)
            (output/'catalog.json').write_text(json.dumps({
                'schema_version': 2, 'system': 'Console', 'status': 'complete',
                'games': {'ID': {'serial': 'ID', 'entries': [{'name': 'Game (USA)'}], 'images': {}}}}))
            store = ArtworkStore(root)
            for kind in ('cover_front', 'screenshot', 'manual'):
                with self.subTest(kind=kind):
                    candidates = []
                    for number in range(3):
                        if kind == 'manual':
                            source = root/f'manual{number}.pdf'
                            _, PdfWriter = pdf_api()
                            writer = PdfWriter()
                            writer.add_blank_page(width=200+number, height=300)
                            writer.write(source)
                            candidates.append(optimize_pdf(source))
                        else:
                            source = root/f'image{number}.png'
                            Image.new('RGB', (20, 20), ('red', 'green', 'blue')[number]).save(source)
                            candidates.append(encode_import(source))
                    extension = candidates[0].get('extension', 'webp')
                    base = output/'ID'/f'{kind}.{extension}'
                    variant = output/'ID'/f'{kind}2.{extension}'
                    store.save(output, 'ID', kind, kind, candidates[0], create_only=True)
                    with self.assertRaises(ValueError):
                        store.save(output, 'ID', kind, kind, candidates[1], create_only=True)
                    store.save(output, 'ID', kind, kind+'2', candidates[1], create_only=True)
                    store.save(output, 'ID', kind, kind+'2', candidates[2])
                    self.assertEqual(base.read_bytes(), candidates[0]['data'])
                    self.assertEqual(variant.read_bytes(), candidates[2]['data'])
                    store.undo(output, 'ID')
                    self.assertEqual(variant.read_bytes(), candidates[1]['data'])
                    store.undo(output, 'ID')
                    self.assertFalse(variant.exists())
                    self.assertEqual(base.read_bytes(), candidates[0]['data'])
                    self.assertNotIn(kind+'2', store.read_catalog(output)['games']['ID']['images'])


if __name__ == '__main__':
    unittest.main()
