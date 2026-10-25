"""Create the editor's private environment and launch it with that interpreter."""
from i18n import tr
from i18n import initialize_language
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    initialize_language()
    if sys.version_info < (3, 10):
        print(tr('Install Python 3.10 or later with Tkinter, then run Run-Editor.cmd again.'))
        return 1
    environment = ROOT/'.venv'
    python = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.exists():
        print(tr('Preparing the editor environment...'), flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    check = subprocess.run([str(python), '-c',
        "import tkinter, PIL, pypdf; from PIL import features; "
        "assert (10, 0) <= tuple(int(n) for n in PIL.__version__.split('.')[:2]) < (13, 0); "
        "assert pypdf.__version__ == '6.21.2'; assert features.check('webp')"],
        capture_output=True)
    if check.returncode:
        print(tr('Installing editor dependencies (Internet access required)...'), flush=True)
        result = subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT/'requirements-editor.txt')])
        if result.returncode:
            return result.returncode
        check = subprocess.run([str(python), '-c', 'import tkinter; from PIL import features; assert features.check("webp")'])
        if check.returncode:
            print(tr('This Python installation needs Tkinter and WebP support to run the editor.'))
            return 1
    if sys.argv[1:] == ['--install-only']:
        print(tr('Editor installed. Run Run-Editor.cmd to open it.'), flush=True)
        return 0
    return subprocess.call([str(python), '-B', str(ROOT/'scripts/artwork_editor.py'), *sys.argv[1:]])


if __name__ == '__main__':
    raise SystemExit(main())
