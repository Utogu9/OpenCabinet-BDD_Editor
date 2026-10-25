"""Official DAT cache and explicit, user-selected game lookup."""
from i18n import tr
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from catalog_rules import (build_serial_routes, canonical_serial, effective_version,
                           filename_identity, LIBRETRO_INVALID, metadata_identity, name_key, read_dat, tagged_title)
from editor_common import digest, settings_path, write_json
from editor_store import atomic_bytes
from nointro_serials import db_serials, enrich

PROFILES = json.loads(Path(__file__).with_name('catalog_profiles.json').read_text(encoding='utf-8'))
DAILY = 'https://datomatic.no-intro.org/index.php?page=download&op=daily&s=64'
MAX_BYTES = 128 * 1024**2


def now():
    return datetime.now(timezone.utc).isoformat()


def systems():
    return sorted(set(PROFILES['REDUMP']) | set(PROFILES['NOINTRO']))


def providers(system):
    result = []
    if system in PROFILES['REDUMP']:
        result.append('redump')
    if system in PROFILES['NOINTRO'] or system == 'Nintendo - Wii':
        result.append('no-intro')
    return result


def console_name(name):
    return PROFILES['ALIASES'].get(name, name)


def source_url(system, provider):
    if provider == 'redump':
        return 'https://redump.info/datfile/'+PROFILES['REDUMP'][system]+'/serial,version'
    return DAILY


def _members(data, filename):
    if len(data) > MAX_BYTES:
        raise ValueError(tr('The file exceeds 128 MiB'))
    if zipfile.is_zipfile(BytesIO(data)):
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith(('.xml', '.dat'))]
            if len(members) > 2000 or sum(m.file_size for m in members) > 1024**3:
                raise ValueError(tr('The ZIP exceeds the supported catalogue limits'))
            for member in members:
                if member.file_size > MAX_BYTES:
                    continue
                yield member.filename, archive.read(member)
    else:
        yield filename, data


def _header(data):
    if b'<!ENTITY' in data.upper():
        raise ValueError(tr('XML entities are not allowed in DAT files'))
    # Stop after the header: bulk packs need not be parsed into memory at once.
    for _, element in ET.iterparse(BytesIO(data), events=('end',)):
        if element.tag == 'header':
            return element.findtext('name')
    return None


class DatCatalog:
    def __init__(self, system, provider, entries, provenance):
        self.system, self.provider = system, provider
        self.entries, self.provenance = entries, provenance
        self.routes = build_serial_routes(entries)
        self.by_id = {e['redump_id']: e for e in entries}

    def destinations(self, entry):
        if self.by_id.get(entry['redump_id']) != entry:
            raise ValueError(tr('The entry does not belong to the loaded DAT'))
        return [self.routes[s] for s in entry['serials']]

    def search(self, query, limit=200):
        query = query.strip()
        if not query:
            return [], 0
        serial_query = canonical_serial(query)
        query, _ = filename_identity(query, set(self.routes))
        if self.system == 'Nintendo - Nintendo Entertainment System':
            from nes_names import convert_name
            converted = convert_name(query)
            if converted:
                query = converted['name']
        if self.system == 'DOS':
            query = re.sub(r' \((?:19|20)\d{2}\)$', '', query)
        identity, version, _ = metadata_identity(query)
        # A synthetic region here normalizes articles in a title-only search;
        # it never selects or assigns a region to the result.
        title_only = query.split('(', 1)[0].strip()
        title_key = metadata_identity(title_only+' (USA)')[0][0]
        found = []
        for entry in self.entries:
            candidate, candidate_version, _ = metadata_identity(entry['name'])
            escaped, _, _ = metadata_identity(LIBRETRO_INVALID.sub('_',entry['name']))
            serial_match = serial_query in entry['serials']
            exact = name_key(query) == name_key(entry['name'])
            if identity and candidate:
                if not identity[2] <= candidate[2]:
                    continue
                if identity[1] != candidate[1]:
                    continue
            same_title = any(parts and parts[0] == title_key for parts in (candidate,escaped))
            partial = any(parts and title_key in parts[0] for parts in (candidate,escaped))
            if not (serial_match or exact or same_title or partial):
                continue
            rank = 0 if serial_match or exact else 1 if same_title else 3
            if version and effective_version(entry) != version:
                rank += 1
            found.append((rank, entry['name'].casefold(), entry['redump_id'], entry))
        found.sort(key=lambda item: item[:3])
        return [item[3] for item in found[:limit]], len(found)


