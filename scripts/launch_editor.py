"""Create the editor's private environment and launch it with that interpreter."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info < (3, 10):
        print('Instalá Python 3.10 o posterior, con Tkinter, y volvé a ejecutar Run-Editor.cmd.')
        return 1
    environment = ROOT/'.venv'
    python = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.exists():
        print('Preparando el entorno del editor...', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    check = subprocess.run([str(python), '-c',
        "import tkinter, PIL, pypdf; from PIL import features; "
        "assert (10, 0) <= tuple(int(n) for n in PIL.__version__.split('.')[:2]) < (13, 0); "
        "assert pypdf.__version__ == '6.21.2'; assert features.check('webp')"],
        capture_output=True)
    if check.returncode:
        print('Instalando las dependencias del editor (requiere Internet)...', flush=True)
        result = subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT/'requirements-editor.txt')])
        if result.returncode:
            return result.returncode
        check = subprocess.run([str(python), '-c', 'import tkinter; from PIL import features; assert features.check("webp")'])
        if check.returncode:
            print('Este Python necesita Tkinter y soporte WebP para ejecutar el editor.')
            return 1
    if sys.argv[1:] == ['--install-only']:
        print('Editor instalado. Ejecutá Run-Editor.cmd para abrirlo.', flush=True)
        return 0
    return subprocess.call([str(python), '-B', str(ROOT/'scripts/artwork_editor.py'), *sys.argv[1:]])


if __name__ == '__main__':
    raise SystemExit(main())
