import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import editor_common


class RuntimePathTests(unittest.TestCase):
    def test_source_settings_stay_with_source(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(editor_common.settings_path(), editor_common.ROOT/'editor-settings.json')

    def test_frozen_settings_are_persistent_outside_bundle(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA':directory}), \
             patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(editor_common.settings_path(), Path(directory)/'OpenCabinet-BDD_Editor/editor-settings.json')


if __name__ == '__main__':
    unittest.main()
