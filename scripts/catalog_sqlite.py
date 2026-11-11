"""Version 2 relational SQLite catalog codec, compatible with the verified trial.

Native record columns and shared text/list/map tables preserve every JSON value.
This module belongs to the standalone editor and has no workspace dependencies.
"""
import json
from i18n import tr
from pathlib import Path
import sqlite3
import tempfile

BLOCK = 1 << 32
NULL, BOOL, INT, FLOAT, TEXT, RECORD, LIST, MAP = range(8)
TYPE_NAMES = ('null', 'boolean', 'integer', 'real', 'text', 'record', 'list', 'map')


def quote(value):
    return '"'+value.replace('"', '""')+'"'


def kind(value):
    return {type(None): NULL, bool: BOOL, int: INT, float: FLOAT,
            str: TEXT, dict: RECORD, list: LIST}[type(value)]


class RelationalCatalog:
    def __init__(self, db):
        self.db = db
        self.texts = {}
        self.schemas = {}
        self.rows = {}
        self.lists = {}
        self.maps = {}
        db.executescript('''
            PRAGMA foreign_keys=ON;
            PRAGMA user_version=2;
            CREATE TABLE texts(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE record_schemas(id INTEGER PRIMARY KEY, table_name TEXT NOT NULL, entity TEXT NOT NULL);
            CREATE TABLE record_columns(schema_id INTEGER REFERENCES record_schemas(id),
                position INTEGER, name TEXT, value_type TEXT,
                PRIMARY KEY(schema_id,position)) WITHOUT ROWID;
            CREATE TABLE lists(id INTEGER PRIMARY KEY,length INTEGER NOT NULL);
            CREATE TABLE list_items(list_id INTEGER REFERENCES lists(id),position INTEGER,
                value_type INTEGER NOT NULL,value,
                PRIMARY KEY(list_id,position)) WITHOUT ROWID;
            CREATE TABLE maps(id INTEGER PRIMARY KEY,length INTEGER NOT NULL);
            CREATE TABLE map_items(map_id INTEGER REFERENCES maps(id),key_id INTEGER REFERENCES texts(id),
                value_type INTEGER NOT NULL,value,
                PRIMARY KEY(map_id,key_id)) WITHOUT ROWID;
            CREATE TABLE catalog_root(id INTEGER PRIMARY KEY CHECK(id=1),record_id INTEGER NOT NULL);
        ''')

    def text(self, value):
        result = self.texts.get(value)
        if result is None:
            result = len(self.texts)+1
            self.texts[value] = result
            self.db.execute('INSERT INTO texts VALUES (?,?)', (result, value))
        return result

    def encode(self, value, entity='catalog'):
        tag = kind(value)
        if tag == TEXT:
            return tag, self.text(value)
        if tag == BOOL:
            return tag, int(value)
        if tag in {NULL, INT, FLOAT}:
            return tag, value
        if tag == LIST:
            items = tuple(self.encode(item, entity) for item in value)
            if items not in self.lists:
                index = len(self.lists)+1
                self.lists[items] = index
                self.db.execute('INSERT INTO lists VALUES (?,?)', (index, len(items)))
                self.db.executemany('INSERT INTO list_items VALUES (?,?,?,?)',
                    ((index, i, tag, item) for i, (tag, item) in enumerate(items)))
            return LIST, self.lists[items]
        is_map = entity in {'games', 'images', 'metadata', 'fields', 'labels',
                           'descriptions', 'short_descriptions', 'qualifiers',
                           'snaks', 'references', 'metadata_sources'} or len(value) > 64
        if is_map:
            items = tuple(sorted((self.text(k), *self.encode(v, self.member_entity(entity, k)))
                                 for k, v in value.items()))
            if items not in self.maps:
                index = len(self.maps)+1
                self.maps[items] = index
                self.db.execute('INSERT INTO maps VALUES (?,?)', (index, len(items)))
                self.db.executemany('INSERT INTO map_items VALUES (?,?,?,?)',
                    ((index, *item) for item in items))
            return MAP, self.maps[items]
        columns = tuple(sorted(value))
        encoded = tuple(self.encode(value[key], self.member_entity(entity, key)) for key in columns)
        # Record shape, value types and entity determine actual SQL columns.
        schema = (entity, tuple(zip(columns, (tag for tag, _ in encoded))))
        if schema not in self.schemas:
            index = len(self.schemas)+1
            table = 'record_'+str(index)+'_'+''.join(c if c.isalnum() else '_' for c in entity)[:32]
            declarations = []
            for key, (tag, _) in zip(columns, encoded):
                sqltype = 'TEXT' if tag == NULL else 'REAL' if tag == FLOAT else 'INTEGER'
                # All text columns reference one deduplicated text dictionary.
                declaration = quote(key)+' '+sqltype
                if tag == TEXT:
                    declaration += ' REFERENCES texts(id)'
                declarations.append(declaration)
            self.db.execute('INSERT INTO record_schemas VALUES (?,?,?)', (index, table, entity))
            self.db.executemany('INSERT INTO record_columns VALUES (?,?,?,?)',
                ((index, i, key, TYPE_NAMES[tag]) for i, (key, (tag, _)) in enumerate(zip(columns, encoded))))
            self.db.execute('CREATE TABLE '+quote(table)+' (_row_id INTEGER PRIMARY KEY'+
                            (','+','.join(declarations) if declarations else '')+')')
            self.schemas[schema] = (index, table)
            self.rows[index] = {}
        index, table = self.schemas[schema]
        values = tuple(v for _, v in encoded)
        rows = self.rows[index]
        if values not in rows:
            identifier = index*BLOCK+len(rows)+1
            rows[values] = identifier
            self.db.execute('INSERT INTO '+quote(table)+' VALUES ('+','.join('?' for _ in range(len(values)+1))+')',
                            (identifier, *values))
        return RECORD, rows[values]

    @staticmethod
    def member_entity(parent, key):
        mapping = {'games': 'game', 'images': 'image', 'metadata': 'metadata_record',
                   'fields': 'metadata_statement', 'labels': 'language_label',
                   'descriptions': 'description', 'short_descriptions': 'short_description',
                   'metadata_sources': 'metadata_source', 'sources': 'source',
                   'entries': 'release', 'serial_identifiers': 'serial_identifier',
                   'qualifiers': 'qualifier', 'snaks': 'snak'}
        return mapping.get(parent, key)

    def finish(self, catalog):
        tag, root = self.encode(catalog)
        assert tag == RECORD
        self.db.execute('INSERT INTO catalog_root VALUES (1,?)', (root,))
        # Practical indexes: enumerate games and images without walking folders.
        self.db.execute('CREATE TABLE game_index(serial_id INTEGER PRIMARY KEY REFERENCES texts(id),record_id INTEGER NOT NULL)')
        self.db.execute('CREATE TABLE image_index(serial_id INTEGER REFERENCES texts(id),label_id INTEGER REFERENCES texts(id),record_id INTEGER NOT NULL,PRIMARY KEY(serial_id,label_id)) WITHOUT ROWID')
        for serial, game in catalog['games'].items():
            self.db.execute('INSERT INTO game_index VALUES (?,?)', (self.text(serial), self.encode(game, 'game')[1]))
            self.db.executemany('INSERT INTO image_index VALUES (?,?,?)',
                ((self.text(serial), self.text(label), self.encode(asset, 'image')[1]) for label, asset in game['images'].items()))
        self.db.execute('CREATE VIEW games AS SELECT t.value AS serial,g.record_id FROM game_index g JOIN texts t ON t.id=g.serial_id')
        self.db.execute('CREATE VIEW images AS SELECT s.value AS serial,l.value AS label,i.record_id FROM image_index i JOIN texts s ON s.id=i.serial_id JOIN texts l ON l.id=i.label_id')


