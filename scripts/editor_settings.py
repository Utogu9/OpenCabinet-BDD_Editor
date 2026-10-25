"""Shared settings updates that preserve the saved library and preferences."""
import json
from pathlib import Path

from editor_common import settings_path, write_json


def read_settings(path=None):
    path = Path(path) if path is not None else settings_path()
    if not path.exists() and path.name == 'editor-setting.json':
        path = path.with_name('editor-settings.json')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def update_settings(changes, path=None):
    path = Path(path) if path is not None else settings_path()
    current = read_settings(path)
    current.update(changes)
    write_json(path, current)
    return current
