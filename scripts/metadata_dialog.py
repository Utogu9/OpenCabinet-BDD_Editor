"""Metadata form for one game/serial or the selected console."""
from copy import deepcopy
import json
import tkinter as tk
from tkinter import ttk, messagebox

from i18n import tr, language, localize, localize_title
from metadata_store import GAME_FIELDS, CONSOLE_FIELDS, effective_metadata, format_field, parse_field


class MetadataDialog:
    def __init__(self, editor):
        self.editor = editor
        self.output = editor.current_output
        self.serial = None if editor.console_mode else editor.serial
        self.busy = False
        self.snapshot = None
        self.controls = {}
        self.window = tk.Toplevel(editor.window)
        localize_title(self.window, 'Console metadata' if self.serial is None else 'Game metadata')
        self.window.geometry('950x800')
        self.window.minsize(730, 550)
        self.window.transient(editor.window)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=editor.catalog['system'] if self.serial is None else self.serial,
                  style='Heading.TLabel').pack(anchor='w')
        localize(ttk.Label(frame, wraplength=850), 'Changes apply only to this console.' if self.serial is None else
                 'Changes apply only to this serial. Shared Wikidata records and other editions are preserved.').pack(anchor='w', pady=8)
        self.source = ttk.Label(frame, wraplength=850, style='Muted.TLabel')
        self.source.pack(anchor='w', pady=(0, 8))
        tabs = ttk.Notebook(frame)
        tabs.pack(fill='both', expand=True)
        general = ttk.Frame(tabs)
        descriptions = ttk.Frame(tabs)
        advanced = ttk.Frame(tabs)
        tabs.add(general, text=tr('General'))
        tabs.add(descriptions, text=tr('Descriptions'))
        tabs.add(advanced, text=tr('Custom metadata / source'))
        self.form = self.scroll_frame(general)
        desc_form = self.scroll_frame(descriptions)
        for lang in ('en', 'es'):
            self.add_field(self.form, ('labels', lang), 'Name (English)' if lang == 'en' else 'Name (Spanish)', 1)
        fields = CONSOLE_FIELDS if self.serial is None else GAME_FIELDS
        for key, label in fields.items():
            self.add_field(self.form, ('fields', key), label, 1 if key in ('min_players', 'max_players') else 2)
        localize(ttk.Label(self.form, wraplength=790, style='Muted.TLabel'),
                 'Enter one value per line. Dates: YYYY, YYYY-MM or YYYY-MM-DD.').pack(anchor='w', pady=8)
        for lang in ('en', 'es'):
            self.add_field(desc_form, ('short_descriptions', lang),
                           'Short description (English)' if lang == 'en' else 'Short description (Spanish)', 2)
            self.add_field(desc_form, ('descriptions', lang),
                           'Full description (English)' if lang == 'en' else 'Full description (Spanish)', 6)
        localize(ttk.Label(advanced, wraplength=830),
                 'Optional custom fields as a JSON object. Existing unknown fields are preserved.').pack(anchor='w', pady=8)
        self.custom = tk.Text(advanced, height=8, wrap='word', undo=True)
        self.custom.pack(fill='both', expand=True)
        localize(ttk.Label(advanced), 'Original shared record (read only)').pack(anchor='w', pady=8)
        self.original = tk.Text(advanced, height=10, wrap='none')
        self.original.pack(fill='both', expand=True)
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(12, 0))
        self.undo_button = localize(ttk.Button(actions, command=self.undo), 'Undo metadata change')
        self.undo_button.pack(side='left')
        self.save_button = localize(ttk.Button(actions, style='Accent.TButton', command=self.save), 'Save metadata')
        self.save_button.pack(side='right')
        self.close_button = localize(ttk.Button(actions, command=self.close), 'Close')
        self.close_button.pack(side='right', padx=8)
        self.load()

    def scroll_frame(self, parent):
        canvas = tk.Canvas(parent, bg='#131820', highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas, padding=8)
        item = canvas.create_window(0, 0, window=content, anchor='nw')
        content.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        def wheel(event):
            canvas.yview_scroll(-int(event.delta / 120), 'units')
        canvas.bind('<MouseWheel>', wheel)
        content._metadata_wheel = wheel
        return content

    def add_field(self, parent, path, label, height):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(0, 9))
        header = ttk.Frame(row)
        header.pack(fill='x')
        localize(ttk.Label(header), label).pack(side='left')
        active = tk.BooleanVar(value=False)
        check = localize(ttk.Checkbutton(header, variable=active,
                         command=lambda: self.toggle(path)), 'Custom value')
        check.pack(side='right')
        text = tk.Text(row, height=height, wrap='word', undo=True)
        text.pack(fill='x')
        text.bind('<MouseWheel>', parent._metadata_wheel)
        self.controls[path] = {'active': active, 'text': text, 'check': check}

    def toggle(self, path):
        control = self.controls[path]
        control['text'].configure(state='normal' if control['active'].get() and not self.busy else 'disabled')

    def set_busy(self, value):
        self.busy = self.editor.busy = value
        self.editor.update_buttons()
        for widget in (self.save_button, self.undo_button, self.close_button):
            widget.configure(state='disabled' if value else 'normal')
        if not value and not (self.snapshot or {}).get('can_undo'):
            self.undo_button.configure(state='disabled')
        for path, control in self.controls.items():
            control['check'].configure(state='disabled' if value else 'normal')
            self.toggle(path)
        self.custom.configure(state='disabled' if value else 'normal')

    def load(self):
        self.set_busy(True)
        self.editor.task(lambda: self.editor.metadata_store.snapshot(self.output, self.serial), self.loaded, self.failed)

    def loaded(self, snapshot):
        if not self.window.winfo_exists():
            return
        self.snapshot = snapshot
        effective = effective_metadata(snapshot['shared'], snapshot['value'])
        for path, control in self.controls.items():
            group, key = path
            value = effective.get(group, {}).get(key, [] if group == 'fields' else '')
            display = format_field(value, language()) if group == 'fields' else value
            control['initial'] = display
            control['initial_value'] = deepcopy(value)
            control['active'].set(key in snapshot['value'].get(group, {}))
            control['text'].configure(state='normal')
            control['text'].delete('1.0', 'end')
            control['text'].insert('1.0', display)
        self.custom.configure(state='normal')
        self.custom.delete('1.0', 'end')
        self.custom.insert('1.0', json.dumps(snapshot['value'].get('custom', {}), ensure_ascii=False, indent=2))
        self.original.configure(state='normal')
        self.original.delete('1.0', 'end')
        self.original.insert('1.0', json.dumps(snapshot['shared'], ensure_ascii=False, indent=2))
        self.original.configure(state='disabled')
        self.source.configure(text=(tr('Shared source: {v0} ({v1} linked games).', v0=snapshot['shared_id'],
                                      v1=snapshot['linked_games']) if snapshot['shared_id'] else
                                    tr('No shared record. Custom values can be added manually.')))
        self.set_busy(False)

    def collect(self):
        result = deepcopy(self.snapshot['value'])
        for (group, key), control in self.controls.items():
            if control['active'].get():
                text = control['text'].get('1.0', 'end-1c')
                value = (deepcopy(control['initial_value']) if text == control['initial'] else
                         parse_field(key, text) if group == 'fields' else text)
                result.setdefault(group, {})[key] = value
            elif group in result:
                result[group].pop(key, None)
                if not result[group]:
                    result.pop(group)
        custom = json.loads(self.custom.get('1.0', 'end-1c').strip() or '{}')
        if not isinstance(custom, dict):
            raise ValueError(tr('Custom metadata must be a JSON object.'))
        if custom:
            result['custom'] = custom
        else:
            result.pop('custom', None)
        return result

    def save(self):
        if self.busy or self.snapshot is None:
            return
        try:
            value = self.collect()
        except (ValueError, TypeError) as error:
            messagebox.showerror(tr('Could not save'), str(error), parent=self.window)
            return
        token = self.snapshot['token']
        self.set_busy(True)
        self.editor.task(lambda: self.editor.metadata_store.save(self.output, self.serial, value, token),
                         self.saved, self.failed)

    def undo(self):
        if self.busy or self.snapshot is None:
            return
        token = self.snapshot['token']
        self.set_busy(True)
        self.editor.task(lambda: self.editor.metadata_store.undo(self.output, self.serial, token), self.saved, self.failed)

    def saved(self, _):
        self.set_busy(False)
        self.editor.reload_game(self.output, self.serial, self.serial is None)
        self.load()

    def failed(self, error):
        if not self.window.winfo_exists():
            return
        self.set_busy(False)
        messagebox.showerror(tr('Could not save'), str(error), parent=self.window)

    def close(self):
        if self.busy:
            return
        if self.snapshot is not None:
            try:
                changed = self.collect() != self.snapshot['value']
            except (ValueError, TypeError):
                changed = True
            if changed and not messagebox.askyesno(tr('Discard metadata changes'),
                    tr('Close without saving the metadata changes?'), parent=self.window):
                return
        self.window.grab_release()
        self.window.destroy()
        self.editor.metadata_dialog = None

