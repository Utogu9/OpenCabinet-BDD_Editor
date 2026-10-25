"""Per-game metadata overrides and console metadata, with reversible saves."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import re

from editor_common import digest
from editor_store import inside, json_bytes, stamp
from game_registration import GameRegistration
from i18n import tr

GAME_FIELDS = {
    'developer': 'Developer', 'publisher': 'Publisher', 'genre': 'Genre',
    'min_players': 'Minimum players', 'max_players': 'Maximum players',
    'game_mode': 'Game mode', 'release_date': 'Release date', 'platform': 'Platform',
}
CONSOLE_FIELDS = {
    'release_date': 'Release date', 'developer': 'Developer', 'manufacturer': 'Manufacturer',
}


def effective_metadata(shared, overrides):
    """Merge field/language dictionaries; an explicit empty value masks inheritance."""
    result = deepcopy(shared)
    for key, value in overrides.items():
        if key in {'fields', 'labels', 'short_descriptions', 'descriptions'} and isinstance(value, dict):
            result[key] = {**result.get(key, {}), **deepcopy(value)}
        else:
            result[key] = deepcopy(value)
    return result


def statement_text(statement, lang='en'):
    labels = statement.get('labels', {})
    if labels:
        value = labels.get(lang) or labels.get('en') or labels.get('mul') or next(iter(labels.values()))
        return str(value)
    value = statement.get('value', '')
    if not isinstance(value, dict):
        return str(value)
    if 'amount' in value:
        return str(value['amount']).lstrip('+')
    if 'time' in value:
        date = value['time'].lstrip('+').split('T', 1)[0]
        return date[:4] if value.get('precision', 11) <= 9 else date[:7] if value.get('precision') == 10 else date
    return str(value.get('text') or value.get('id') or '')


def format_field(values, lang='en'):
    return '\n'.join(statement_text(value, lang) for value in values)


def parse_field(key, text):
    values = [line.strip() for line in text.splitlines() if line.strip()]
    if key in ('min_players', 'max_players'):
        if len(values) > 1 or (values and not re.fullmatch(r'[1-9][0-9]{0,6}', values[0])):
            raise ValueError(tr('Player counts must be positive whole numbers, or empty.'))
        return [{'value': {'amount': '+' + value, 'unit': '1'}, 'source': 'manual'} for value in values]
    if key == 'release_date':
        from datetime import date
        result = []
        for value in values:
            if not re.fullmatch(r'[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?', value):
                raise ValueError(tr('Use YYYY, YYYY-MM or YYYY-MM-DD for release dates, one per line.'))
            parts = [int(p) for p in value.split('-')]
            try:
                date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
            except ValueError as error:
                raise ValueError(tr('Invalid release date.')) from error
            padded = value + ('-00-00' if len(parts) == 1 else '-00' if len(parts) == 2 else '')
            result.append({'value': {'time': '+' + padded + 'T00:00:00Z', 'precision': len(parts) + 8,
                                     'timezone': 0, 'before': 0, 'after': 0,
                                     'calendarmodel': 'http://www.wikidata.org/entity/Q1985727'}, 'source': 'manual'})
        return result
    return [{'value': value, 'source': 'manual'} for value in values]


def validate(value):
    if not isinstance(value, dict):
        raise ValueError(tr('Metadata must be a JSON object.'))
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 1024 * 1024:
        raise ValueError(tr('Metadata exceeds the 1 MiB limit.'))
    for key in ('labels', 'short_descriptions', 'descriptions'):
        if key in value and (not isinstance(value[key], dict) or
                             any(not isinstance(v, str) for v in value[key].values())):
            raise ValueError(tr('Names and descriptions must contain text by language.'))
    if 'fields' in value:
        if not isinstance(value['fields'], dict) or any(not isinstance(v, list) or
                any(not isinstance(s, dict) or 'value' not in s for s in v) for v in value['fields'].values()):
            raise ValueError(tr('Metadata fields must contain lists of statements with a value.'))
        numbers = {}
        for key in ('min_players', 'max_players'):
            statements = value['fields'].get(key, [])
            if len(statements) == 1 and not statements[0].get('qualifiers'):
                v = statements[0]['value']
                try:
                    numbers[key] = Decimal(v.get('amount')) if isinstance(v, dict) else Decimal(str(v))
                    if not numbers[key].is_finite() or numbers[key] <= 0 or numbers[key] % 1:
                        raise InvalidOperation
                except (InvalidOperation, TypeError):
                    raise ValueError(tr('Player counts must be positive whole numbers, or empty.'))
        if numbers.get('min_players', 0) > numbers.get('max_players', float('inf')):
            raise ValueError(tr('Minimum players cannot exceed maximum players.'))
    if 'custom' in value and not isinstance(value['custom'], dict):
        raise ValueError(tr('Custom metadata must be a JSON object.'))


class MetadataStore(GameRegistration):
    """Reuse the editor's durable journal and base-catalog synchronization."""
    def paths(self, output):
        output = self.store.output(output)
        key = digest(output.relative_to(self.store.generated).as_posix().encode())
        private = inside(self.store.manual / 'metadata-edits' / key, self.store.root)
        return private / 'history.json', private / 'pending.json'

    def _ready(self, output):
        registration = GameRegistration(self.store)
        registration._recover(output)
        self._recover(output)
        return self._views(output)

    def _value(self, catalog, serial):
        if serial is None:
            return catalog.get('console_metadata')
        if serial not in catalog['games']:
            raise ValueError(tr('The selected game is no longer in the catalogue.'))
        return catalog['games'][serial].get('metadata_overrides')

    def _snapshot(self, catalog, serial):
        value = self._value(catalog, serial)
        shared_id = catalog['games'][serial].get('metadata_id') if serial is not None else None
        shared = catalog.get('metadata', {}).get(shared_id, {}) if shared_id else {}
        if not isinstance(shared, dict) or (value is not None and not isinstance(value, dict)):
            raise ValueError(tr('Metadata must be a JSON object.'))
        return {'value': deepcopy(value or {}), 'shared': deepcopy(shared), 'shared_id': shared_id,
                'token': digest(json_bytes([shared_id, shared, value])),
                'linked_games': sum(g.get('metadata_id') == shared_id for g in catalog['games'].values()) if shared_id else 0}

    def snapshot(self, output, serial=None):
        output = self.store.output(output)
        with self.store.writer():
            catalog, _, _ = self._ready(output)
            result = self._snapshot(catalog, serial)
            history, _ = self.paths(output)
            events = json.loads(history.read_text(encoding='utf-8')) if history.exists() else []
            result['can_undo'] = any(event['serial'] == serial for event in events)
            return result

    def _assign(self, catalog, serial, value):
        target, key = (catalog, 'console_metadata') if serial is None else (catalog['games'][serial], 'metadata_overrides')
        if value is None:
            target.pop(key, None)
        else:
            target[key] = deepcopy(value)

    def save(self, output, serial, value, expected):
        output = self.store.output(output)
        validate(value)
        with self.store.writer():
            catalog, base, state = self._ready(output)
            if self._snapshot(catalog, serial)['token'] != expected:
                raise ValueError(tr('Metadata changed while this window was open. Reopen it before saving.'))
            before = self._value(catalog, serial)
            after = value or None
            if (before or None) == after:
                return False
            path, _ = self.paths(output)
            history = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
            history.append({'at': stamp(), 'serial': serial, 'before': deepcopy(before), 'after': deepcopy(after)})
            for view in (catalog, base):
                self._assign(view, serial, after)
            payloads = self._payloads(output, catalog, base, state, history)
            if len(payloads[output / 'catalog.json']) >= 100 * 1024 * 1024:
                raise ValueError(tr('The catalogue would exceed GitHub\'s 100 MiB file limit.'))
            self._commit(output, payloads)
            return True

    def undo(self, output, serial, expected):
        output = self.store.output(output)
        with self.store.writer():
            catalog, base, state = self._ready(output)
            if self._snapshot(catalog, serial)['token'] != expected:
                raise ValueError(tr('Metadata changed while this window was open. Reopen it before saving.'))
            path, _ = self.paths(output)
            history = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
            index = next((i for i in range(len(history) - 1, -1, -1) if history[i]['serial'] == serial), None)
            if index is None:
                raise ValueError(tr('There are no metadata changes to undo for this selection.'))
            event = history[index]
            if self._value(catalog, serial) != event['after']:
                raise ValueError(tr('Metadata changed after this edit; it will not be overwritten.'))
            for view in (catalog, base):
                self._assign(view, serial, event['before'])
            history.pop(index)
            self._commit(output, self._payloads(output, catalog, base, state, history))