def restore(db):
    texts = dict(db.execute('SELECT id,value FROM texts'))
    schemas = {}
    for index, table in db.execute('SELECT id,table_name FROM record_schemas'):
        columns = list(db.execute('SELECT name,value_type FROM record_columns WHERE schema_id=? ORDER BY position', (index,)))
        names = ','.join(quote(name) for name, _ in columns)
        rows = {row[0]: row[1:] for row in db.execute('SELECT _row_id'+(','+names if names else '')+' FROM '+quote(table))}
        schemas[index] = (columns, rows)
    lists = {}
    for index, position, tag, value in db.execute('SELECT list_id,position,value_type,value FROM list_items ORDER BY list_id,position'):
        lists.setdefault(index, []).append((tag, value))
    maps = {}
    for index, key, tag, value in db.execute('SELECT map_id,key_id,value_type,value FROM map_items'):
        maps.setdefault(index, []).append((key, tag, value))

    def decode(tag, value):
        if tag == TEXT:
            return texts[value]
        if tag == BOOL:
            return bool(value)
        if tag in {NULL, INT, FLOAT}:
            return value
        if tag == LIST:
            return [decode(t, v) for t, v in lists.get(value, [])]
        if tag == MAP:
            return {texts[key]: decode(t, v) for key, t, v in maps.get(value, [])}
        columns, rows = schemas[value//BLOCK]
        return {key: decode(TYPE_NAMES.index(t), v) for (key, t), v in zip(columns, rows[value])}

    return decode(RECORD, db.execute('SELECT record_id FROM catalog_root').fetchone()[0])


SQLITE_HEADER = b'SQLite format 3\x00'


def _connect_bytes(raw):
    db = sqlite3.connect(':memory:')
    if hasattr(db, 'deserialize'):
        try:
            db.deserialize(raw)
        except BaseException:
            db.close()
            raise
        return db, None
    db.close()
    # Python 3.10 does not expose Connection.deserialize/serialize.
    temporary = tempfile.TemporaryDirectory(prefix='opencabinet-catalog-')
    try:
        path = Path(temporary.name)/'catalog.sqlite'
        path.write_bytes(raw)
        return sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True), temporary
    except BaseException:
        temporary.cleanup()
        raise


def loads(raw):
    if not raw.startswith(SQLITE_HEADER):
        raise ValueError(tr('Invalid SQLite catalog header'))
    try:
        db, temporary = _connect_bytes(raw)
    except sqlite3.Error as error:
        raise ValueError(tr('Invalid SQLite catalog structure')) from error
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA user_version').fetchone()[0] != 2:
            raise ValueError(tr('Unsupported SQLite catalog version'))
        result = restore(db)
        if not isinstance(result, dict) or not isinstance(result.get('games'), dict):
            raise ValueError(tr('Invalid SQLite catalog structure'))
        return result
    except (sqlite3.Error, KeyError, TypeError, IndexError, RecursionError) as error:
        raise ValueError(tr('Invalid SQLite catalog structure')) from error
    finally:
        db.close()
        if temporary is not None:
            temporary.cleanup()


def dumps(catalog):
    # Regenerate a compact snapshot before replacing the live file atomically.
    # Existing editor journals can back up and undo the exact binary snapshot.
    with tempfile.TemporaryDirectory(prefix='opencabinet-catalog-') as directory:
        path = Path(directory)/'catalog.sqlite'
        db = sqlite3.connect(path)
        try:
            model = RelationalCatalog(db)
            with db:
                model.finish(catalog)
            del model
            db.execute('VACUUM')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError(tr('Invalid SQLite catalog structure'))
            if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError(tr('Invalid SQLite catalog references'))
        finally:
            db.close()
        return path.read_bytes()
