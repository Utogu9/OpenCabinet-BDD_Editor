"""English source messages, Spanish translations and live Tk text bindings."""
from weakref import WeakKeyDictionary, ref

from editor_settings import read_settings, update_settings
from translations import SPANISH

_language = 'en'
_bindings = {}
_headings = WeakKeyDictionary()


def language():
    return _language


def initialize_language(path=None):
    global _language
    value = read_settings(path).get('language', 'en')
    _language = value if value in {'en','es'} else 'en'
    return _language


def set_language(value, path=None, persist=True):
    global _language
    if value not in {'en','es'}:
        raise ValueError('Unsupported language: '+str(value))
    if persist:
        update_settings({'language':value}, path)
    _language = value


def tr(message, **values):
    template = SPANISH.get(message, message) if _language == 'es' else message
    return template.format(**values) if values else template


def remember(target, kind, message, values):
    # tkinter.Variable implements equality and is unhashable, so it cannot
    # be a WeakKeyDictionary key. Keep weak references indexed by identity.
    key = id(target)
    _bindings[key] = (ref(target, lambda _: _bindings.pop(key, None)), kind, message, values)


def localize(widget, message, values=None, **options):
    values = values or {}
    widget.configure(text=tr(message, **values), **options)
    remember(widget, 'widget', message, values)
    return widget


def set_text(variable, message, **values):
    variable.set(tr(message, **values))
    remember(variable, 'variable', message, values)


def localize_title(window, message, **values):
    window.title(tr(message, **values))
    remember(window, 'title', message, values)


def localize_heading(tree, column, message, **values):
    tree.heading(column, text=tr(message, **values))
    _headings.setdefault(tree, {})[column] = (message, values)


def refresh_translations():
    # Weakref cleanup can remove bindings during GC while building a list of items.
    for key, (reference, kind, message, values) in _bindings.copy().items():
        target = reference()
        if target is None:
            _bindings.pop(key, None)
            continue
        try:
            text = tr(message, **values)
            if kind == 'variable':
                target.set(text)
            elif target.winfo_exists():
                target.title(text) if kind == 'title' else target.configure(text=text)
        except Exception:
            # Destroyed Tk objects can outlive their widgets in Python.
            _bindings.pop(key, None)
    for tree, columns in list(_headings.items()):
        try:
            if tree.winfo_exists():
                for column, (message, values) in columns.items():
                    tree.heading(column, text=tr(message, **values))
        except Exception:
            _headings.pop(tree, None)
