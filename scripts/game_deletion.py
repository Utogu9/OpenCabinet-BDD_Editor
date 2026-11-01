"""Delete a game's complete directory and catalogue entry with a durable backup."""
from copy import deepcopy
import json
from pathlib import Path

from editor_common import digest, is_link
from editor_store import component, inside, json_bytes, stamp
from game_registration import GameRegistration
from i18n import tr


class GameDeletion(GameRegistration):
    def paths(self, output):
        output = self.store.output(output)
        key = digest(output.relative_to(self.store.generated).as_posix().encode())
        private = inside(self.store.manual / 'game-deletion' / key, self.store.root)
        return private / 'history.json', private / 'pending.json'

    def _ready(self, output):
        from metadata_store import MetadataStore
        self._recover(output)
        GameRegistration(self.store)._recover(output)
        MetadataStore(self.store)._recover(output)
        inside(output / 'catalog.json', output)
        return self._views(output)

    def _snapshot(self, output, serial, catalog):
        component(serial)
        if serial not in catalog['games']:
            raise ValueError(tr('The selected game is no longer in the catalogue.'))
        game_path = output / serial
        if game_path.is_symlink() or (game_path.exists() and is_link(game_path)):
            raise ValueError(tr('Links are not allowed in editing paths'))
        directory = inside(game_path, output)
        files, directories = [], []

        def visit(folder):
            if is_link(folder):
                raise ValueError(tr('Links are not allowed in editing paths'))
            inside(folder, output)
            if not folder.is_dir():
                raise ValueError(tr('The game path must be a directory.'))
            directories.append(folder)
            for path in sorted(folder.iterdir()):
                if is_link(path):
                    raise ValueError(tr('Links are not allowed in editing paths'))
                path = inside(path, directory)
                if path.is_dir():
                    visit(path)
                elif path.is_file():
                    raw = path.read_bytes()
                    files.append({'path': path.relative_to(output).as_posix(),
                                  'sha256': digest(raw), 'bytes': len(raw)})
                else:
                    raise ValueError(tr('Unsupported file in the game directory.'))

        if directory.exists():
            visit(directory)
        for asset in catalog['games'][serial].get('images', {}).values():
            inside(output / asset['path'], directory)
        contents = {'catalog_sha256': digest((output / 'catalog.json').read_bytes()),
                    'files': files, 'directories': [p.relative_to(output).as_posix() for p in directories]}
        titles = [e['name'] for e in catalog['games'][serial].get('entries', []) if e.get('name')]
        return {**contents, 'token': digest(json_bytes(contents)), 'serial': serial,
                'title': titles[0] if titles else serial, 'directory': str(directory),
                'file_count': len(files), 'bytes': sum(f['bytes'] for f in files)}

    def preview(self, output, serial):
        output = self.store.output(output)
        with self.store.writer():
            catalog, _, _ = self._ready(output)
            return self._snapshot(output, serial, catalog)

    def _private_changes(self, output, serial, catalog):
        """Retire only this game's edits so a later DAT registration starts clean."""
        from metadata_store import MetadataStore
        payloads = {self.store.manifest_path(catalog['system'], serial): None}
        metadata_path, _ = MetadataStore(self.store).paths(output)
        if metadata_path.exists():
            events = json.loads(metadata_path.read_text(encoding='utf-8'))
            payloads[metadata_path] = json_bytes([e for e in events if e['serial'] != serial])
        registration_path, _ = GameRegistration(self.store).paths(output)
        if registration_path.exists():
            events = json.loads(registration_path.read_text(encoding='utf-8'))
            remaining = []
            for event in events:
                event = deepcopy(event)
                event['before'].pop(serial, None)
                event['after'].pop(serial, None)
                event['created'] = [folder for folder in event['created'] if folder != serial]
                if event['after']:
                    remaining.append(event)
            payloads[registration_path] = json_bytes(remaining)
        return payloads

    def delete(self, output, serial, expected):
        output = self.store.output(output)
        with self.store.writer():
            catalog, base, state = self._ready(output)
            snapshot = self._snapshot(output, serial, catalog)
            if snapshot['token'] != expected:
                raise ValueError(tr('The game changed after confirmation; review it before deleting.'))
            history_path, _ = self.paths(output)
            history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else []
            payloads = self._private_changes(output, serial, catalog)
            directory = inside(output / serial, output)
            for view in (catalog, base):
                view['games'].pop(serial, None)
            if state is not None:
                state = deepcopy(state)
                state['files'] = {key: value for key, value in state['files'].items()
                                  if not inside(output / key, output).is_relative_to(directory)}
                if state['files']:
                    catalog['manual_edits']['images'] = sum(
                        record['manual_sha256'] is not None for record in state['files'].values())
                else:
                    # A state with no edited files must not leave a stale
                    # catalogue overlay that later artwork undo cannot match.
                    state = None
                    payloads[self.store.state_path(output)] = None
                    if 'manual_edits' in base:
                        catalog['manual_edits'] = deepcopy(base['manual_edits'])
                    else:
                        catalog.pop('manual_edits', None)
            for item in snapshot['files']:
                payloads[inside(output / item['path'], directory)] = None
            payloads.update(self._payloads(output, catalog, base, state, history))
            payloads.pop(history_path)
            files = []
            for path, after in payloads.items():
                path = inside(path, self.store.root)
                before = path.read_bytes() if path.exists() else None
                files.append({'path': str(path.relative_to(self.store.root)),
                              'before': self.store.blob(before) if before is not None else None,
                              'after': self.store.blob(after) if after is not None else None})
            history.append({'at': stamp(), 'serial': serial, 'title': snapshot['title'],
                            'files': files, 'directories': snapshot['directories']})
            payloads[history_path] = json_bytes(history)
            # All absolute paths are validated before deleting individual files;
            # rmdir then removes only the verified, now-empty game directories.
            directories = [inside(output / name, output) for name in snapshot['directories']]
            self._commit(output, payloads, remove=list(reversed(directories)))
            return snapshot

    def undo(self, output):
        output = self.store.output(output)
        with self.store.writer():
            self._ready(output)
            history_path, _ = self.paths(output)
            history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else []
            if not history:
                raise ValueError(tr('There are no game deletions to undo for this console.'))
            event = history[-1]
            directory = inside(output / component(event['serial']), output)
            # Refuse a newly-created folder, including untracked or empty files.
            if directory.exists():
                raise ValueError(tr('The library changed after deletion; undo later changes before restoring the game.'))
            payloads = {}
            for item in event['files']:
                path = inside(self.store.root / item['path'], self.store.root)
                current = digest(path.read_bytes()) if path.exists() else None
                expected = Path(item['after']).stem if item['after'] else None
                if current != expected:
                    raise ValueError(tr('The library changed after deletion; undo later changes before restoring the game.'))
                payloads[path] = self.store.read_blob(item['before']) if item['before'] else None
            directories = [inside(output / name, output) for name in event['directories']]
            if any(p != directory and not p.is_relative_to(directory) for p in directories):
                raise ValueError(tr('Path outside the library'))
            history.pop()
            payloads[history_path] = json_bytes(history)
            self._commit(output, payloads, create=directories)
            return event['serial']
