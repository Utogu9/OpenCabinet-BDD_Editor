"""Local manual artwork, reversible exports and shared batch/editor locking."""
from i18n import tr
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageOps
from editor_common import ROOT, compare_encodings, digest, is_link, write_json


def stamp():
    return datetime.now(timezone.utc).isoformat()


def component(value):
    if not value or value in {'.', '..'} or any(c in value for c in '/\\\x00:'):
        raise ValueError(tr('Invalid folder name'))
    return value


def inside(path, base):
    base, path = Path(base).resolve(), Path(path)
    if not path.resolve().is_relative_to(base) or path.resolve() == base:
        raise ValueError(tr('Path outside the library'))
    for parent in [path, *path.parents]:
        if parent == base:
            break
        if parent.exists() and is_link(parent):
            raise ValueError(tr('Links are not allowed in editing paths'))
    return path.resolve()


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as f:
        temporary = Path(f.name)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')


def encode_import(path):
    path = Path(path)
    if path.stat().st_size > 100*1024**2:
        raise ValueError(tr('The image exceeds 100 MiB'))
    raw = path.read_bytes()
    with Image.open(BytesIO(raw)) as original:
        if original.format not in {'PNG', 'JPEG', 'WEBP'}:
            raise ValueError(tr('PNG, JPG and WebP files are supported'))
        if getattr(original, 'n_frames', 1) != 1:
            raise ValueError(tr('The image must be static'))
        if original.width*original.height > 40_000_000:
            raise ValueError(tr('The image exceeds 40 megapixels'))
        image = ImageOps.exif_transpose(original)
        alpha = 'A' in image.getbands() or 'transparency' in image.info
        image = image.convert('RGBA' if alpha else 'RGB')
        data, compression = compare_encodings(image, original.info.get('icc_profile'))
        with Image.open(BytesIO(data)) as check:
            if check.size != image.size:
                raise ValueError(tr('Conversion changed the dimensions'))
            if compression['lossless'] and check.convert('RGBA').tobytes() != image.convert('RGBA').tobytes():
                raise ValueError(tr('Lossless conversion changed the pixels'))
            if alpha and check.convert('RGBA').getchannel('A').tobytes() != image.getchannel('A').tobytes():
                raise ValueError(tr('Conversion changed the transparency'))
        return {'data': data, 'original': raw, 'filename': path.name, 'sha256': digest(data),
                'source_sha256': digest(raw), 'source_format': original.format,
                'width': image.width, 'height': image.height, 'alpha': alpha,
                'bytes': len(data), 'compression': compression}


