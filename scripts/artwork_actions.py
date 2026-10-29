"""Delete or promote artwork without re-encoding bytes or losing attribution."""
from copy import deepcopy
import json
from pathlib import Path
import re

from editor_common import digest
from editor_store import atomic_bytes, inside, json_bytes, stamp
from i18n import tr


def image_kind(label, asset):
    kind = asset.get('kind', label)
    return re.sub(r'[0-9]+$', '', kind) if kind == label else kind


def game_images(store, output, serial):
    catalog = store.read_catalog(output)
    images = deepcopy(catalog['games'][serial]['images'])
    directory = inside(output/serial, output)
    if directory.exists():
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in {'.webp', '.png', '.jpg', '.jpeg', '.pdf', '.cbz'} and path.stem not in images:
                images[path.stem] = {'path': f'{serial}/{path.name}', 'kind': image_kind(path.stem, {}),
                                     'bytes': path.stat().st_size, 'format': path.suffix[1:].upper()}
    return images


def checked_file(output, asset, expected=None):
    path = inside(output/asset['path'], output)
    data = path.read_bytes()
    checksum = digest(data)
    if (asset.get('sha256') and checksum != asset['sha256']) or (expected and checksum != expected):
        raise ValueError(tr('Artwork changed outside the editor; refresh before editing.'))
    return path, data


def change_game(store, output, serial, label, operation, expected=None):
    output = store.output(output)
    with store.writer():
        catalog = store.read_catalog(output)
        if catalog.get('status') not in {'complete', 'sample_complete'} or catalog.get('schema_version') != 2:
            raise ValueError(tr('Wait for this console to finish generating'))
        images = game_images(store, output, serial)
        selected = images[label]
        kind = image_kind(label, selected)
        if operation not in {'delete', 'primary'} or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', label):
            raise ValueError(tr('Invalid manual image name'))
        if operation == 'primary' and (kind == label or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', kind)):
            raise ValueError(tr('Choose a numbered variant to make primary.'))
        labels = [label] if operation == 'delete' else [label, kind]
        path = store.manifest_path(catalog['system'], serial)
        previous_manifest = path.read_bytes() if path.exists() else None
        manifest = json.loads(previous_manifest) if previous_manifest else {
            'schema_version': 1, 'system': catalog['system'], 'serial': serial, 'images': {}, 'history': []}
        previous = {key: deepcopy(manifest['images'].get(key)) for key in labels}
        snapshots = {}
        for key in labels:
            if key not in images:
                continue
            asset = deepcopy(images[key])
            file_path, data = checked_file(output, asset, expected if key == label else None)
            if file_path.parent != inside(output/serial, output):
                raise ValueError(tr('Path outside the library'))
            asset.update({'sha256': digest(data), 'bytes': len(data), 'kind': kind})
            snapshots[key] = {'catalog_asset': asset, 'blob': store.blob(data)}
        def baseline(key):
            old = previous[key] or {}
            if old.get('base_file'):
                return deepcopy(old['base_file'])
            if key not in catalog['games'][serial]['images'] and key in snapshots:
                return {k: snapshots[key]['catalog_asset'][k] for k in ('path', 'sha256')}
            return None
        if operation == 'delete':
            changes = {label: {'deleted': True, 'kind': kind}}
        else:
            changes = {kind: snapshots[label], label: snapshots.get(kind, {'deleted': True, 'kind': kind})}
        for key, record in changes.items():
            record['base_file'] = baseline(key)
        manifest['history'].append({'label': label, 'operation': operation, 'previous_images': previous, 'at': stamp()})
        manifest['images'].update(changes)
        atomic_bytes(path, json_bytes(manifest))
        try:
            store.apply_to_output(output)
        except BaseException:
            if previous_manifest is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, previous_manifest)
            store.apply_to_output(output)
            raise


def change_console(console, output, label, operation, expected=None):
    store = console.store
    with store.writer():
        output, metadata, history_path, pending = console.paths(output)
        console.recover(pending)
        catalog = store.read_catalog(output)
        if catalog.get('status') not in {'complete', 'sample_complete'}:
            raise ValueError(tr('Wait for this console to finish generating'))
        images = console.images(output)
        selected = images[label]
        kind = selected['kind']
        if operation not in {'delete', 'primary'} or (operation == 'primary' and kind == label):
            raise ValueError(tr('Choose a numbered variant to make primary.'))
        labels = [label] if operation == 'delete' else [label, kind]
        values = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {
            'schema_version': 1, 'system': catalog['system'], 'images': {}}
        history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {'events': []}
        before = {key: deepcopy(values['images'].get(key)) for key in labels}
        assets, data_by_label, payloads = {}, {}, {}
        for key in labels:
            if key in images:
                file_path, data = checked_file(output, images[key], expected if key == label else None)
                assets[key] = deepcopy(values['images'].get(key) or images[key])
                assets[key].update({'sha256': digest(data), 'bytes': len(data)})
                data_by_label[key] = data
                payloads[file_path] = None
        if operation == 'delete':
            values['images'].pop(label, None)
        else:
            for target, source in ((kind, label), (label, kind)):
                if source not in assets:
                    values['images'].pop(target, None)
                    continue
                asset = deepcopy(assets[source])
                asset['path'] = target + Path(asset['path']).suffix
                destination = inside(output/asset['path'], output)
                if destination.exists() and destination not in payloads:
                    raise ValueError(tr('Uncatalogued file: {v0}', v0=destination.name))
                values['images'][target] = asset
                payloads[destination] = data_by_label[source]
        event_files = [{'path': file.name, 'before': store.blob(file.read_bytes()) if file.exists() else None,
                        'after': store.blob(data) if data is not None else None} for file, data in payloads.items()]
        history['events'].append({'operation': operation, 'kind': kind, 'label': label, 'labels': labels,
                                  'previous_images': before, 'after_images': {key: values['images'].get(key) for key in labels},
                                  'files': event_files, 'at': stamp()})
        console.commit(pending, [*payloads.items(), (metadata, json_bytes(values)), (history_path, json_bytes(history))])


def undo_console_action(console, output, values, history, event, metadata, history_path, pending):
    from console_artwork import valid_filename
    changes = []
    for label, expected in event['after_images'].items():
        if values['images'].get(label) != expected:
            raise ValueError(tr('Artwork changed outside the editor; refresh before editing.'))
    for item in event['files']:
        name = item['path']
        if Path(name).stem not in event['labels']:
            raise ValueError(tr('Invalid console artwork path.'))
        valid_filename(Path(name).stem, name)
        path = inside(output/name, output)
        actual = digest(path.read_bytes()) if path.exists() else None
        if actual != (Path(item['after']).stem if item['after'] else None):
            raise ValueError(tr('Artwork changed outside the editor; refresh before editing.'))
        changes.append((path, console.store.read_blob(item['before']) if item['before'] else None))
    for label, asset in event['previous_images'].items():
        if asset is None:
            values['images'].pop(label, None)
        else:
            values['images'][label] = asset
    console.commit(pending, [*changes, (metadata, json_bytes(values)), (history_path, json_bytes(history))])
