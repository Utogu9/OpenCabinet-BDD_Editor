"""Catalog format selection; SQLite and JSON share the same in-memory schema."""
import json
from i18n import tr
from pathlib import Path

from catalog_sqlite import SQLITE_HEADER, loads as load_sqlite, dumps as dump_sqlite

CATALOG_NAMES = ('catalog.sqlite', 'catalog.json')


def validate_snapshot(path):
    path = Path(path)
    if path.suffix == '.sqlite':
        for suffix in ('-wal', '-journal'):
            sidecar = path.with_name(path.name+suffix)
            if sidecar.exists() and sidecar.stat().st_size:
                raise ValueError(tr('SQLite catalog has an active journal; close other database tools before editing it.'))
    return path


def catalog_path(output, *, checkpoint=False):
    output = Path(output)
    if checkpoint and (output/'checkpoint.json').exists():
        return output/'checkpoint.json'
    for name in CATALOG_NAMES:
        if (output/name).exists():
            return validate_snapshot(output/name)
    return output/'catalog.json'


def decode_catalog(raw):
    if raw.startswith(SQLITE_HEADER):
        return load_sqlite(raw)
    return json.loads(raw.decode('utf-8-sig'))


def read_catalog(path):
    path = validate_snapshot(path)
    raw = path.read_bytes()
    if path.suffix == '.sqlite' and not raw.startswith(SQLITE_HEADER):
        raise ValueError(tr('Invalid SQLite catalog header'))
    return decode_catalog(raw)


def encode_catalog(catalog, path):
    if Path(path).suffix == '.sqlite':
        return dump_sqlite(catalog)
    return (json.dumps(catalog, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def sample_directories(directory):
    return sorted({path.parent for name in CATALOG_NAMES for path in Path(directory).rglob(name)})
