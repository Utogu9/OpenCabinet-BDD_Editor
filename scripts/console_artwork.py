"""Console artwork at the library root; independent from game catalogues."""
from i18n import tr
import json
import re
from pathlib import Path

from PIL import Image
from editor_store import ArtworkStore, atomic_bytes, inside, json_bytes, stamp
from editor_common import digest

CONSOLE_KINDS = {'logo': 'Console logo', 'render': 'Console render',
                 'screenshot': 'Console screenshot'}


def label_kind(label):
    for kind in CONSOLE_KINDS:
        if re.fullmatch(kind + r'(?:[2-9]|[1-9][0-9]+)?', label):
            return kind
    raise ValueError(tr('Invalid console artwork path.'))


def valid_filename(label, filename):
    kind = label_kind(label)
    if filename not in {label + '.webp', label + '.svg'} or (filename.endswith('.svg') and kind != 'logo'):
        raise ValueError(tr('Invalid console artwork path.'))
    return filename


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
        labels = set(values)
        for path in output.iterdir():
            if path.suffix in {'.webp', '.svg'}:
                try:
                    valid_filename(path.stem, path.name)
                except ValueError:
                    continue
                labels.add(path.stem)
        for label in sorted(labels):
            kind = label_kind(label)
            record = values.get(label, {})
            filename = valid_filename(label, record.get('path', label + '.webp'))
            path = inside(output/filename, output)
            if not path.exists() and kind == 'logo' and not record:
                path = inside(output/(label+'.svg'), output)
            if path.exists():
                if path.suffix == '.svg':
                    from svg_tools import svg_info
                    width, height = svg_info(path.read_bytes())
                else:
                    with Image.open(path) as image:
                        width, height = image.size
                result[label] = {**record, 'path': path.name, 'kind': kind, 'format': 'SVG' if path.suffix == '.svg' else 'WEBP',
                                'width': width, 'height': height, 'bytes': path.stat().st_size}
        return result

    def next_label(self, output, kind):
        if kind not in CONSOLE_KINDS:
            raise ValueError(tr('Invalid console artwork path.'))
        output, metadata, _, _ = self.paths(output)
        occupied = set(json.loads(metadata.read_text(encoding='utf-8')).get('images', {})) if metadata.exists() else set()
        occupied.update(path.stem for path in output.iterdir() if path.is_file())
        number = 1
        while (label := kind if number == 1 else f'{kind}{number}') in occupied:
            number += 1
        return label

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

    def save(self, output, kind, encoded, label=None, *, create_only=False):
        label = kind if label is None else label
        if label_kind(label) != kind:
            raise ValueError(tr('Invalid console artwork path.'))
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
            destination = inside(output/(label+'.'+extension), output)
            old = values['images'].get(label)
            previous_name = old.get('path', label+'.webp') if old else label+'.webp'
            if not old and not (output/previous_name).exists() and kind == 'logo' and (output/(label+'.svg')).exists():
                previous_name = label+'.svg'
            valid_filename(label, previous_name)
            if create_only and (old is not None or any(path.stem == label for path in output.iterdir())):
                raise ValueError(tr('This variant already exists; refresh before importing again.'))
            previous_path = inside(output/previous_name, output)
            previous = previous_path.read_bytes() if previous_path.exists() else None
            if destination != previous_path and destination.exists():
                raise ValueError(tr('An uncatalogued console logo already exists at the destination.'))
            if old and (previous is None or digest(previous) != old['sha256']):
                raise ValueError(tr('Console artwork changed outside the editor; refresh and review it'))
            for path in output.iterdir():
                try:
                    if label_kind(path.stem) != kind or path.stem == label:
                        continue
                    valid_filename(path.stem, path.name)
                except ValueError:
                    continue
                if path.is_file() and path.read_bytes() == encoded['data']:
                    raise ValueError(tr('This file already exists as {v0}; no duplicate will be created', v0=path.name))
            history['events'].append({'kind': kind, 'label': label, 'previous': self.store.blob(previous) if previous is not None else None,
                                      'metadata': old, 'previous_path': previous_path.name,
                                      'saved_path': destination.name, 'at': stamp()})
            asset = {k: encoded[k] for k in ('sha256', 'bytes', 'width', 'height', 'alpha', 'compression', 'filename', 'source_sha256')}
            asset.update({'path': destination.name, 'kind': kind,
                          'original_blob': self.store.blob(encoded['original']), 'updated_at': stamp(),
                          'manual': encoded.get('manual', True), 'format': encoded.get('format', 'WEBP'), 'extension': extension})
            if encoded.get('sources'):
                asset['sources'] = encoded['sources']
            values['images'][label] = asset
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
                          if kind is None or kind in history['events'][i].get('labels', [history['events'][i].get('label', history['events'][i]['kind'])])), None)
            if index is None:
                raise ValueError(tr('There are no more console changes to undo'))
            event = history['events'].pop(index)
            values = json.loads(metadata.read_text(encoding='utf-8'))
            if event.get('operation'):
                from artwork_actions import undo_console_action
                undo_console_action(self, output, values, history, event, metadata, history_path, pending)
                return
            label = event.get('label', event['kind'])
            if label_kind(label) != event['kind']:
                raise ValueError(tr('Invalid console artwork path.'))
            current = values['images'].get(label)
            target = inside(output/valid_filename(label, current.get('path', label+'.webp') if current else label+'.webp'), output)
            previous_path = inside(output/valid_filename(label, event.get('previous_path', label+'.webp')), output)
            if not current or not target.exists() or digest(target.read_bytes()) != current['sha256']:
                raise ValueError(tr('Console artwork changed outside the editor'))
            history.setdefault('undone', []).append({'asset': current, 'at': stamp()})
            if event['metadata'] is None:
                values['images'].pop(label, None)
            else:
                values['images'][label] = event['metadata']
            data = self.store.read_blob(event['previous']) if event['previous'] else None
            if previous_path != target and previous_path.exists():
                raise ValueError(tr('The previous console logo path is occupied.'))
            changes = [(target, None), (previous_path, data)] if previous_path != target else [(target, data)]
            self.commit(pending, [*changes, (metadata, json_bytes(values)), (history_path, json_bytes(history))])