class ArtworkStore:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.generated = self.root/'generated'
        self.manual = self.root/'manual'

    def output(self, output):
        return inside(Path(output), self.generated)

    def blob(self, data):
        path = inside(self.manual/'blobs'/(digest(data)+'.bin'), self.root)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError(tr('Corrupted backup'))
        else:
            atomic_bytes(path, data)
        return str(path.relative_to(self.root))

    def read_blob(self, relative):
        path = inside(self.root/relative, self.manual/'blobs')
        data = path.read_bytes()
        if path.stem != digest(data):
            raise ValueError(tr('Invalid backup hash'))
        return data

    def state_path(self, output):
        output = self.output(output)
        key = digest(str(output.relative_to(self.generated)).encode('utf-8'))
        return inside(self.manual/'exports'/key/'state.json', self.root)

    def manifest_path(self, system, serial):
        return inside(self.manual/component(system)/component(serial)/'edits.json', self.root)

    def read_catalog(self, output):
        output = self.output(output)
        path = output/'checkpoint.json' if (output/'checkpoint.json').exists() else output/'catalog.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def libraries(self, samples=False):
        if not self.generated.exists():
            return []
        candidates = [p for p in self.generated.iterdir() if p.is_dir() and not p.name.startswith('_')]
        revisions = self.generated/'_revisions'
        if revisions.exists():
            candidates += [p for version in revisions.iterdir() if version.is_dir()
                           for p in version.iterdir() if p.is_dir()]
        if samples and (self.generated/'_samples').exists():
            candidates += [p.parent for p in (self.generated/'_samples').rglob('catalog.json')]
        result = []
        for output in candidates:
            try:
                output = self.output(output)
                index = output/'checkpoint.json' if (output/'checkpoint.json').exists() else output/'catalog.json'
                if not index.exists():
                    continue
                # Read system from the folder layout; large catalogues load on demand.
                system = output.name if '_samples' not in output.parts else output.parent.name
                result.append({'system': system, 'output': output, 'index': index,
                               'revision': str(output.relative_to(self.generated)), 'mtime': index.stat().st_mtime_ns})
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda r: (r['system'].casefold(), -r['mtime']))

    def lock_status(self):
        lock = self.root/'reports/batch.lock'
        if lock.exists():
            return tr('Run-Library or another editor is using the library')
        return ''

    @contextmanager
    def writer(self):
        lock = self.root/'reports/batch.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = lock.open('x', encoding='utf-8')
        except FileExistsError:
            raise ValueError(tr('The library is in use. Wait for Run-Library to finish before editing.'))
        try:
            with handle:
                handle.write(json.dumps({'pid': os.getpid(), 'started_at_utc': stamp(), 'owner': 'artwork-editor'}))
            yield
        finally:
            lock.unlink(missing_ok=True)

    def restore_output(self, output):
        """Caller owns batch.lock. Restore generated assets before reconversion."""
        output = self.output(output)
        state_path = self.state_path(output)
        if not state_path.exists():
            return
        state = json.loads(state_path.read_text(encoding='utf-8'))
        base = self.read_blob(state['base_catalog'])
        catalog_path = inside(output/'catalog.json', output)
        if catalog_path.exists() and digest(catalog_path.read_bytes()) not in {
                digest(base), state['applied_catalog_sha256']}:
            raise ValueError(tr('The catalogue changed outside the editor; it will not be overwritten'))
        plan = []
        for relative, record in state['files'].items():
            destination = inside(output/relative, output)
            previous = self.read_blob(record['base']) if record['base'] else None
            if destination.exists() and digest(destination.read_bytes()) not in {
                    record['manual_sha256'], digest(previous) if previous is not None else None}:
                raise ValueError(tr('The image changed outside the editor: {v0}', v0=relative))
            plan.append((destination, previous))
        for destination, previous in plan:
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                atomic_bytes(destination, previous)
        atomic_bytes(catalog_path, base)
        state_path.unlink()

    def apply_to_output(self, output):
        """Caller owns batch.lock. Apply edits to a finished, verified catalogue."""
        output = self.output(output)
        self.restore_output(output)
        path = output/'catalog.json'
        if not path.exists():
            return 0
        raw = path.read_bytes()
        catalog = json.loads(raw)
        if catalog.get('schema_version') != 2 or catalog.get('status') not in {'complete', 'sample_complete'}:
            return 0
        system = component(catalog['system'])
        edited, files, payloads = deepcopy(catalog), {}, {}
        for serial, game in edited['games'].items():
            manifest_path = self.manifest_path(system, serial)
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            for label, asset in manifest['images'].items():
                if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', label):
                    raise ValueError(tr('Invalid manual image name'))
                extension = asset.get('extension', 'webp')
                if extension not in {'webp', 'pdf'}:
                    raise ValueError(tr('Unsupported manual extension'))
                relative = f'{component(serial)}/{label}.{extension}'
                destination = inside(output/relative, output)
                data = self.read_blob(asset['blob'])
                if digest(data) != asset['sha256']:
                    raise ValueError(tr('Corrupted manual image'))
                base_asset = game['images'].get(label)
                if destination.exists() and (base_asset is None or base_asset['path'] != relative):
                    raise ValueError(tr('Uncatalogued file: {v0}', v0=relative))
                base_destination = inside(output/base_asset['path'], output) if base_asset else destination
                previous = base_destination.read_bytes() if base_destination.exists() else None
                if base_asset and (previous is None or digest(previous) != base_asset['sha256']):
                    raise ValueError(tr('The generated image changed: {v0}', v0=relative))
                if base_asset and base_asset['path'] != relative:
                    files[base_asset['path']] = {'base': self.blob(previous), 'manual_sha256': None}
                    payloads[base_asset['path']] = None
                    previous = None
                files[relative] = {'base': self.blob(previous) if previous is not None else None,
                                   'manual_sha256': asset['sha256']}
                payloads[relative] = data
                game['images'][label] = {k: asset[k] for k in ('kind', 'sha256', 'bytes', 'width', 'height', 'alpha', 'compression')}
                game['images'][label].update({k: asset[k] for k in ('format', 'extension', 'pages') if k in asset})
                game['images'][label].update({'path': relative, 'sources': (base_asset or {}).get('sources', []),
                                             'manual': {k: asset[k] for k in ('blob', 'original_blob', 'filename', 'source_sha256', 'updated_at')}})
        if not files:
            return 0
        count = sum(record['manual_sha256'] is not None for record in files.values())
        edited['manual_edits'] = {'schema_version': 1, 'images': count, 'updated_at': stamp()}
        encoded_catalog = json_bytes(edited)
        state = {'output': str(output.relative_to(self.generated)), 'base_catalog': self.blob(raw),
                 'applied_catalog_sha256': digest(encoded_catalog), 'files': files}
        state_path = self.state_path(output)
        # Durable journal before touching the export; recover after any interrupted save.
        write_json(state_path, state)
        try:
            for relative, data in payloads.items():
                destination = inside(output/relative, output)
                if data is None:
                    destination.unlink(missing_ok=True)
                else:
                    atomic_bytes(destination, data)
            atomic_bytes(path, encoded_catalog)
        except BaseException:
            self.restore_output(output)
            raise
        return count

    def save(self, output, serial, kind, label, encoded, *, create_only=False):
        output = self.output(output)
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', label) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', kind):
            raise ValueError(tr('Use lowercase letters, numbers and underscores for the type'))
        if (kind == 'manual') != (encoded.get('format') == 'PDF'):
            raise ValueError(tr('The manual type accepts complete PDFs; other types accept images'))
        with self.writer():
            catalog = self.read_catalog(output)
            if catalog.get('status') not in {'complete', 'sample_complete'} or catalog.get('schema_version') != 2:
                raise ValueError(tr('Wait for this console to finish generating'))
            if serial not in catalog['games']:
                raise ValueError(tr('The game is no longer in this catalogue'))
            directory = inside(output/serial, output)
            if create_only and (label in catalog['games'][serial]['images'] or
                                (directory.exists() and any(path.stem == label for path in directory.iterdir()))):
                raise ValueError(tr('This variant already exists; refresh before importing again.'))
            for existing_label, image in catalog['games'][serial]['images'].items():
                if existing_label != label and image['kind'] == kind and image['sha256'] == encoded['sha256']:
                    if inside(output/image['path'], output).read_bytes() == encoded['data']:
                        raise ValueError(tr('This file already exists as {v0}; no duplicate will be created', v0=Path(image['path']).name))
            path = self.manifest_path(catalog['system'], serial)
            previous_manifest = path.read_bytes() if path.exists() else None
            manifest = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
                'schema_version': 1, 'system': catalog['system'], 'serial': serial, 'images': {}, 'history': []}
            old = manifest['images'].get(label)
            manifest['history'].append({'label': label, 'previous': old, 'at': stamp()})
            asset = {k: encoded[k] for k in ('sha256', 'bytes', 'width', 'height', 'alpha', 'compression', 'filename', 'source_sha256')}
            asset.update({k: encoded[k] for k in ('format', 'extension', 'pages') if k in encoded})
            asset.update({'kind': kind, 'blob': self.blob(encoded['data']),
                          'original_blob': self.blob(encoded['original']), 'updated_at': stamp()})
            manifest['images'][label] = asset
            write_json(path, manifest)
            try:
                self.apply_to_output(output)
            except Exception:
                if previous_manifest is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, previous_manifest)
                self.apply_to_output(output)
                raise
        return asset

    def reset(self, output, serial, label):
        with self.writer():
            catalog = self.read_catalog(output)
            path = self.manifest_path(catalog['system'], serial)
            previous_manifest = path.read_bytes()
            manifest = json.loads(path.read_text(encoding='utf-8'))
            old = manifest['images'].pop(label)
            manifest['history'].append({'label': label, 'previous': old, 'at': stamp()})
            write_json(path, manifest)
            try:
                self.apply_to_output(output)
            except Exception:
                atomic_bytes(path, previous_manifest)
                self.apply_to_output(output)
                raise

    def undo(self, output, serial):
        with self.writer():
            catalog = self.read_catalog(output)
            path = self.manifest_path(catalog['system'], serial)
            if not path.exists():
                raise ValueError(tr('There are no changes to undo for this game'))
            previous_manifest = path.read_bytes()
            manifest = json.loads(previous_manifest)
            if not manifest.get('history'):
                raise ValueError(tr('There are no more changes to undo for this game'))
            event = manifest['history'].pop()
            label = event['label']
            manifest.setdefault('undone_changes', []).append({'label': label,
                'image': manifest['images'].get(label), 'at': stamp()})
            if event['previous'] is None:
                manifest['images'].pop(label, None)
            else:
                manifest['images'][label] = event['previous']
            write_json(path, manifest)
            try:
                self.apply_to_output(output)
            except Exception:
                atomic_bytes(path, previous_manifest)
                self.apply_to_output(output)
                raise

    def verification_view(self, output, actual):
        """Validate manual files; supply the untouched generated view to its verifier."""
        output = self.output(output)
        state_path = self.state_path(output)
        if not state_path.exists():
            if actual.get('manual_edits'):
                raise ValueError(tr('The edited catalogue backup is missing'))
            return actual, {}, set()
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if digest((output/'catalog.json').read_bytes()) != state['applied_catalog_sha256']:
            raise ValueError(tr('Incomplete edit or manually modified catalogue'))
        base = json.loads(self.read_blob(state['base_catalog']))
        redirects, extras = {}, set()
        for relative, record in state['files'].items():
            path = inside(output/relative, output)
            if record['manual_sha256'] is None:
                if path.exists():
                    raise ValueError(tr('A file removed by the edit has reappeared'))
                self.read_blob(record['base'])
                redirects[relative] = inside(self.root/record['base'], self.manual/'blobs')
                continue
            if digest(path.read_bytes()) != record['manual_sha256']:
                raise ValueError(tr('The manual image changed outside the editor'))
            serial, filename = relative.split('/')
            asset = actual['games'][serial]['images'][Path(filename).stem]
            manual = asset['manual']
            data, original = self.read_blob(manual['blob']), self.read_blob(manual['original_blob'])
            if digest(original) != manual['source_sha256'] or digest(data) != asset['sha256'] or path.read_bytes() != data:
                raise ValueError(tr('Invalid manual provenance'))
            if asset.get('format') == 'PDF':
                from pdf_tools import read_pdf, signature
                pdf = read_pdf(data)
                if len(pdf.pages) != asset['pages'] or signature(pdf) != signature(read_pdf(original)):
                    raise ValueError(tr('Manual pages or text were altered'))
                if len(data) != asset['bytes'] or asset['bytes'] != min(asset['compression']['candidate_bytes'].values()):
                    raise ValueError(tr('Invalid manual size'))
                if record['base']:
                    self.read_blob(record['base'])
                    redirects[relative] = inside(self.root/record['base'], self.manual/'blobs')
                else:
                    extras.add(relative)
                continue
            with Image.open(BytesIO(original)) as source, Image.open(BytesIO(data)) as converted:
                if converted.format != 'WEBP' or converted.size != (asset['width'], asset['height']):
                    raise ValueError(tr('Invalid manual dimensions'))
                decision = asset['compression']
                sizes = decision['candidate_bytes']
                if asset['bytes'] != min(sizes.values()) or decision['lossless'] != (sizes['lossless'] <= sizes['lossy90']):
                    raise ValueError(tr('Invalid manual compression choice'))
                if decision['lossless'] and ImageOps.exif_transpose(source).convert('RGBA').tobytes() != converted.convert('RGBA').tobytes():
                    raise ValueError(tr('Invalid lossless manual pixels'))
            if record['base']:
                self.read_blob(record['base'])
                redirects[relative] = inside(self.root/record['base'], self.manual/'blobs')
            else:
                extras.add(relative)
        return base, redirects, extras


def store_for_output(output):
    output = Path(output).resolve()
    for parent in output.parents:
        if parent.name == 'generated':
            return ArtworkStore(parent.parent)
    return None
