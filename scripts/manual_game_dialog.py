"""Create a game using a user-supplied identifier without downloading a DAT."""
import tkinter as tk
from tkinter import ttk, messagebox

from dat_catalog import systems
from game_registration import manual_destination
from i18n import tr, localize, localize_title, set_text


class ManualGameDialog:
    def __init__(self, editor):
        self.editor = editor
        self.busy = False
        self.outputs = {}
        for row in getattr(editor, 'all_libraries', []):
            self.outputs.setdefault(row['system'], row['output'])
        current = editor.catalog.get('system') if editor.catalog else ''
        if current and editor.current_output:
            self.outputs[current] = editor.current_output
        self.window = tk.Toplevel(editor.window)
        localize_title(self.window, 'Add game manually')
        self.window.transient(editor.window)
        self.window.geometry('690x455')
        self.window.minsize(580, 400)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda _: self.close())
        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill='both', expand=True)
        self.system = tk.StringVar(value=current)
        self.name = tk.StringVar()
        self.serial = tk.StringVar()
        self.reference = tk.StringVar()
        localize(ttk.Label(frame), 'Console (choose one or enter a new name)').pack(anchor='w')
        self.system_box = ttk.Combobox(frame, textvariable=self.system,
            values=sorted(set(systems()) | set(self.outputs)))
        self.system_box.pack(fill='x', pady=(3, 10))
        self.fields = [self.system_box]
        for variable, label in [
            (self.name, 'Full game name (including region / edition)'),
            (self.serial, 'Serial / title ID'),
            (self.reference, 'Source / reference (optional)')]:
            localize(ttk.Label(frame), label).pack(anchor='w')
            field = ttk.Entry(frame, textvariable=variable)
            field.pack(fill='x', pady=(3, 10))
            field.bind('<Return>', lambda _: self.create())
            self.fields.append(field)
        localize(ttk.Label(frame, wraplength=640),
                 'Use the identifier printed on the game or published by its platform. These details are supplied by you and are not verified against a DAT.').pack(anchor='w', pady=(0, 10))
        self.preview = tk.StringVar()
        ttk.Label(frame, textvariable=self.preview, wraplength=640).pack(anchor='w', fill='x')
        self.create_button = localize(ttk.Button(frame, command=self.create), 'Create / open game')
        self.create_button.pack(anchor='e', side='bottom')
        for variable in (self.system, self.name, self.serial, self.reference):
            variable.trace_add('write', lambda *_: self.refresh_preview())
        self.refresh_preview()
        self.window.grab_set()
        self.fields[1 if current else 0].focus_set()

    def destination(self):
        values = manual_destination(self.system.get(), self.name.get(), self.serial.get(), self.reference.get())
        system = values['system']
        output = self.outputs.get(system, self.editor.store.generated/system)
        # Preserve existing names and their output paths even with different case.
        for known, directory in self.outputs.items():
            if known.casefold() == system.casefold():
                values['system'], output = known, directory
                break
        return values, output

    def refresh_preview(self):
        try:
            values, output = self.destination()
            set_text(self.preview, 'Identifier: {v0}\nFolder: {v1}',
                     v0=values['serial'], v1=str(output/values['folder']))
            valid = True
        except ValueError as error:
            self.preview.set(str(error))
            valid = False
        self.create_button.configure(state='normal' if valid and not self.busy else 'disabled')

    def close(self):
        if self.busy:
            return
        self.window.grab_release()
        self.window.destroy()

    def create(self):
        if self.busy:
            return
        try:
            values, output = self.destination()
        except ValueError as error:
            messagebox.showerror(tr('Could not add game'), str(error), parent=self.window)
            return
        self.busy = self.editor.busy = True
        self.editor.update_buttons()
        for field in self.fields:
            field.configure(state='disabled')
        self.create_button.configure(state='disabled')

        def finish():
            self.busy = self.editor.busy = False
            self.editor.update_buttons()

        def done(result):
            finish()
            self.editor.pending_game = (output, result[0]['folder'])
            self.editor.console_filter.set('')
            self.editor.query.set('')
            self.editor.refresh_libraries()
            self.close()

        def failed(error):
            finish()
            for field in self.fields:
                field.configure(state='normal')
            self.refresh_preview()
            messagebox.showerror(tr('Could not add game'), str(error), parent=self.window)

        self.editor.task(lambda: self.editor.registration.add_manual(output, values['system'],
            values['name'], values['serial_raw'], values['reference']), done, failed)
