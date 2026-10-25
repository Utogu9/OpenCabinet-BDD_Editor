"""Exercise game/console metadata forms using an isolated temporary library."""
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from artwork_editor import Editor
from editor_common import write_json
from metadata_store import effective_metadata, format_field


def run():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        output = root / 'generated' / 'Test Console'
        output.mkdir(parents=True)
        original = {'wikidata_id': 'Q123', 'license': 'CC0-1.0',
                    'fields': {'developer': [{'value': {'id': 'Q456'}, 'labels': {'en': 'Original Studio'},
                                             'qualifiers': {'keep': True}, 'references': [{'keep': True}]}]},
                    'short_descriptions': {'en': 'A game'}}
        write_json(output / 'catalog.json', {'schema_version': 2, 'status': 'complete', 'system': 'Test Console',
            'games': {serial: {'serial': serial, 'entries': [{'name': 'Game (' + region + ')'}], 'images': {},
                               'metadata_id': 'wikidata:Q123'} for serial, region in [('ID-USA', 'USA'), ('ID-EU', 'Europe')]},
            'metadata': {'wikidata:Q123': original}})
        config = root / 'editor-setting.json'
        write_json(config, {'language': 'en'})
        window = tk.Tk()
        window.withdraw()
        editor = Editor(window, root)
        failures = []
        window.report_callback_exception = lambda typ, value, tb: failures.append(str(value))
        stage, started, dialog = 0, time.monotonic(), None

        def edit(path, value):
            control = dialog.controls[path]
            control['active'].set(True)
            dialog.toggle(path)
            control['text'].delete('1.0', 'end')
            control['text'].insert('1.0', value)

        def read():
            return json.loads((output / 'catalog.json').read_text(encoding='utf-8'))

        def tick():
            nonlocal stage, dialog
            try:
                if failures:
                    raise AssertionError('; '.join(failures))
                if time.monotonic() - started > 45:
                    raise AssertionError('Metadata UI timeout at stage ' + str(stage))
                if stage == 0 and editor.serial:
                    editor.serial = 'ID-USA'
                    item = next(item for item, serial in editor.rows.items() if serial == 'ID-USA')
                    editor.tree.selection_set(item)
                    editor.select_game()
                    dialog = editor.edit_metadata()
                    stage = 1
                elif stage == 1 and not dialog.busy:
                    assert dialog.controls[('fields', 'developer')]['text'].get('1.0', 'end-1c') == 'Original Studio'
                    assert str(dialog.undo_button.cget('state')) == 'disabled'
                    edit(('fields', 'developer'), 'My Studio')
                    edit(('descriptions', 'en'), 'My complete description')
                    dialog.save()
                    stage = 2
                elif stage == 2 and not dialog.busy:
                    data = read()
                    assert data['metadata']['wikidata:Q123'] == original
                    assert 'metadata_overrides' not in data['games']['ID-EU']
                    assert data['games']['ID-USA']['metadata_overrides']['descriptions']['en'] == 'My complete description'
                    dialog.close()
                    editor.show_console()
                    dialog = editor.edit_metadata()
                    stage = 3
                elif stage == 3 and not dialog.busy:
                    assert set(key for group, key in dialog.controls if group == 'fields') == {'release_date', 'developer', 'manufacturer'}
                    edit(('fields', 'release_date'), '1994-12-03')
                    edit(('fields', 'developer'), 'Sony')
                    edit(('fields', 'manufacturer'), 'Sony')
                    dialog.save()
                    stage = 4
                elif stage == 4 and not dialog.busy:
                    data = read()
                    assert format_field(data['console_metadata']['fields']['release_date']) == '1994-12-03'
                    assert format_field(data['console_metadata']['fields']['manufacturer']) == 'Sony'
                    assert data['games']['ID-USA']['metadata_overrides']['descriptions']['en'] == 'My complete description'
                    dialog.undo()
                    stage = 5
                elif stage == 5 and not dialog.busy:
                    assert 'console_metadata' not in read()
                    dialog.close()
                    item = next(item for item, serial in editor.rows.items() if serial == 'ID-USA')
                    editor.tree.selection_set(item)
                    editor.select_game()
                    dialog = editor.edit_metadata()
                    stage = 6
                elif stage == 6 and not dialog.busy:
                    dialog.controls[('fields', 'developer')]['active'].set(False)
                    dialog.toggle(('fields', 'developer'))
                    dialog.save()
                    stage = 7
                elif stage == 7 and not dialog.busy:
                    data = read()
                    merged = effective_metadata(original, data['games']['ID-USA']['metadata_overrides'])
                    assert format_field(merged['fields']['developer']) == 'Original Studio'
                    assert merged['descriptions']['en'] == 'My complete description'
                    dialog.undo()
                    stage = 8
                elif stage == 8 and not dialog.busy:
                    assert format_field(read()['games']['ID-USA']['metadata_overrides']['fields']['developer']) == 'My Studio'
                    dialog.close()
                    editor.toggle_language()
                    dialog = editor.edit_metadata()
                    stage = 9
                elif stage == 9 and not dialog.busy:
                    assert dialog.save_button.cget('text') == 'Guardar metadatos'
                    assert dialog.window.title() == 'Metadatos del juego'
                    assert read()['metadata']['wikidata:Q123'] == original
                    dialog.close()
                    editor.close()
                    return
            except Exception as error:
                import traceback
                failures.append('Metadata UI stage ' + str(stage) + ': ' + traceback.format_exc())
                editor.closed = True
                editor.pool.shutdown(wait=True, cancel_futures=True)
                window.destroy()
                return
            window.after(60, tick)

        with patch('metadata_dialog.messagebox.showerror', side_effect=lambda *a, **k: failures.append(str(a))), \
             patch('metadata_dialog.messagebox.askyesno', return_value=True):
            window.after(100, tick)
            window.mainloop()
        editor.pool.shutdown(wait=True, cancel_futures=True)
        if failures:
            raise AssertionError('\n'.join(failures))
        from i18n import set_language
        set_language('en', persist=False)
        print(json.dumps({'metadata_ui': 'passed', 'game_overrides': True, 'console_metadata': True,
                          'shared_source_preserved': True, 'restore_inheritance': True,
                          'metadata_undo': True, 'spanish_metadata_ui': True, 'production_data_modified': False}))


if __name__ == '__main__':
    run()
