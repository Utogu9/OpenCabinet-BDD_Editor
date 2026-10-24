"""Build the portable Windows executable with the installed build dependencies."""
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = 'OpenCabinet-BDD_Editor'


def main():
    if sys.platform != 'win32':
        raise RuntimeError('Build the Windows executable on Windows.')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--windowed', '--noupx', '--name', NAME, '--distpath', str(ROOT/'dist'),
                    '--workpath', str(ROOT/'build'), '--specpath', str(ROOT/'build'),
                    '--paths', str(ROOT/'scripts'), '--collect-all', 'PIL', '--collect-all', 'pypdf',
                    '--hidden-import', 'check_artwork_editor', str(ROOT/'scripts/editor_entry.py')],
                   cwd=ROOT, check=True)
    executable = ROOT/'dist'/(NAME+'.exe')
    checksum = hashlib.sha256(executable.read_bytes()).hexdigest()
    executable.with_suffix('.exe.sha256').write_text(checksum+'  '+executable.name+'\n', encoding='ascii')
    print(str(executable), flush=True)


if __name__ == '__main__':
    main()
