"""Exercise the real Tk UI without touching the user's generated library."""
import json
from pathlib import Path
import tempfile
import time
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
        encoded = encode_import(original)
        from pdf_tools import pdf_api
        _, PdfWriter = pdf_api()
        manual_pdf = root/'manual.pdf'
        pdf = PdfWriter()
        pdf.add_blank_page(width=200, height=300)
        pdf.write(manual_pdf)
        output = root/'generated/Test Console'
        folder = output/'TEST-1'
        folder.mkdir(parents=True)
        (folder/'cover_front.webp').write_bytes(encoded['data'])
        asset = {key: encoded[key] for key in ('sha256', 'bytes', 'width', 'height', 'alpha', 'compression')}
        asset.update({'kind':'cover_front', 'path':'TEST-1/cover_front.webp', 'sources':[]})
        (output/'catalog.json').write_text(json.dumps({'schema_version':2, 'system':'Test Console',
            'status':'complete', 'games':{'TEST-1':{'serial':'TEST-1', 'entries':[{'name':'Example (USA)'}],
                                                 'images':{'cover_front':asset}}}}))
        window = tk.Tk()
        window.withdraw()
        editor = Editor(window, root)
        failures = []
        window.report_callback_exception = lambda typ, value, tb: failures.append(str(value))
        stage, started = 0, time.monotonic()
        def tick():
            nonlocal stage
            try:
                if failures:
                    raise AssertionError('; '.join(failures))
                if time.monotonic()-started > 25:
                    raise AssertionError(f'Timeout at UI stage {stage}')
                if stage == 0 and editor.serial == 'TEST-1':
                    assert editor.can_edit()
                    assert editor.title.cget('text') == 'Example (USA)'
                    editor.query.set('EXAMPLE usa')
                    stage = 1
                elif stage == 1 and editor.filter_timer is None:
                    assert len(editor.rows) == 1
                    editor.import_image('cover_front', 'cover_front')
                    stage = 2
                elif stage == 2 and not editor.busy:
                    assert editor.catalog['games']['TEST-1']['images']['cover_front']['manual']
                    editor.view_image(folder/'cover_front.webp')
                    for widget in window.winfo_children():
                        if isinstance(widget, tk.Toplevel):
                            widget.withdraw()
                    editor.undo()
                    stage = 3
                elif stage == 3 and not editor.busy:
                    assert (folder/'cover_front.webp').read_bytes() == encoded['data']
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
                    editor.close()
                    return
            except Exception as exc:
                failures.append(str(exc))
                editor.closed = True
                editor.pool.shutdown(wait=True, cancel_futures=True)
                window.destroy()
                return
            window.after(70, tick)
        with patch('artwork_editor.filedialog.askopenfilename', side_effect=lambda **k:
                   str(manual_pdf) if k['filetypes'][0][1] == '*.pdf' else str(imported)), \
             patch('artwork_editor.os.startfile', create=True) as open_pdf, \
             patch('artwork_editor.messagebox.showerror', side_effect=lambda *a, **k: failures.append(str(a))), \
             patch('artwork_editor.messagebox.showinfo'):
            window.after(100, tick)
            window.mainloop()
            assert open_pdf.call_count == 1
        if failures:
            raise AssertionError('\n'.join(failures))
        print(json.dumps({'desktop_ui':'passed', 'search':True, 'replace':True, 'pixel_view':True,
                          'undo':True, 'add_type':True, 'restore':True, 'console_filter':True,
                          'batch_lock':True, 'pdf_import_open_undo':True, 'console_root_artwork':True,
                          'production_data_modified':False}))
        return 0


if __name__ == '__main__':
    raise SystemExit(run())
