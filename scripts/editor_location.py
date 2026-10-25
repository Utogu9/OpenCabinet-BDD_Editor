"""Find and validate an editor library without touching the converter."""
from i18n import tr
import json
from pathlib import Path

from editor_store import ArtworkStore
from editor_common import is_link, write_json
from editor_settings import read_settings, update_settings


def valid_library(directory, samples=False):
    directory = Path(directory)
    if not directory.is_dir() or is_link(directory):
        return False
    candidates = [p for p in directory.iterdir() if p.is_dir() and not p.name.startswith('_')]
    revisions = directory/'_revisions'
    if revisions.is_dir() and not is_link(revisions):
        candidates += [p for v in revisions.iterdir() if v.is_dir() and not is_link(v)
                       for p in v.iterdir() if p.is_dir()]
    if samples and (directory/'_samples').is_dir() and not is_link(directory/'_samples'):
        candidates += [p.parent for p in (directory/'_samples').rglob('catalog.json')]
    for candidate in candidates:
        if is_link(candidate):
            continue
        index = candidate/'checkpoint.json' if (candidate/'checkpoint.json').exists() else candidate/'catalog.json'
        try:
            if is_link(index):
                continue
            catalog = json.loads(index.read_text(encoding='utf-8-sig'))
            if (catalog.get('schema_version') in {2, 3} and isinstance(catalog.get('system'), str)
                    and isinstance(catalog.get('games'), dict)):
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def selected_library(directory, samples=False):
    directory = Path(directory).resolve()
    if valid_library(directory, samples):
        return directory
    if valid_library(directory/'generated', samples):
        return directory/'generated'
    return None


def choose_library(root, settings, ask, error, samples=False):
    default = Path(root)/'generated'
    if valid_library(default, samples):
        return default.resolve()
    try:
        remembered = read_settings(settings)['library']
        result = selected_library(remembered, samples)
        if result:
            return result
    except (OSError, ValueError, KeyError, TypeError):
        pass
    while True:
        chosen = ask()
        if not chosen:
            return None
        result = selected_library(chosen, samples)
        if result:
            try:
                update_settings({'library': str(result)}, settings)
            except OSError:
                # Read-only application folders must not prevent opening artwork.
                pass
            return result
        error(tr('No valid library was found. Choose the folder containing the consoles and their catalog.json files, or the project folder containing generated.'))


class LocatedArtworkStore(ArtworkStore):
    def __init__(self, directory):
        directory = Path(directory).resolve()
        super().__init__(directory.parent)
        self.generated = directory
        # Keep arbitrary named exports self-contained, avoiding shared drive-root backups.
        if directory.name != 'generated':
            self.manual = directory/'_editor'
