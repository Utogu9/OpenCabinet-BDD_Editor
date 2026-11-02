"""Retry temporary Windows locks while preserving atomic-write guarantees."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import editor_store


def locked(code):
    error = PermissionError('Windows file is temporarily locked')
    error.winerror = code
    return error


class AtomicWriteTests(unittest.TestCase):
    def test_transient_windows_lock_retries_without_removing_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'logo.svg'
            path.write_bytes(b'original')
            real_replace = editor_store.os.replace
            attempts = []
            def replace(source, destination):
                self.assertEqual(path.read_bytes(), b'original')
                self.assertEqual(Path(source).read_bytes(), b'replacement')
                attempts.append(source)
                if len(attempts) < 3:
                    raise locked(32 if len(attempts) == 1 else 5)
                real_replace(source, destination)
            with patch.object(editor_store.os, 'replace', side_effect=replace), \
                 patch.object(editor_store.time, 'sleep') as sleep:
                editor_store.atomic_bytes(path, b'replacement')
            self.assertEqual(path.read_bytes(), b'replacement')
            self.assertEqual(len(set(attempts)), 1)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_persistent_windows_lock_is_bounded_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'logo.svg'
            path.write_bytes(b'original')
            with patch.object(editor_store.os, 'replace', side_effect=locked(5)) as replace, \
                 patch.object(editor_store.time, 'sleep') as sleep, self.assertRaises(PermissionError):
                editor_store.atomic_bytes(path, b'replacement')
            self.assertEqual(replace.call_count, 10)
            self.assertEqual(sleep.call_count, 9)
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_unrelated_errors_are_not_retried(self):
        for error in (PermissionError('ordinary permission error'), OSError('Disk is full')):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/'logo.svg'
                path.write_bytes(b'original')
                with patch.object(editor_store.os, 'replace', side_effect=error) as replace, \
                     patch.object(editor_store.time, 'sleep') as sleep, self.assertRaises(OSError):
                    editor_store.atomic_bytes(path, b'replacement')
                replace.assert_called_once()
                sleep.assert_not_called()
                self.assertEqual(path.read_bytes(), b'original')
                self.assertEqual(list(path.parent.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
