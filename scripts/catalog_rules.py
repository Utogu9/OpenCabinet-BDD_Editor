"""DAT parsing, names and serial routing aligned with Run-Library.

These rules are covered by fixtures and a read-only parity audit against the
source DATs and generated catalogues. DAT entry IDs are never folder IDs.
"""
from __future__ import annotations
from collections import defaultdict
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from editor_common import digest
from i18n import tr

LANGUAGE_CODES = frozenset(('En Fr De Es It Nl Sv No Da Fi Pt Ja Zh Ko Ar Cs Hu Pl Ru El He Tr Sk Sl Hr Ro Bg Uk La Ca Eu Cy Ga Is Id Ms Th Vi Hi').lower().split())

ARTICLES = r"The|A|An|Le|La|Les|L'|El|Los|Las|Il|Lo|Gli|I|Der|Die|Das|Ein|Eine|Un|Une|O|Os|As|Um|Uma"

LIBRETRO_INVALID = re.compile(r'[&*/:`<>?\\|\"]')

WINDOWS_SUBSTITUTIONS = str.maketrans({
    '/': '-', '\\': '-', '<': '\uff1c', '>': '\uff1e', ':': '\uff1a',
    '"': '\uff02', '|': '\uff5c', '?': '\uff1f', '*': '\uff0a',
})

WINDOWS_RESERVED = re.compile(r'(CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])\Z', re.IGNORECASE)

APOSTROPHES = str.maketrans('', '', "'\u2018\u2019\u02bc")

REGION_NAMES = frozenset(name.casefold() for name in (
    'Japan', 'Asia', 'USA', 'Europe', 'Australia', 'Canada', 'Germany', 'France',
    'Italy', 'Spain', 'UK', 'Russia', 'Netherlands', 'Sweden', 'Portugal', 'Denmark',
    'Korea', 'Norway', 'Finland', 'Taiwan', 'Scandinavia', 'Greece', 'Belgium',
    'Israel', 'Ireland', 'Singapore', 'World', 'China', 'Austria', 'Poland'))

def release_parts(value: str) -> tuple[str, str, frozenset] | None:
    for tag in re.finditer(r'\(([^()]*)\)', value):
        regions = frozenset(part.strip().casefold() for part in tag.group(1).split(','))
        if regions and regions <= REGION_NAMES:
            title = re.sub(r'[\s\-\u2010-\u2014]+', '', name_key(value[:tag.start()]))
            # Keep release tags distinct: Disc 1 != Disc 2, Rev 1 != Rev 2, etc.
            return title, name_key(value[tag.end():]).strip(), regions
    return None

def name_key(value: str) -> str:
    return value.translate(APOSTROPHES).casefold()

def canonical_serial(value: str) -> str:
    # Only standardise Sony's four-letter/five-digit separator; keep suffixes.
    return re.sub(r'^([A-Z]{4})[ -]?(\d{5})', r'\1-\2', value.strip().upper())

def serial_folder(value: str) -> str | None:
    folder = ''.join('-' if ord(char) < 32 else char for char in value.translate(WINDOWS_SUBSTITUTIONS))
    tail_start = len(folder.rstrip(' .'))
    folder = folder[:tail_start] + folder[tail_start:].replace('.', '\uff0e').replace(' ', '_')
    if WINDOWS_RESERVED.fullmatch(folder.split('.')[0]):
        folder = '_' + folder
    return folder or None

def build_serial_routes(entries: list[dict]) -> dict:
    from serial_policy import exclusion_reason
    exclusions = {serial: reason for entry in entries for serial, reason in entry.get('excluded_serials', {}).items()}
    proposals = {serial: serial_folder(serial) for entry in entries for serial in entry['serials']}
    groups = defaultdict(set)
    for serial, folder in proposals.items():
        if folder:
            groups[folder.casefold()].add(serial)
    routes = {}
    for serial, folder in sorted(proposals.items()):
        others = sorted(groups[folder.casefold()] - {serial}) if folder else []
        # A literal existing serial keeps its namespace. A transformed serial
        # must never be merged into a different identifier, even without images.
        status = 'invalid' if not folder else ('collision' if others and folder != serial else 'ready')
        reason = exclusions.get(serial) or exclusion_reason(serial)
        if reason:
            status = 'excluded'
        routes[serial] = {'serial': serial, 'folder': folder, 'status': status,
                          'collides_with': others if status == 'collision' else [],
                          **({'exclusion_reason': reason} if reason else {})}
    return routes

