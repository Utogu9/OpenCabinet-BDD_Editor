"""Exercise the real Tk UI without touching the user's generated library."""
import json
from pathlib import Path
import tempfile
import time
import traceback
import tkinter as tk
from unittest.mock import patch

from PIL import Image
from artwork_editor import Editor
from editor_store import encode_import


def run():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        imported = root/'new.png'
        Image.new('RGBA', (32, 24), (15, 40, 240, 180)).save(imported)
        original = root/'original.png'
        Image.new('RGB', (24, 24), 'red').save(original)
        vector = root/'logo.svg'
        vector.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><rect width="120" height="40" fill="red"/></svg>')
        encoded = encode_import(original)
        from pdf_tools import pdf_api
        _, PdfWriter = pdf_api()
        manual_pdf = root/'manual.pdf'
        pdf = PdfWriter()
        pdf.add_blank_page(width=200, height=300)
        pdf.write(manual_pdf)
        from dat_catalog import DatCache
        dat_cache = DatCache(root/'test-dat-cache')
        dat_cache.import_bytes('Sony - PlayStation','redump',
            b'<datafile><header><name>Sony - PlayStation</name></header>'
            b'<game id="999" name="New Game (USA)"><serial>SLUS-99999</serial></game></datafile>')
        output = root/'generated/Test Console'
        folder = output/'TEST-1'
        folder.mkdir(parents=True)
        (folder/'cover_front.webp').write_bytes(encoded['data'])
        asset = {key: encoded[key] for key in ('sha256', 'bytes', 'width', 'height', 'alpha', 'compression')}
        asset.update({'kind':'cover_front', 'path':'TEST-1/cover_front.webp', 'sources':[]})
        (output/'catalog.json').write_text(json.dumps({'schema_version':2, 'system':'Test Console',
            'status':'complete', 'games':{'TEST-1':{'serial':'TEST-1', 'entries':[{'name':'Example (USA)'}],
                                                 'images':{'cover_front':asset}}}}))
        config = root/'editor-setting.json'
        config.write_text(json.dumps({'library':str(root/'generated'),'keep_preference':'unchanged'}))
        window = tk.Tk()
        window.withdraw()
        editor = Editor(window, root)
        failures = []
        window.report_callback_exception = lambda typ, value, tb: failures.append(''.join(traceback.format_exception(typ, value, tb)))
        stage, started = 0, time.monotonic()
        dialog = None
        def tick():
            nonlocal stage, dialog
            try:
                if failures:
                    raise AssertionError('; '.join(failures))
                if time.monotonic()-started > 45:
                    raise AssertionError(f'Timeout at UI stage {stage}')
                if stage == 0 and editor.serial == 'TEST-1':
                    assert editor.can_edit()
                    assert editor.title.cget('text') == 'Example (USA)'
                    assert editor.language_button.cget('text') == 'ES'
                    assert editor.add_button.cget('text') == 'Import image'
                    editor.query.set('EXAMPLE usa')
                    editor.toggle_language()
                    assert editor.language_button.cget('text') == 'EN'
                    assert editor.add_button.cget('text') == 'Importar imagen'
                    assert editor.serial == 'TEST-1' and editor.query.get() == 'EXAMPLE usa'
                    assert editor.title.cget('text') == 'Example (USA)'
                    assert json.loads(config.read_text())['language'] == 'es'
                    editor.toggle_language()
                    assert editor.language_button.cget('text') == 'ES'
                    assert editor.add_button.cget('text') == 'Import image'
                    assert json.loads(config.read_text())['library'] == str(root/'generated')
                    stage = 1
                elif stage == 1 and editor.filter_timer is None:
                    assert len(editor.rows) == 1
                    editor.import_image('cover_front', 'cover_front')
                    stage = 2
                elif stage == 2 and not editor.busy:
                    assert editor.catalog['games']['TEST-1']['images']['cover_front']['manual']
                    editor.view_image(folder/'cover_front.webp')
                    viewer = next(widget for widget in window.winfo_children() if isinstance(widget, tk.Toplevel))
                    editor.toggle_language()
                    assert viewer.title().endswith('vista de píxeles')
                    editor.toggle_language()
                    assert viewer.title().endswith('pixel view')
                    for widget in window.winfo_children():
                        if isinstance(widget, tk.Toplevel):
                            widget.withdraw()
                    editor.undo()
                    stage = 3
                elif stage == 3 and not editor.busy:
                    assert (folder/'cover_front.webp').read_bytes() == encoded['data']
                    editor.kind.set('cover_front')
                    editor.import_kind()
                    stage = 31
                elif stage == 31 and not editor.busy:
                    assert (folder/'cover_front2.webp').exists()
                    assert (folder/'cover_front.webp').read_bytes() == encoded['data']
                    assert editor.catalog['games']['TEST-1']['images']['cover_front2']['kind'] == 'cover_front'
                    comparison = editor.compare_images('cover_front')
                    assert comparison.choices[0].get() == 'cover_front'
                    assert comparison.choices[1].get() == 'cover_front2'
                    comparison.zoom(4)
                    comparison.draw()
                    assert comparison.scale == 4 and all(comparison.photos)
                    assert 'KiB' in comparison.details[0].cget('text')
                    comparison.close()
                    editor.artwork_action('cover_front2', 'primary')
                    stage = 311
                elif stage == 311 and not editor.busy:
                    assert (folder/'cover_front2.webp').read_bytes() == encoded['data']
                    assert (folder/'cover_front.webp').read_bytes() == encode_import(imported)['data']
                    editor.artwork_action('cover_front2', 'delete')
                    stage = 312
                elif stage == 312 and not editor.busy:
                    assert not (folder/'cover_front2.webp').exists()
                    assert 'cover_front2' not in editor.catalog['games']['TEST-1']['images']
                    editor.undo()
                    stage = 313
                elif stage == 313 and not editor.busy:
                    assert (folder/'cover_front2.webp').read_bytes() == encoded['data']
                    editor.undo()
                    stage = 314
                elif stage == 314 and not editor.busy:
                    assert (folder/'cover_front.webp').read_bytes() == encoded['data']
                    editor.undo()
                    stage = 32
                elif stage == 32 and not editor.busy:
                    assert not (folder/'cover_front2.webp').exists()
                    editor.kind.set('disc')
                    editor.import_kind()
                    stage = 4
                elif stage == 4 and not editor.busy:
                    assert (folder/'disc.webp').exists()
                    editor.reset('disc')
                    stage = 5
                elif stage == 5 and not editor.busy:
                    assert not (folder/'disc.webp').exists()
                    editor.kind.set('manual')
                    editor.import_kind()
                    stage = 6
                elif stage == 6 and not editor.busy:
                    assert (folder/'manual.pdf').exists()
                    assert editor.catalog['games']['TEST-1']['images']['manual']['format'] == 'PDF'
                    editor.open_pdf(folder/'manual.pdf')
                    editor.undo()
                    stage = 7
                elif stage == 7 and not editor.busy:
                    assert not (folder/'manual.pdf').exists()
                    editor.console_filter.set('NO-SUCH-CONSOLE')
                    stage = 8
                elif stage == 8:
                    assert editor.serial is None and not editor.tree.get_children()
                    assert not editor.can_edit()
                    editor.console_filter.set('Test Console')
                    stage = 9
                elif stage == 9 and editor.serial == 'TEST-1':
                    lock = root/'reports/batch.lock'
                    lock.write_text('{"pid":123}')
                    editor.update_buttons()
                    assert not editor.can_edit()
                    assert str(editor.add_button['state']) == 'disabled'
                    lock.unlink()
                    assert editor.can_edit()
                    editor.show_console()
                    stage = 10
                elif stage == 10 and editor.console_mode and editor.action_buttons:
                    editor.kind.set('render')
                    editor.import_kind()
                    stage = 11
                elif stage == 11 and not editor.busy:
                    assert (output/'render.webp').exists()
                    assert not (folder/'render.webp').exists()
                    assert 'render' not in editor.catalog['games']['TEST-1']['images']
                    editor.undo()
                    stage = 12
                elif stage == 12 and not editor.busy:
                    assert not (output/'render.webp').exists()
                    with patch('artwork_editor.filedialog.askopenfilename', return_value=str(vector)):
                        editor.import_image('logo', 'logo')
                    stage = 121
                elif stage == 121 and not editor.busy:
                    assert (output/'logo.svg').read_bytes() == vector.read_bytes()
                    assert not (output/'logo.webp').exists()
                    editor.view_image(output/'logo.svg')
                    viewer = next(w for w in window.winfo_children() if isinstance(w, tk.Toplevel) and 'SVG' in w.title())
                    viewer.withdraw()
                    editor.kind.set('logo')
                    editor.import_kind()
                    stage = 125
                elif stage == 125 and not editor.busy:
                    assert (output/'logo.svg').read_bytes() == vector.read_bytes()
                    assert (output/'logo2.webp').exists()
                    assert set(editor.console_store.images(output)) == {'logo', 'logo2'}
                    replacement = root/'second-logo.svg'
                    replacement.write_bytes(vector.read_bytes().replace(b'red', b'blue'))
                    with patch('artwork_editor.filedialog.askopenfilename', return_value=str(replacement)):
                        editor.import_image('logo', 'logo2')
                    stage = 126
                elif stage == 126 and not editor.busy and editor.current_images.get('logo2', {}).get('path') == 'logo2.svg':
                    assert (output/'logo2.svg').exists()
                    assert not (output/'logo2.webp').exists()
                    assert (output/'logo.svg').read_bytes() == vector.read_bytes()
                    comparison = editor.compare_images('logo')
                    comparison.zoom(2)
                    assert all(record['format'] == 'SVG' for record in comparison.records)
                    comparison.close()
                    editor.artwork_action('logo2', 'primary')
                    stage = 1261
                elif stage == 1261 and not editor.busy and 'logo' in editor.current_images:
                    assert b'blue' in (output/'logo.svg').read_bytes()
                    assert (output/'logo2.svg').read_bytes() == vector.read_bytes()
                    editor.artwork_action('logo', 'delete')
                    stage = 1262
                elif stage == 1262 and not editor.busy:
                    assert not (output/'logo.svg').exists()
                    editor.undo()
                    stage = 1263
                elif stage == 1263 and not editor.busy:
                    assert b'blue' in (output/'logo.svg').read_bytes()
                    editor.undo()
                    stage = 1264
                elif stage == 1264 and not editor.busy:
                    assert (output/'logo.svg').read_bytes() == vector.read_bytes()
                    editor.reset('logo2')
                    stage = 127
                elif stage == 127 and not editor.busy:
                    assert (output/'logo2.webp').exists()
                    assert not (output/'logo2.svg').exists()
                    editor.undo()
                    stage = 128
                elif stage == 128 and not editor.busy:
                    assert not (output/'logo2.webp').exists()
                    assert (output/'logo.svg').read_bytes() == vector.read_bytes()
                    editor.import_image('logo', 'logo')
                    stage = 122
                elif stage == 122 and not editor.busy:
                    assert (output/'logo.webp').exists()
                    assert not (output/'logo.svg').exists()
                    editor.undo()
                    stage = 123
                elif stage == 123 and not editor.busy:
                    assert (output/'logo.svg').read_bytes() == vector.read_bytes()
                    assert not (output/'logo.webp').exists()
                    editor.undo()
                    stage = 124
                elif stage == 124 and not editor.busy:
                    assert not (output/'logo.svg').exists()
                    from game_dialog import AddGameDialog
                    dialog = AddGameDialog(editor,dat_cache)
                    dialog.window.withdraw()
                    stage = 13
                elif stage == 13 and not dialog.busy:
                    dialog.system.set('Sony - PlayStation')
                    dialog.change_system()
                    stage = 14
                elif stage == 14 and not dialog.busy:
                    assert dialog.catalog is not None
                    dialog.query.set('New Game (USA)')
                    dialog.search()
                    stage = 15
                elif stage == 15 and not dialog.busy:
                    assert dialog.tree.get_children() == ('0',)
                    dialog.tree.selection_set('0')
                    dialog.show_destinations()
                    dialog.create()
                    stage = 16
                elif stage == 16 and not editor.busy and editor.serial == 'SLUS-99999':
                    game = editor.catalog['games']['SLUS-99999']
                    assert game['entries'][0]['name'] == 'New Game (USA)'
                    assert game['editor_added_entries'][0]['dat']['provider'] == 'redump'
                    editor.import_image('cover_front','cover_front')
                    stage = 17
                elif stage == 17 and not editor.busy:
                    assert editor.catalog['games']['SLUS-99999']['images']['cover_front']['manual']
                    editor.undo()
                    stage = 18
                elif stage == 18 and not editor.busy:
                    assert not editor.catalog['games']['SLUS-99999']['images']
                    editor.undo_game()
                    stage = 19
                elif stage == 19 and not editor.busy and 'SLUS-99999' not in (editor.catalog or {}).get('games',{}):
                    assert not (root/'generated/Sony - PlayStation/SLUS-99999').exists()
                    editor.toggle_language()
                    assert editor.language_button.cget('text') == 'EN'
                    editor.close()
                    return
            except Exception:
                failures.append(f'Stage {stage}:\n' + traceback.format_exc())
                editor.closed = True
                editor.pool.shutdown(wait=True, cancel_futures=True)
                window.destroy()
                return
            window.after(70, tick)
        with patch('artwork_editor.filedialog.askopenfilename', side_effect=lambda **k:
                   str(manual_pdf) if k['filetypes'][0][1] == '*.pdf' else str(imported)), \
             patch('artwork_editor.os.startfile', create=True) as open_pdf, \
             patch('artwork_editor.messagebox.showerror', side_effect=lambda *a, **k: failures.append(str(a))), \
             patch('artwork_editor.messagebox.showinfo'), \
             patch('game_dialog.messagebox.askyesno',return_value=True):
            window.after(100, tick)
            window.mainloop()
            if failures:
                raise AssertionError('\n'.join(failures))
            assert open_pdf.call_count == 1
        if failures:
            raise AssertionError('\n'.join(failures))
        restarted_window = tk.Tk()
        restarted_window.withdraw()
        restarted = Editor(restarted_window, root)
        assert restarted.language_button.cget('text') == 'EN'
        assert restarted.new_game_button.cget('text') == 'Agregar juego desde DAT'
        assert json.loads(config.read_text())['keep_preference'] == 'unchanged'
        restarted.close()
        restarted.pool.shutdown(wait=True, cancel_futures=True)
        from i18n import set_language
        set_language('en', persist=False)
        from check_metadata_editor import run as check_metadata
        check_metadata()
        print(json.dumps({'desktop_ui':'passed', 'search':True, 'replace':True, 'pixel_view':True,
                          'undo':True, 'add_type':True, 'restore':True, 'console_filter':True,
                          'batch_lock':True, 'pdf_import_open_undo':True, 'console_root_artwork':True,
                          'production_data_modified':False, 'add_game_from_dat':True,
                          'new_game_image_and_undo':True, 'undo_game_registration':True,
                          'english_default':True, 'live_language_switch':True, 'saved_language_restart':True,
                          'svg_logo_import_preview_replace_undo':True,
                          'game_and_console_import_variants':True,
                          'delete_primary_compare_and_undo':True}))
        return 0


if __name__ == '__main__':
    raise SystemExit(run())