class DatCache:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else settings_path().parent/'dat-cache'

    def _index(self, system, provider):
        key = digest((system+'\n'+provider).encode())
        return self.directory/(key+'.json')

    def load(self, system, provider):
        path = self._index(system, provider)
        if not path.exists():
            return None
        metadata = json.loads(path.read_text(encoding='utf-8'))
        if metadata['system'] != system or metadata['provider'] != provider:
            raise ValueError(tr('The cache belongs to another system or provider'))
        if not re.fullmatch('[0-9a-f]{64}', metadata['sha256']):
            raise ValueError(tr('Invalid cache hash'))
        dat = self.directory/(metadata['sha256']+'.dat')
        if digest(dat.read_bytes()) != metadata['sha256']:
            raise ValueError(tr('The saved DAT hash does not match'))
        entries, _ = read_dat(dat, provider)
        if system == 'Nintendo - Wii' and provider == 'no-intro':
            entries = [{**e, 'redump_id':'no-intro:'+e['redump_id']} for e in entries]
        return DatCatalog(system, provider, entries, metadata)

    def import_file(self, system, provider, path):
        path = Path(path)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError(tr('The file exceeds 128 MiB'))
        return self.import_bytes(system, provider, path.read_bytes(), path.name)

    def import_bytes(self, system, provider, data, filename='download.dat', url=None):
        if provider not in providers(system):
            raise ValueError(tr('This provider does not match the console'))
        standard, database = [], []
        preferred = PROFILES['NOINTRO_HEADERS'].get(system)
        for member, raw in _members(data, filename):
            if b'<!ENTITY' in raw.upper():
                raise ValueError(tr('XML entities are not allowed'))
            try:
                name = _header(raw)
            except ET.ParseError:
                continue
            if not name and provider == 'no-intro' and '(DB Export)' in member:
                db_name = re.sub(r' \(DB Export\).*$', '', Path(member).name)
                if console_name(db_name) == system:
                    database.append((member, raw))
                continue
            if console_name(name) != system:
                continue
            if provider == 'no-intro' and system == 'Nintendo - Wii' and name != 'Nintendo - Wii (Digital) (CDN)':
                continue
            tree = ET.fromstring(raw)
            if tree.tag != 'datafile':
                continue
            count = len(tree.findall('game')) + len(tree.findall('machine'))
            standard.append((name == preferred, count, member, raw, tree))
        baseline = self.load(system, provider) if database and not standard else None
        if not standard and baseline:
            raw = (self.directory/(baseline.provenance['standard_sha256']+'.original.xml')).read_bytes()
            if digest(raw) != baseline.provenance['standard_sha256']:
                raise ValueError(tr('The cached original Standard DAT is corrupted'))
            standard = [(True, len(baseline.entries), baseline.provenance['member'], raw, ET.fromstring(raw))]
        if not standard:
            raise ValueError(tr('No Standard DAT was found for this console. For DB Export, import the Standard DAT first and then the original DB ZIP/XML.'))
        if provider == 'redump' and len(standard) != 1:
            raise ValueError(tr('Expected exactly one Redump DAT for this console'))
        _, _, member, original, tree = max(standard, key=lambda item: item[:2])
        standard_sha = digest(original)
        self.directory.mkdir(parents=True, exist_ok=True)
        archive_sha = digest(data)
        archive_path = self.directory/(archive_sha+('.zip' if zipfile.is_zipfile(BytesIO(data)) else '.xml'))
        atomic_bytes(archive_path, data)
        # Preserve the original XML, even when DB enrichment creates a derivative.
        atomic_bytes(self.directory/(digest(original)+'.original.xml'), original)
        db_sources = []
        if database:
            evidence = {}
            for db_member, raw in database:
                for name, records in db_serials(raw).items():
                    evidence.setdefault(name, []).extend([{**r, 'member':db_member, 'member_sha256':digest(raw)} for r in records])
                db_sources.append({'member':db_member, 'sha256':digest(raw)})
            tree, _ = enrich(tree, evidence)
            original = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
        sha = digest(original)
        path = self.directory/(sha+'.dat')
        atomic_bytes(path, original)
        entries, parsed = read_dat(path, provider)
        metadata = {**parsed, 'system':system, 'provider':provider, 'dat_system':tree.findtext('header/name'),
                    'sha256':sha, 'file':path.name, 'member':member, 'imported_at_utc':now(),
                    'acquisition':'official_download' if url else 'user_import',
                    'url':url or source_url(system, provider), 'archive_sha256':archive_sha,
                    'standard_sha256':standard_sha,
                    'db_sources':db_sources or (baseline.provenance.get('db_sources', []) if baseline else [])}
        # Keep the index unchanged if validation fails.
        write_json(self._index(system, provider), metadata)
        return self.load(system, provider)

    @staticmethod
    def fetch(url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'redump.info', 'redump.org', 'datomatic.no-intro.org'}:
            raise ValueError(tr('Catalogues can only be downloaded from official providers'))
        request = urllib.request.Request(url, headers={'User-Agent':'OpenCabinet-BDD_Editor/2.0'})
        with urllib.request.urlopen(request, timeout=40) as response:
            target = urllib.parse.urlparse(response.url)
            if target.scheme != 'https' or target.hostname not in {'redump.info','redump.org','datomatic.no-intro.org'}:
                raise ValueError(tr('Redirect outside the official provider'))
            data = response.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES:
            raise ValueError(tr('The download exceeds 128 MiB'))
        return data

    def download(self, system, provider):
        url = source_url(system, provider)
        data = self.fetch(url)
        try:
            return self.import_bytes(system, provider, data, url=url)
        except (ValueError, ET.ParseError) as first:
            if provider == 'redump':
                raise ValueError(tr('Redump did not return a valid DAT; you can import the file downloaded from its website.')) from first
        # Follow only direct official download links advertised by the page.
        # Interactive forms/captchas are left to the browser, never bypassed.
        html = data.decode('utf-8', errors='replace')
        links = re.findall(r'href=[\"\']([^\"\']+)[\"\']', html, re.I)
        candidates = [urllib.parse.urljoin(url, unescape(link)) for link in links
                      if '.zip' in link.lower() or 'op=dat' in unescape(link)]
        if system == 'Nintendo - Game Boy Advance':
            candidates.append('https://datomatic.no-intro.org/index.php?op=dat&page=download&s=23')
        for candidate in dict.fromkeys(candidates[:8]):
            try:
                return self.import_bytes(system, provider, self.fetch(candidate), url=candidate)
            except (ValueError, ET.ParseError, OSError):
                continue
        raise ValueError(tr('No-Intro did not provide a valid direct download. Open its website, download the official Standard DAT (and DB Export if serials are missing), then use Import DAT/ZIP. The previous cache is preserved.'))
