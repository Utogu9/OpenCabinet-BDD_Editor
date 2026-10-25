"""Read-only developer audit against an existing Run-Library workspace."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import catalog_rules
from editor_common import compare_encodings, COMPRESSION_POLICY, write_json


def run(workspace):
    workspace = Path(workspace).resolve()
    spec = importlib.util.spec_from_file_location('reference_library_rules',workspace/'scripts/restructure_ps1.py')
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    if reference.COMPRESSION_POLICY != COMPRESSION_POLICY:
        raise AssertionError('Compression policy differs')
    from PIL import Image
    for mode, color in [('RGB',(20,70,120)),('RGBA',(20,70,120,80))]:
        image = Image.new(mode,(12,10),color)
        if compare_encodings(image) != reference.compare_encodings(image):
            raise AssertionError('WebP output differs from Run-Library')
    registered = {}
    paths = [*(workspace/'dats').glob('*/*/metadata.json'),workspace/'dats/redump/metadata.json']
    for path in paths:
        if not path.exists():
            continue
        meta = json.loads(path.read_text(encoding='utf-8-sig'))
        provider = meta.get('provider', '').lower()
        if provider not in {'no-intro','redump'}:
            continue
        dat = workspace/meta['dat']['path'] if 'path' in meta['dat'] else path.parent/meta['dat']['filename']
        registered[meta['system']] = (dat,provider)
    rows = []
    for index in sorted((workspace/'generated').glob('*/catalog.json')):
        system = index.parent.name
        if system.startswith('_') or system not in registered:
            continue
        dat, provider = registered[system]
        entries, provenance = catalog_rules.read_dat(dat,provider)
        expected, expected_provenance = reference.read_dat(dat,provider)
        if entries != expected or provenance != expected_provenance:
            raise AssertionError('DAT parsing differs: '+system)
        if system == 'Nintendo - Wii' and 'Nintendo - Wii (Digital)' in registered:
            digital, _ = registered['Nintendo - Wii (Digital)']
            extra, _ = catalog_rules.read_dat(digital,'no-intro')
            entries += [{**e,'redump_id':'no-intro:'+e['redump_id']} for e in extra]
        routes = catalog_rules.build_serial_routes(entries)
        if routes != reference.build_serial_routes(entries):
            raise AssertionError('Routing differs: '+system)
        for entry in entries:
            if catalog_rules.metadata_identity(entry['name']) != reference.metadata_identity(entry['name']):
                raise AssertionError('Name normalization differs: '+entry['name'])
        actual = json.loads(index.read_text(encoding='utf-8'))
        checked = 0
        for folder, game in actual['games'].items():
            for serial in game['serial_identifiers']:
                route = routes.get(serial)
                if route is None or route['status'] != 'ready' or route['folder'] != folder:
                    raise AssertionError(f'Generated folder does not match accepted routing: {system}/{folder}: {serial}')
                checked += 1
        rows.append({'system':system,'dat_entries':len(entries),'generated_games':len(actual['games']),
                     'checked_identifiers':checked})
        print('Verified '+system,flush=True)
    if not rows:
        raise AssertionError('No real catalogues were audited')
    return {'status':'passed','compression_equal':True,'parsing_equal':True,'name_rules_equal':True,
            'serial_routing_equal':True,'systems':rows}


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--report',type=Path,default=Path(__file__).resolve().parents[1]/'reports/rule-audit.json')
    args = parser.parse_args()
    result = run(args.workspace)
    write_json(args.report,result)
    print(json.dumps({'status':'passed','systems':len(result['systems']),
                      'identifiers':sum(r['checked_identifiers'] for r in result['systems'])}),flush=True)
