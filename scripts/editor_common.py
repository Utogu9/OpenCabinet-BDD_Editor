"""Shared image encoding and file helpers for the standalone editor."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
COMPRESSION_POLICY = 'smallest-lossless-or-lossy90-v2'


def settings_path():
    if getattr(sys, 'frozen', False):
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')
        return base/'OpenCabinet-BDD_Editor/editor-setting.json'
    return ROOT/'editor-setting.json'

def compare_encodings(image, icc_profile=None):
    """Encode both candidates from the same pixels; prefer lossless on ties."""
    candidates = {}
    for lossless, label in ((True, 'lossless'), (False, 'lossy90')):
        buffer = BytesIO()
        options = {'format': 'WEBP', 'lossless': lossless, 'exact': True,
                   'quality': 100 if lossless else 90, 'method': 6 if lossless else 4}
        if icc_profile:
            options['icc_profile'] = icc_profile
        image.save(buffer, **options)
        candidates[label] = buffer.getvalue()
    lossless = len(candidates['lossless']) <= len(candidates['lossy90'])
    return candidates['lossless' if lossless else 'lossy90'], {
        'policy': COMPRESSION_POLICY, 'lossless': lossless, 'reason': 'smallest_webp',
        'quality': 100 if lossless else 90,
        'candidate_bytes': {key: len(value) for key, value in candidates.items()}}

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as handle:
        temp = Path(handle.name)
        handle.write((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    os.replace(temp, path)

def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))
