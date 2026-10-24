import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image
from console_artwork import ConsoleArtwork
from editor_store import encode_import
from editor_location import choose_library, selected_library, LocatedArtworkStore


class EditorLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.settings = self.root/'settings.json'

    def create(self, directory):
        output = directory/'Console'
        output.mkdir(parents=True)
        (output/'catalog.json').write_text(json.dumps({'schema_version':2,'system':'Console',
                                                    'status':'complete','games':{}}))
        return output

    def test_existing_default_does_not_prompt_or_write_settings(self):
        self.create(self.root/'generated')
        ask, error = Mock(), Mock()
        self.assertEqual(choose_library(self.root, self.settings, ask, error), self.root/'generated')
        ask.assert_not_called()
        self.assertFalse(self.settings.exists())

    def test_missing_default_asks_retries_and_remembers_renamed_directory(self):
        folder = self.root/'Other Library'
        self.create(folder)
        ask, error = Mock(side_effect=[str(self.root/'invalid'), str(folder)]), Mock()
        self.assertEqual(choose_library(self.root, self.settings, ask, error), folder)
        self.assertEqual(error.call_count, 1)
        self.assertEqual(json.loads(self.settings.read_text())['library'], str(folder))
        no_prompt = Mock()
        self.assertEqual(choose_library(self.root, self.settings, no_prompt, error), folder)
        no_prompt.assert_not_called()

    def test_project_selection_and_cancel(self):
        project = self.root/'external'
        self.create(project/'generated')
        self.assertEqual(selected_library(project), project/'generated')
        self.assertIsNone(choose_library(self.root, self.settings, Mock(return_value=''), Mock()))
        self.assertFalse(self.settings.exists())

    def test_renamed_library_store_can_save_console_artwork(self):
        library = self.root/'Artwork Library'
        output = self.create(library)
        store = LocatedArtworkStore(library)
        self.assertEqual(store.libraries()[0]['output'], output)
        image = self.root/'import.png'
        Image.new('RGB', (10,10), 'red').save(image)
        ConsoleArtwork(store).save(output, 'logo', encode_import(image))
        self.assertTrue((output/'logo.webp').exists())
        self.assertTrue((library/'_editor').exists())
        self.assertFalse((self.root/'manual').exists())


if __name__ == '__main__':
    unittest.main()
