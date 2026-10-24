"""Run the executable alone in a temporary directory without source modules."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='OpenCabinet-exe-') as directory:
        folder = Path(directory)/'Standalone executable'
        folder.mkdir()
        executable = folder/'OpenCabinet-BDD_Editor.exe'
        shutil.copy2(ROOT/'dist'/executable.name, executable)
        report = folder/'self-test.json'
        environment = {k:v for k,v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME'}}
        environment['LOCALAPPDATA'] = str(folder/'settings')
        subprocess.run([str(executable), '--self-test', '--self-test-report', str(report)],
                       cwd=folder, env=environment, check=True, timeout=90)
        result = json.loads(report.read_text(encoding='utf-8'))
        if result.get('status') != 'passed' or result.get('frozen') is not True:
            raise RuntimeError('The executable did not pass its bundled UI self-test')
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
