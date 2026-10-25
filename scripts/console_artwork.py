"""Console artwork at the library root; independent from game catalogues."""
from i18n import tr
import json
from pathlib import Path

from PIL import Image
from editor_store import ArtworkStore, atomic_bytes, inside, json_bytes, stamp
from editor_common import digest

CONSOLE_KINDS = {'logo': 'Console logo', 'render': 'Console render',
                 'screenshot': 'Console screenshot'}


class ConsoleArtwork:
    def __init__(self, store):
        self.store = store

    def paths(self, output):
        output = self.store.output(output)
        key = digest(str(output.relative_to(self.store.generated)).encode('utf-8'))
        private = inside(self.store.manual/'console-assets'/key, self.store.root)
        return output, output/'console_artwork.json', private/'history.json', private/'pending.json'

    def images(self, output):
        output, metadata, _, _ = self.paths(output)
        values = json.loads(metadata.read_text(encoding='utf-8')).get('images', {}) if metadata.exists() else {}
        result = {}
        for kind in CONSOLE_KINDS:
            record = values.get(kind, {})
            filename = record.get('path', kind + '.webp')
            if filename not in {kind + '.webp', kind + '.svg'} or (filename.endswith('.svg') and kind != 'logo'):
                raise ValueError(tr('Invalid console artwork path.'))
            path = inside(output/filename, output)
            if not path.exists() and kind == 'logo' and not record:
                path = inside(output/'logo.svg', output)
            if path.exists():
                if path.suffix == '.svg':
                    from svg_tools import svg_info
                    width, height = svg_info(path.read_bytes())
                else:
                    with Image.open(path) as image:
                        width, height = image.size
                result[kind] = {**record, 'path': path.name, 'kind': kind, 'format': 'SVG' if path.suffix == '.svg' else 'WEBP',
                                'width': width, 'height': height, 'bytes': path.stat().st_size}
        return result

    def recover(self, pending):
        if not pending.exists():
            return
        plan = json.loads(pending.read_text(encoding='utf-8'))
        for item in plan:
            path = inside(self.store.root/item['path'], self.store.root)
            if path.exists() and digest(path.read_bytes()) not in {
                    Path(item[key]).stem if item[key] else None for key in ('before', 'after')}:
                raise ValueError(tr('A console file changed outside the editor; it will not be overwritten'))
            for key in ('before', 'after'):
                if item[key]:
                    self.store.read_blob(item[key])
        for item in plan:
            path = inside(self.store.root/item['path'], self.store.root)
            if item['before'] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, self.store.read_blob(item['before']))
        pending.unlink()

    def commit(self, pending, changes):
        plan = [{'path': str(path.relative_to(self.store.root)),
                 'before': self.store.blob(path.read_bytes()) if path.exists() else None,
                 'after': self.store.blob(data) if data is not None else None} for path, data in changes]
        atomic_bytes(pending, json_bytes(plan))
        try:
            for path, data in changes:
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, data)
            pending.unlink()
        except BaseException:
            self.recover(pending)
            raise

    def save(self, output, kind, encoded):
        if kind not in CONSOLE_KINDS or encoded.get('format') == 'PDF' or (encoded.get('format') == 'SVG' and kind != 'logo'):
            raise ValueError(tr('Console artwork supports logo, render and screenshot in WebP'))
        with self.store.writer():
            output, metadata, history_path, pending = self.paths(output)
            self.recover(pending)
            catalog = self.store.read_catalog(output)
            if catalog.get('status') not in {'complete', 'sample_complete'}:
                raise ValueError(tr('Wait for this console to finish generating'))
            values = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {
                'schema_version': 1, 'system': catalog['system'], 'images': {}}
            history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {'events': []}
            extension = 'svg' if encoded.get('format') == 'SVG' else 'webp'
            destination = inside(output/(kind+'.'+extension), output)
            old = values['images'].get(kind)
            previous_name = old.get('path', kind+'.webp') if old else kind+'.webp'
            if not old and not (output/previous_name).exists() and kind == 'logo' and (output/'logo.svg').exists():
                previous_name = 'logo.svg'
            if previous_name not in {kind+'.webp', 'logo.svg' if kind == 'logo' else kind+'.webp'}:
                raise ValueError(tr('Invalid console artwork path.'))
            previous_path = inside(output/previous_name, output)
            previous = previous_path.read_bytes() if previous_path.exists() else None
            if destination != previous_path and destination.exists():
                raise ValueError(tr('An uncatalogued console logo already exists at the destination.'))
            if old and (previous is None or digest(previous) != old['sha256']):
                raise ValueError(tr('Console artwork changed outside the editor; refresh and review it'))
            history['events'].append({'kind': kind, 'previous': self.store.blob(previous) if previous is not None else None,
                                      'metadata': old, 'previous_path': previous_path.name,
                                      'saved_path': destination.name, 'at': stamp()})
            asset = {k: encoded[k] for k in ('sha256', 'bytes', 'width', 'height', 'alpha', 'compression', 'filename', 'source_sha256')}
            asset.update({'path': destination.name, 'kind': kind,
                          'original_blob': self.store.blob(encoded['original']), 'updated_at': stamp(),
                          'manual': encoded.get('manual', True), 'format': encoded.get('format', 'WEBP'), 'extension': extension})
            if encoded.get('sources'):
                asset['sources'] = encoded['sources']
            values['images'][kind] = asset
            changes = ([(previous_path, None)] if previous_path != destination else [])
            self.commit(pending, [*changes, (destination, encoded['data']), (metadata, json_bytes(values)),
                                  (history_path, json_bytes(history))])
            return asset

    def undo(self, output, kind=None):
        with self.store.writer():
            output, metadata, history_path, pending = self.paths(output)
            self.recover(pending)
            if not history_path.exists():
                raise ValueError(tr('There are no console changes to undo'))
            history = json.loads(history_path.read_text(encoding='utf-8'))
            index = next((i for i in range(len(history['events'])-1, -1, -1)
                          if kind is None or history['events'][i]['kind'] == kind), None)
            if index is None:
                raise ValueError(tr('There are no more console changes to undo'))
            event = history['events'].pop(index)
            values = json.loads(metadata.read_text(encoding='utf-8'))
            current = values['images'].get(event['kind'])
            allowed = {event['kind']+'.webp', 'logo.svg' if event['kind'] == 'logo' else event['kind']+'.webp'}
            if (current and current.get('path', event['kind']+'.webp') not in allowed) or event.get('previous_path', event['kind']+'.webp') not in allowed:
                raise ValueError(tr('Invalid console artwork path.'))
            target = inside(output/(current.get('path') if current else event['kind']+'.webp'), output)
            previous_path = inside(output/event.get('previous_path', event['kind']+'.webp'), output)
            if not current or not target.exists() or digest(target.read_bytes()) != current['sha256']:
                raise ValueError(tr('Console artwork changed outside the editor'))
            history.setdefault('undone', []).append({'asset': current, 'at': stamp()})
            if event['metadata'] is None:
                values['images'].pop(event['kind'], None)
            else:
                values['images'][event['kind']] = event['metadata']
            data = self.store.read_blob(event['previous']) if event['previous'] else None
            if previous_path != target and previous_path.exists():
                raise ValueError(tr('The previous console logo path is occupied.'))
            changes = [(target, None), (previous_path, data)] if previous_path != target else [(target, data)]
            self.commit(pending, [*changes, (metadata, json_bytes(values)), (history_path, json_bytes(history))])