def read_dat(path: Path, provider: str = 'redump') -> tuple[list[dict], dict]:
    data = path.read_bytes()
    tree = ET.fromstring(data)
    if provider not in {'redump', 'no-intro'}:
        raise ValueError(tr('Only No-Intro and Redump are supported'))
    if tree.tag != 'datafile' or not tree.findtext('header/name'):
        raise ValueError(tr('Expected a Logiqx XML DAT with a system name'))
    entries = []
    for game in [*tree.findall('game'), *tree.findall('machine')]:
        # Standard No-Intro DATs may put serial on ROM elements. Never use a
        # ROM checksum, DAT database ID or release number as a product serial.
        values = [node.text or '' for node in game.findall('serial')]
        values += [rom.attrib['serial'] for rom in game.findall('rom') if rom.get('serial')]
        raw = ', '.join(dict.fromkeys(value.strip() for value in values if value.strip()))
        serials = list(dict.fromkeys(canonical_serial(s) for s in raw.split(',') if s.strip()))
        from serial_policy import exclusion_reason
        excluded_serials = {s: reason for s in serials
                            if (reason := exclusion_reason(s, tree.findtext('header/name')))}
        title_id = None
        if provider == 'no-intro' and tree.findtext('header/name') == 'Nintendo - Wii (Digital) (CDN)':
            title_id = (game.findtext('game_id') or '').strip()
            if re.fullmatch(r'[0-9a-fA-F]{16}', title_id):
                serials = [title_id.upper()]
                raw = title_id
            else:
                serials = []
        identifier = game.get('id')
        if not identifier:
            identifier = game.find('archive').get('number') if game.find('archive') is not None else None
        identifier = identifier or 'name-sha256:' + digest(game.attrib['name'].encode('utf-8'))
        entries.append({
            # redump_id is the legacy schema-v2 field; provider/entry_id make
            # the identity explicit for other DAT producers without breaking PS1.
            'redump_id': identifier, 'entry_id': identifier, 'provider': provider,
            'name': game.attrib['name'],
            'serial_raw': raw, 'serials': serials,
            **({'excluded_serials': excluded_serials} if excluded_serials else {}),
            'category': game.findtext('category'), 'version': game.findtext('version'),
            **({'identifier_type': 'platform_title_id', 'title_id': title_id,
                'source_provenance': {'provider': 'no-intro', 'field': 'game_id', 'value': title_id}}
               if title_id and serials else {}),
            **({'source_provenance': json.loads(game.findtext('source_provenance'))}
               if game.findtext('source_provenance') else {}),
        })
    if not entries:
        raise ValueError(tr('Empty DAT'))
    if len({e['redump_id'] for e in entries}) != len(entries):
        raise ValueError(tr('Duplicate DAT entry IDs'))
    return entries, {'file': path.name, 'sha256': digest(data),
                     **({'source_provenance': json.loads(tree.findtext('header/source_provenance'))}
                        if tree.findtext('header/source_provenance') else {}),
                     'version': tree.findtext('header/version'),
                     **({'url': 'https://redump.info/datfile/psx/serial,version'}
                        if tree.findtext('header/name') == 'Sony - PlayStation' and provider == 'redump'
                        else {'system': tree.findtext('header/name'), 'provider': provider})}

def version_key(value: str | None) -> str | None:
    if value and re.fullmatch(r'v?\d+(?:\.\d+)*(?:[a-z])?', value.strip(), re.I):
        return value.strip().lower().removeprefix('v')
    return None

