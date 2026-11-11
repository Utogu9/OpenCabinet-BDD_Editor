"""Transactional catalogue additions, preserving the editor's artwork history."""
from i18n import tr
from copy import deepcopy
import json
from pathlib import Path
import re

import PIL
from PIL import features

from editor_common import COMPRESSION_POLICY, digest, is_link, write_json
from editor_store import atomic_bytes, component, inside, json_bytes, stamp
from catalog_rules import canonical_serial, serial_folder, WINDOWS_RESERVED
from serial_policy import exclusion_reason
from catalog_io import decode_catalog, encode_catalog


def manual_destination(system, name, serial, reference=''):
    system, name, raw, reference = (value.strip() for value in (system, name, serial, reference))
    if (not system or system.startswith(('.', '_')) or re.search(r'[<>:"/\\|?*\x00-\x1f]', system)
            or system.endswith(('.', ' ')) or WINDOWS_RESERVED.fullmatch(system.split('.')[0])):
        raise ValueError(tr('Enter a valid console folder name'))
    if not name or any(ord(c) < 32 for c in name):
        raise ValueError(tr('Enter the full game name, including region or edition when known'))
    if (not raw or len(raw) > 200 or ',' in raw or any(ord(c) < 32 for c in raw)
            or not any(c.isalnum() for c in raw) or raw.startswith(('/', '\\'))
            or re.match(r'^[A-Za-z]:[/\\]', raw)
            or any(part in {'.', '..'} for part in re.split(r'[/\\]', raw))):
        raise ValueError(tr('Enter one serial or title ID, not a file path or a list'))
    identifier = canonical_serial(raw)
    if exclusion_reason(identifier, system):
        raise ValueError(tr('Missing-identifier placeholders cannot be used as a serial'))
    folder = component(serial_folder(identifier))
    if any(ord(c) < 32 for c in reference):
        raise ValueError(tr('Enter a source reference on one line'))
    return {'system': system, 'name': name, 'serial': identifier, 'serial_raw': raw,
            'folder': folder, 'reference': reference}


def metadata(game):
    return deepcopy({k:v for k,v in game.items() if k != 'images'}) if game is not None else None


