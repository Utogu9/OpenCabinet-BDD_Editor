"""Official DB primary serial enrichment; identical missing-only policy to Run-Library."""
from collections import defaultdict
from copy import deepcopy
import json
import re
import xml.etree.ElementTree as ET
from catalog_rules import canonical_serial

POLICY = 'official-db-primary-media-fill-v1'

def db_serials(data):
    # DB Export uses sibling header/datafile elements rather than one XML root.
    body = re.sub(br'^\s*<\?xml[^>]*\?>', b'', data)
    tree = ET.fromstring(b'<export>' + body + b'</export>')
    entries = defaultdict(list)
    for game in tree.findall('datafile/game'):
        for source in game.findall('source'):
            details, serials = source.find('details'), source.find('serials')
            if details is None or serials is None:
                continue
            if details.get('rominfo', '').lower() in {'bad', 'hacked'}:
                continue
            if not any(f.get('bad') != '1' for f in source.findall('file')):
                continue
            # Secondary labels may be cart part numbers or production codes.
            # Never use PCB/chip/barcode/stamp/database IDs as product serials.
            field = 'media_serial1' if serials.get('media_serial1') else 'digital_serial1'
            for value in serials.get(field, '').split(','):
                value = value.strip()
                if value and value.lower() not in {'unknown', 'n/a', 'none', '-'}:
                    entries[game.get('name')].append({'serial': value, 'field': field,
                        'source_id': details.get('id'), 'section': details.get('section')})
    return entries

def enrich(tree, serials):
    result = deepcopy(tree)
    added = 0
    for game in result.findall('game') + result.findall('machine'):
        existing = [s.text for s in game.findall('serial') if s.text]
        existing += [r.get('serial') for r in game.findall('rom') if r.get('serial')]
        if any(s.strip() for s in existing):
            continue
        evidence = serials.get(game.get('name'), [])
        codes = list(dict.fromkeys(canonical_serial(e['serial']) for e in evidence))
        if codes:
            ET.SubElement(game, 'serial').text = ', '.join(codes)
            ET.SubElement(game, 'source_provenance').text = json.dumps(
                {'provider': 'no-intro', 'export': 'DB', 'policy': POLICY, 'evidence': evidence}, ensure_ascii=False)
            added += 1
    return result, added
