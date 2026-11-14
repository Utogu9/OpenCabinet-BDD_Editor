"""Console-scoped imports with a legacy batch.lock marker for older editors."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

OWNER = 'console-imports-v1'


def read(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix='.tmp') as handle:
        temporary = Path(handle.name)
        handle.write((json.dumps(value, ensure_ascii=False)+'\n').encode('utf-8'))
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def gate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'.gate'
    for attempt in range(100):
        try:
            handle = path.open('x', encoding='utf-8')
            break
        except FileExistsError:
            if attempt == 99:
                raise ValueError('Import lock manager is busy; retry shortly. Do not remove active locks.')
            time.sleep(0.05)
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def marker(session, records):
    return {'owner': OWNER, 'session': session, 'pid': records[0]['pid'],
            'pids': sorted({record['pid'] for record in records}),
            'consoles': [record['console'] for record in records]}


@contextmanager
def console_writer(store, output):
    output = store.output(output)
    reports = store.root/'reports'
    directory = reports/'console-locks'
    batch = reports/'batch.lock'
    name = hashlib.sha256(str(output).casefold().encode('utf-8')).hexdigest()+'.lock'
    scope = directory/name
    token = uuid.uuid4().hex
    with gate(directory):
        locks = sorted(directory.glob('*.lock'))
        current = read(batch) if batch.exists() else None
        if current is not None and (current.get('owner') != OWNER or not current.get('session')):
            raise ValueError('The library is in use by the editor, Run-Library or an older importer. Wait for it to finish.')
        if scope.exists():
            raise ValueError('This console already has an active import: '+output.name)
        if current is None and locks:
            raise ValueError('Inconsistent import locks; review them before continuing.')
        records = [read(path) for path in locks]
        if current and any(record.get('session') != current['session'] for record in records):
            raise ValueError('Inconsistent import lock sessions; review them before continuing.')
        session = current['session'] if current else uuid.uuid4().hex
        record = {'pid': os.getpid(), 'console': output.name, 'output': str(output),
                  'session': session, 'token': token, 'started_at': time.time()}
        created_batch = False
        try:
            if current is None:
                # Exclusive create also arbitrates against unmodified editors.
                try:
                    with batch.open('x', encoding='utf-8') as handle:
                        handle.write(json.dumps(marker(session, [record])))
                    created_batch = True
                except FileExistsError:
                    raise ValueError('The library became busy; retry after the other writer finishes.')
            with scope.open('x', encoding='utf-8') as handle:
                handle.write(json.dumps(record))
            write(batch, marker(session, records+[record]))
        except BaseException:
            if read(scope).get('token') == token:
                scope.unlink(missing_ok=True)
            if created_batch and read(batch).get('session') == session:
                batch.unlink(missing_ok=True)
            raise
    try:
        yield
    finally:
        with gate(directory):
            # Never release a lock which another process has replaced.
            if read(scope).get('token') != token:
                raise ValueError('Import lock changed outside the importer; review locks before continuing.')
            scope.unlink()
            current = read(batch)
            if current.get('owner') != OWNER or current.get('session') != session:
                raise ValueError('Library lock changed outside the importer; review locks before continuing.')
            records = [read(path) for path in sorted(directory.glob('*.lock'))]
            if records:
                write(batch, marker(session, records))
            else:
                batch.unlink()