def metadata_identity(value: str) -> tuple[tuple | None, str | None, dict]:
    """Ignore languages and article position; keep all other release labels."""
    versions, languages = [], []
    def clean_tag(tag):
        prefix = value[:tag.start()]
        if prefix.count('(') != prefix.count(')'):
            return tag.group(0)
        text = tag.group(1).strip()
        tokens = {part.strip().casefold() for part in text.split(',')}
        if tokens and tokens <= LANGUAGE_CODES and not tokens <= REGION_NAMES:
            languages.append(text)
            return ''
        if re.fullmatch(r'v\d+(?:\.\d+)*(?:[a-z])?', text, re.I):
            versions.append(version_key(text))
            return ''
        return tag.group(0)
    cleaned = re.sub(r'\(([^()]*)\)', clean_tag, value)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # The title ends at its region tag, so parentheses within a title survive.
    region = next((tag for tag in re.finditer(r'\(([^()]*)\)', cleaned)
                   if {part.strip().casefold() for part in tag.group(1).split(',')} <= REGION_NAMES), None)
    article_changed = False
    if region:
        title = cleaned[:region.start()].strip()
        article = re.search(r',\s*(' + ARTICLES + r')$', title, re.I)
        if article:
            title = article.group(1) + ' ' + title[:article.start()].strip()
            cleaned = title + ' ' + cleaned[region.start():]
            article_changed = True
    parts = release_parts(cleaned)
    details = {'languages_ignored': languages, 'article_reordered': article_changed}
    return parts, versions[0] if len(set(versions)) == 1 else None, details

def effective_version(entry):
    return metadata_identity(entry['name'])[1] or version_key(entry.get('version'))

def tagged_title(value: str) -> tuple[str, set, set]:
    title = value.split('(', 1)[0].strip()
    regions, tags = set(), set()
    for tag in re.findall(r'\(([^()]*)\)', value):
        parts = {part.strip().casefold() for part in tag.split(',')}
        if parts and parts <= REGION_NAMES:
            regions.update(parts)
        else:
            tags.add(name_key(tag).strip())
    return re.sub(r'[\s\-\u2010-\u2014]+', '', name_key(title)), regions, tags


def filename_identity(value: str, known_serials: set) -> tuple[str, list[str]]:
    serials = []
    def strip_serial(tag):
        prefix = value[:tag.start()]
        if prefix.count('(') != prefix.count(')'):
            return tag.group(0)  # A code inside a bundle/accessory tag is part of its name.
        text = tag.group(1).strip()
        serial = canonical_serial(text)
        if (not re.match(r'(?:Rev|Disc|Disk|Track|Version|Ver)\s', text, re.I) and
                (serial in known_serials or re.fullmatch(r'[A-Za-z]{2,6}[- ]\d[A-Za-z0-9-]{2,15}', text))):
            serials.append(serial)
            return ''
        return tag.group(0)
    clean = re.sub(r'\(([^()]*)\)', strip_serial, value)
    # Arcade names sometimes put region and revision in the same parentheses.
    def split_region_revision(tag):
        parts = [part.strip() for part in tag.group(1).split(',')]
        regions = [part for part in parts if part.casefold() in REGION_NAMES]
        revisions = [part for part in parts if re.fullmatch(r'Rev\s+[^,]+', part, re.I)]
        if regions and revisions and len(regions) + len(revisions) == len(parts):
            return '(' + ', '.join(regions) + ') ' + ' '.join('(' + part + ')' for part in revisions)
        return tag.group(0)
    if serials:
        clean = re.sub(r'\(([^()]*)\)', split_region_revision, clean)
    return re.sub(r'\s+', ' ', clean).strip(), list(dict.fromkeys(serials))


def metadata_candidates(value, index):
    parts, source_version, details = metadata_identity(value)
    if parts is None:
        return [], source_version, details
    title, tags, regions = parts
    candidates = [entry for entry, dat_regions in index.get((title, tags), {}).values() if regions <= dat_regions]
    return candidates, source_version, details
