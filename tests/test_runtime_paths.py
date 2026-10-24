import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import editor_common
from editor_store import ArtworkStore


class RuntimePathTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows short paths')
    def test_windows_short_paths_use_one_canonical_store_location(self):
        import ctypes
        with tempfile.TemporaryDirectory(prefix='OpenCabinet long path ') as directory:
            root = Path(directory).resolve()
            output = root/'generated/Console'
            output.mkdir(parents=True)
            get_short = ctypes.windll.kernel32.GetShortPathNameW
            get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
            get_short.restype = ctypes.c_uint32
            buffer = ctypes.create_unicode_buffer(32768)
            if not get_short(str(output), buffer, len(buffer)):
                self.skipTest('Short paths are unavailable on this filesystem')
            store = ArtworkStore(root)
            canonical = store.output(Path(buffer.value))
            self.assertEqual(canonical, output.resolve())
            self.assertEqual(canonical.relative_to(store.generated), Path('Console'))
            self.assertEqual(store.state_path(canonical), store.state_path(output))

    def test_source_settings_stay_with_source(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(editor_common.settings_path(), editor_common.ROOT/'editor-settings.json')

    def test_frozen_settings_are_persistent_outside_bundle(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA':directory}), \
             patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(editor_common.settings_path(), Path(directory)/'OpenCabinet-BDD_Editor/editor-settings.json')


if __name__ == '__main__':
    unittest.main()
