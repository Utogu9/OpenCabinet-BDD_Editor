"""Optional live download check; stores no production library changes."""
import json
from pathlib import Path
import tempfile

from dat_catalog import DatCache
from editor_common import write_json


if __name__ == '__main__':
    result = []
    with tempfile.TemporaryDirectory(prefix='OpenCabinet-DAT-') as directory:
        cache = DatCache(Path(directory))
        for system, provider in [('Sony - PlayStation','redump'),('Nintendo - Game Boy Advance','no-intro')]:
            try:
                catalog = cache.download(system,provider)
                row = {'system':system,'provider':provider,'status':'downloaded','entries':len(catalog.entries),
                       'valid_ids':sum(any(r['status']=='ready' for r in catalog.destinations(e)) for e in catalog.entries),
                       'sha256':catalog.provenance['sha256'],'url':catalog.provenance['url']}
            except Exception as exc:
                row = {'system':system,'provider':provider,'status':'manual_import_required','reason':str(exc)}
            result.append(row)
            print(json.dumps(row,ensure_ascii=True),flush=True)
    write_json(Path(__file__).resolve().parents[1]/'reports/dat-download-check.json',result)
    if result[0]['status'] != 'downloaded':
        raise SystemExit('Redump download failed; see the report')
