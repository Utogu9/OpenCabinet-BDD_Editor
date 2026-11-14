import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from console_locks import console_writer, OWNER
from editor_store import ArtworkStore


class ConsoleLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = ArtworkStore(self.root)
        self.ps2 = self.root/'generated/Sony - PlayStation 2'
        self.wii = self.root/'generated/Nintendo - Wii'
        self.batch = self.root/'reports/batch.lock'

    def test_different_consoles_overlap_and_global_marker_survives_first_exit(self):
        first, second = console_writer(self.store, self.wii), console_writer(self.store, self.ps2)
        first.__enter__()
        try:
            second.__enter__()
            try:
                info = json.loads(self.batch.read_text())
                self.assertEqual(set(info['consoles']), {self.wii.name, self.ps2.name})
                with self.assertRaises(ValueError):
                    with console_writer(self.store, self.ps2):
                        self.fail('same console acquired twice')
                first.__exit__(None, None, None)
                first = None
                self.assertTrue(self.batch.exists())
                self.assertIn(self.ps2.name, self.store.lock_status())
                with self.assertRaises(ValueError):
                    with self.store.writer():
                        self.fail('editor acquired the library during import')
            finally:
                second.__exit__(None, None, None)
        finally:
            if first is not None:
                first.__exit__(None, None, None)
        self.assertFalse(self.batch.exists())
        self.assertFalse(list((self.root/'reports/console-locks').glob('*.lock')))

    def test_editor_or_legacy_import_blocks_new_console_imports(self):
        with self.store.writer():
            before = self.batch.read_bytes()
            with self.assertRaises(ValueError):
                with console_writer(self.store, self.ps2):
                    self.fail('joined a legacy exclusive lock')
            self.assertEqual(self.batch.read_bytes(), before)

    def test_wii_to_gamecube_transition_while_ps2_keeps_importing(self):
        gamecube = self.root/'generated/Nintendo - GameCube'
        with console_writer(self.store, self.ps2):
            with console_writer(self.store, self.wii):
                self.assertEqual(set(json.loads(self.batch.read_text())['consoles']),
                                 {self.ps2.name, self.wii.name})
            with console_writer(self.store, gamecube):
                self.assertEqual(set(json.loads(self.batch.read_text())['consoles']),
                                 {self.ps2.name, gamecube.name})
                with self.assertRaises(ValueError):
                    with console_writer(self.store, gamecube):
                        self.fail('GameCube must stay locked during its import')
                # Wii was released when its own stage finished.
                with console_writer(self.store, self.wii):
                    pass
            self.assertEqual(json.loads(self.batch.read_text())['consoles'], [self.ps2.name])
        self.assertFalse(self.batch.exists())

    def test_keyboard_interrupt_releases_only_own_console(self):
        with console_writer(self.store, self.wii):
            try:
                with console_writer(self.store, self.ps2):
                    raise KeyboardInterrupt()
            except KeyboardInterrupt:
                pass
            self.assertEqual(json.loads(self.batch.read_text())['consoles'], [self.wii.name])
            with console_writer(self.store, self.ps2):
                pass
        self.assertFalse(self.batch.exists())

    def test_actual_second_process_joins_other_console_and_rejects_same_one(self):
        code = '''import sys
sys.path.insert(0, sys.argv[1])
from editor_store import ArtworkStore
from console_locks import console_writer
from pathlib import Path
store = ArtworkStore(Path(sys.argv[2]))
try:
    with console_writer(store, store.generated/sys.argv[3]):
        pass
except ValueError:
    sys.exit(7)
'''
        scripts = str(Path(__file__).resolve().parents[1]/'scripts')
        with console_writer(self.store, self.wii):
            for name, expected in [(self.ps2.name, 0), (self.wii.name, 7)]:
                result = subprocess.run([sys.executable, '-B', '-c', code, scripts, str(self.root), name], capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(json.loads(self.batch.read_text())['consoles'], [self.wii.name])


if __name__ == '__main__':
    unittest.main()