class GameRegistration:
    def __init__(self, store):
        self.store = store

    def paths(self, output):
        output = self.store.output(output)
        key = digest(output.relative_to(self.store.generated).as_posix().encode())
        private = inside(self.store.manual/'game-registration'/key, self.store.root)
        return private/'history.json', private/'pending.json'

    def has_pending(self, output):
        return self.paths(output)[1].exists()

    def _recover(self, output):
        _, pending = self.paths(output)
        if not pending.exists():
            return
        journal = json.loads(pending.read_text(encoding='utf-8'))
        for item in journal['files']:
            path = inside(self.store.root/item['path'], self.store.root)
            current = digest(path.read_bytes()) if path.exists() else None
            allowed = {Path(item[k]).stem if item[k] else None for k in ('before', 'after')}
            if current not in allowed:
                raise ValueError(tr('A file changed outside the editor during an incomplete game registration'))
            for key in ('before', 'after'):
                if item[key]:
                    self.store.read_blob(item[key])
        for relative in journal['removed_directories']:
            inside(self.store.root/relative, self.store.generated).mkdir(parents=True, exist_ok=True)
        for item in journal['files']:
            path = inside(self.store.root/item['path'], self.store.root)
            if item['before'] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, self.store.read_blob(item['before']))
        for relative in reversed(journal['created_directories']):
            directory = inside(self.store.root/relative, self.store.generated)
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        pending.unlink()

    def recover(self, output):
        with self.store.writer():
            self._recover(output)

    def _commit(self, output, payloads, create=(), remove=()):
        _, pending = self.paths(output)
        files = []
        for path, after in payloads.items():
            path = inside(path, self.store.root)
            before = path.read_bytes() if path.exists() else None
            files.append({'path':str(path.relative_to(self.store.root)),
                          'before':self.store.blob(before) if before is not None else None,
                          'after':self.store.blob(after) if after is not None else None})
        journal = {'files':files,
                   'created_directories':[str(p.relative_to(self.store.root)) for p in create],
                   'removed_directories':[str(p.relative_to(self.store.root)) for p in remove]}
        write_json(pending, journal)
        try:
            for directory in create:
                inside(directory, self.store.generated).mkdir(parents=True, exist_ok=True)
            for path, data in payloads.items():
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, data)
            for directory in remove:
                inside(directory, self.store.generated).rmdir()  # Empty folders only.
            pending.unlink()
        except BaseException:
            self._recover(output)
            raise

    def _views(self, output, dat=None, manual_system=None):
        output = self.store.output(output)
        index = self.store.catalog_path(output)
        if (output/'checkpoint.json').exists():
            raise ValueError(tr('This console has a pending conversion; wait for it to finish'))
        if not index.exists():
            if (dat is None and manual_system is None) or output.exists():
                raise ValueError(tr('The folder exists without a valid catalogue; it will not be adopted or overwritten'))
            system = dat.system if dat else manual_system
            if output.name != system:
                raise ValueError(tr('The new folder must use the selected console name'))
            catalog = {'schema_version':2, 'system':system,
                       **({'dat':deepcopy(dat.provenance)} if dat else {}),
                       'source_policy':'release-metadata-v1' if dat else 'manual-registration-v1',
                       'status':'complete', 'games':{},
                       'encoding':{'format':'WEBP', 'quality':90, 'method':4, 'lossless':False, 'exact':True,
                                   'compression_policy':COMPRESSION_POLICY, 'pillow':PIL.__version__,
                                   'webp':features.version('webp')}}
            return catalog, deepcopy(catalog), None
        raw = index.read_bytes()
        catalog = decode_catalog(raw)
        if catalog.get('schema_version') != 2 or catalog.get('status') not in {'complete', 'sample_complete'}:
            raise ValueError(tr('The console must have a complete schema 2 serial-based catalogue'))
        if dat and catalog['system'] != dat.system:
            raise ValueError(tr('The DAT and destination console do not match'))
        if manual_system and catalog['system'] != manual_system:
            raise ValueError(tr('The console name and destination catalogue do not match'))
        state_path = self.store.state_path(output)
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding='utf-8'))
            if state['applied_catalog_sha256'] != digest(raw):
                raise ValueError(tr('The catalogue changed outside the editor'))
            if state.get('catalog_filename', index.name) != index.name:
                raise ValueError(tr('The catalogue changed outside the editor'))
            base = decode_catalog(self.store.read_blob(state['base_catalog']))
        else:
            state, base = None, deepcopy(catalog)
        return catalog, base, state

    def _payloads(self, output, catalog, base, state, history):
        history_path, _ = self.paths(output)
        index = self.store.catalog_path(output)
        payloads = {index:encode_catalog(catalog, index), history_path:json_bytes(history)}
        if state is not None:
            updated = {**state, 'base_catalog':self.store.blob(encode_catalog(base, index)),
                       'catalog_filename':index.name,
                       'applied_catalog_sha256':digest(payloads[index])}
            payloads[self.store.state_path(output)] = json_bytes(updated)
        return payloads

    def add_manual(self, output, system, name, serial, reference=''):
        destination = manual_destination(system, name, serial, reference)
        output = self.store.output(output)
        identifier, folder = destination['serial'], destination['folder']
        with self.store.writer():
            self._recover(output)
            catalog, base, state = self._views(output, manual_system=destination['system'])
            existing = next((key for key in catalog['games'] if key.casefold() == folder.casefold()), None)
            if existing is not None:
                game = catalog['games'][existing]
                known = game.get('serial_identifiers', [existing])
                if not known or any(canonical_serial(value) != identifier for value in known):
                    raise ValueError(tr('Destination {v0} already belongs to another identifier: {v1}', v0=existing, v1=known))
                folder = existing
            directory = inside(output/folder, output)
            if directory.exists() and (is_link(directory) or existing is None):
                raise ValueError(tr('Folder {v0} exists without that catalogue association; it will not be overwritten', v0=folder))
            before = catalog['games'].get(folder)
            if before and before.get('entries'):
                if any(entry.get('name', '').strip().casefold() == destination['name'].casefold()
                       for entry in before['entries']):
                    return [{'folder': folder, 'created': False, 'existing': True}]
                raise ValueError(tr('This identifier is already registered as {v0}. Open that game instead.',
                                    v0=before['entries'][0]['name']))
            history_path, _ = self.paths(output)
            history = json.loads(history_path.read_text('utf-8')) if history_path.exists() else []
            event = {'at': stamp(), 'before': {folder: metadata(before)}, 'after': {}, 'created': []}
            create = [output] if not output.exists() else []
            if not directory.exists():
                create.append(directory)
                event['created'].append(folder)
            provenance = {'provider': 'manual', 'verification': 'user_supplied',
                          'field': 'user_serial', 'value': identifier,
                          **({'reference': destination['reference']} if destination['reference'] else {})}
            entry = {'provider': 'manual', 'name': destination['name'],
                     'serial_raw': destination['serial_raw'], 'serials': [identifier],
                     'source_provenance': provenance}
            for view in (catalog, base):
                game = view['games'].setdefault(folder, {'serial': folder,
                    'serial_identifiers': [identifier], 'entries': [], 'images': {}})
                game['entries'].append(deepcopy(entry))
                game.setdefault('editor_added_entries', []).append({
                    'method': 'manual', 'source': deepcopy(provenance), 'serial': identifier, 'at': event['at']})
            event['after'][folder] = metadata(catalog['games'][folder])
            history.append(event)
            self._commit(output, self._payloads(output, catalog, base, state, history), create=create)
            return [{'folder': folder, 'created': before is None, 'existing': False}]

    def add(self, output, dat, entry_id, serials):
        output = self.store.output(output)
        entry = dat.by_id.get(entry_id)
        if entry is None:
            raise ValueError(tr('The selected entry no longer belongs to the DAT'))
        routes = {r['serial']:r for r in dat.destinations(entry)}
        if not serials or len(set(serials)) != len(serials) or any(s not in routes or routes[s]['status'] != 'ready' for s in serials):
            raise ValueError(tr('Select valid DAT identifiers without placeholders or collisions'))
        with self.store.writer():
            self._recover(output)
            catalog, base, state = self._views(output, dat)
            history_path, _ = self.paths(output)
            history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else []
            event = {'at':stamp(), 'before':{}, 'after':{}, 'created':[]}
            result = []
            create = [output] if not output.exists() else []
            for serial in serials:
                folder = component(routes[serial]['folder'])
                # A newer DAT cannot silently merge a transformed ID with a
                # literal ID already registered by an older catalogue.
                existing = next((key for key in catalog['games'] if key.casefold() == folder.casefold()), None)
                if existing:
                    old_game = catalog['games'][existing]
                    known = old_game.get('serial_identifiers', [existing])
                    if any(value != serial for value in known):
                        raise ValueError(tr('Destination {v0} already belongs to another identifier: {v1}', v0=existing, v1=known))
                    folder = existing
                directory = inside(output/folder, output)
                if directory.exists() and (is_link(directory) or existing is None):
                    raise ValueError(tr('Folder {v0} exists without that catalogue association; it will not be overwritten', v0=folder))
                if not directory.exists():
                    create.append(directory)
                    event['created'].append(folder)
                before = catalog['games'].get(folder)
                event['before'][folder] = metadata(before)
                changed = False
                for view in (catalog, base):
                    game = view['games'].setdefault(folder, {'serial':folder, 'serial_identifiers':[serial],
                                                            'entries':[], 'images':{}})
                    # DAT numeric entry IDs may change between exports. Reuse
                    # the complete provider/name association when it exists.
                    known_entry = next((e for e in game['entries'] if e.get('provider') == dat.provider and e['name'] == entry['name']), None)
                    if known_entry is None:
                        if any(e.get('provider') == dat.provider and e.get('redump_id') == entry_id for e in game['entries']):
                            raise ValueError(tr('The internal DAT ID already identifies another name in this folder; review is required'))
                        game['entries'].append(deepcopy(entry))
                        game.setdefault('editor_added_entries', []).append({'entry_id':entry_id, 'dat':deepcopy(dat.provenance),
                                                                            'serial':serial, 'at':event['at']})
                        changed = True
                if not changed:
                    event['before'].pop(folder)
                    if folder in event['created']:
                        event['created'].remove(folder)
                        create.remove(directory)
                    result.append({'folder':folder, 'created':False, 'existing':True})
                    continue
                event['after'][folder] = metadata(catalog['games'][folder])
                result.append({'folder':folder, 'created':before is None, 'existing':False})
            if not event['after']:
                return result
            history.append(event)
            self._commit(output, self._payloads(output, catalog, base, state, history), create=create)
            return result

    def can_undo(self, output):
        path, _ = self.paths(output)
        return path.exists() and bool(json.loads(path.read_text(encoding='utf-8')))

    def undo(self, output):
        output = self.store.output(output)
        with self.store.writer():
            self._recover(output)
            catalog, base, state = self._views(output)
            path, _ = self.paths(output)
            history = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
            if not history:
                raise ValueError(tr('There are no game registrations to undo for this console'))
            event = history[-1]
            remove = []
            for folder, after in event['after'].items():
                identity = lambda game: {k:v for k,v in (metadata(game) or {}).items()
                                         if k not in {'metadata_id', 'metadata_overrides'}}
                if identity(catalog['games'].get(folder)) != identity(after):
                    raise ValueError(tr('The game association changed after registration; it will not be overwritten'))
                previous = event['before'][folder]
                directory = inside(output/folder, output)
                if previous is None:
                    if catalog['games'][folder].get('metadata_overrides'):
                        raise ValueError(tr("Undo this game's metadata changes before removing its registration."))
                    if catalog['games'][folder]['images'] or (directory.exists() and any(directory.iterdir())):
                        raise ValueError(tr("Undo the new games' images first; registration undo only removes empty folders"))
                    if directory.exists():
                        remove.append(directory)
                for view in (catalog, base):
                    if previous is None:
                        view['games'].pop(folder)
                    else:
                        current = view['games'][folder]
                        restored = {k:v for k,v in deepcopy(previous).items()
                                    if k not in {'metadata_id', 'metadata_overrides'}}
                        restored.update({k:deepcopy(current[k]) for k in ('metadata_id', 'metadata_overrides') if k in current})
                        view['games'][folder] = {**restored, 'images':current['images']}
            history.pop()
            self._commit(output, self._payloads(output, catalog, base, state, history), remove=remove)
            return list(event['after'])
