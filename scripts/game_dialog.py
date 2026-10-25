"""Add a missing game by choosing an official DAT entry and its identifiers."""
from i18n import tr, localize, set_text, localize_title, localize_heading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

from dat_catalog import DatCache, providers, source_url, systems


class AddGameDialog:
    def __init__(self, editor, cache=None):
        self.editor, self.cache = editor, cache or DatCache()
        self.catalog = None
        self.results = {}
        self.identifiers = []
        self.busy = False
        self.window = tk.Toplevel(editor.window)
        localize_title(self.window, 'Add game from No-Intro / Redump')
        self.window.geometry('1080x710')
        self.window.transient(editor.window)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        self.initial_output = editor.current_output
        self.initial_system = editor.catalog.get('system') if editor.catalog else None
        self.system = tk.StringVar(value=self.initial_system if self.initial_system in systems() else systems()[0])
        self.provider = tk.StringVar()
        controls = ttk.Frame(frame)
        controls.pack(fill='x')
        self.system_box = ttk.Combobox(controls, textvariable=self.system, values=systems(), state='readonly', width=52)
        self.system_box.pack(side='left')
        self.provider_box = ttk.Combobox(controls, textvariable=self.provider, state='readonly', width=16)
        self.provider_box.pack(side='left', padx=8)
        self.system_box.bind('<<ComboboxSelected>>', lambda _: self.change_system())
        self.provider_box.bind('<<ComboboxSelected>>', lambda _: self.load_cache())
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=10)
        self.download_button = localize(ttk.Button(actions, command=self.download), 'Download / update DAT', values={})
        self.download_button.pack(side='left')
        self.import_button = localize(ttk.Button(actions, command=self.import_dat), 'Import DAT/ZIP', values={})
        self.import_button.pack(side='left', padx=8)
        localize(ttk.Button(actions, command=self.open_source), 'Open provider website', values={}).pack(side='left')
        self.status = tk.StringVar(value='')
        ttk.Label(frame, textvariable=self.status, wraplength=1000).pack(anchor='w', pady=(0, 10))
        search = ttk.Frame(frame)
        search.pack(fill='x')
        self.query = tk.StringVar()
        field = ttk.Entry(search, textvariable=self.query)
        field.pack(side='left', fill='x', expand=True)
        field.bind('<Return>', lambda _: self.search())
        self.search_button = localize(ttk.Button(search, command=self.search), 'Search name or serial', values={})
        self.search_button.pack(side='left', padx=(8, 0))
        result_frame = ttk.Frame(frame)
        result_frame.pack(fill='both', expand=True, pady=10)
        self.tree = ttk.Treeview(result_frame, columns=('serials','version'), show='tree headings', selectmode='browse')
        localize_heading(self.tree, '#0', 'Full DAT name: choose the exact region / edition')
        localize_heading(self.tree, 'serials', 'Official identifiers')
        localize_heading(self.tree, 'version', 'Version')
        self.tree.column('#0', width=600)
        self.tree.column('serials', width=240)
        self.tree.column('version', width=90)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(result_frame, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.show_destinations())
        self.destinations = ttk.Frame(frame)
        self.destinations.pack(fill='x')
        self.explanation = tk.StringVar(value=tr('Search results are candidates; no region, revision or disc is selected automatically.'))
        ttk.Label(frame, textvariable=self.explanation, wraplength=1000).pack(anchor='w', pady=8)
        self.create_button = localize(ttk.Button(frame, command=self.create, state='disabled'), 'Create / open selected game', values={})
        self.create_button.pack(anchor='e')
        self.change_system()
        self.window.grab_set()
        field.focus_set()

    def close(self):
        if self.busy:
            return
        self.window.grab_release()
        self.window.destroy()

    def change_system(self):
        options = providers(self.system.get())
        self.provider_box.configure(values=options)
        if self.provider.get() not in options:
            self.provider.set(options[0])
        self.load_cache()

    def load_cache(self):
        self.catalog = None
        self.tree.delete(*self.tree.get_children())
        self.results = {}
        self.show_destinations()
        system, provider = self.system.get(), self.provider.get()
        self.background(lambda: self.cache.load(system, provider), self.loaded)

    def background(self, work, success):
        if self.busy:
            return
        self.busy = self.editor.busy = True
        self.editor.update_buttons()
        for button in (self.download_button, self.import_button, self.search_button, self.create_button):
            button.configure(state='disabled')
        self.system_box.configure(state='disabled')
        self.provider_box.configure(state='disabled')
        def finish():
            self.busy = self.editor.busy = False
            if not self.window.winfo_exists():
                return
            for button in (self.download_button, self.import_button, self.search_button):
                button.configure(state='normal')
            self.system_box.configure(state='readonly')
            self.provider_box.configure(state='readonly')
            self.editor.update_buttons()
            self.show_destinations()
        def done(value):
            finish()
            success(value)
        def failed(error):
            finish()
            self.status.set(str(error))
            messagebox.showerror(tr('Could not complete the operation'), str(error), parent=self.window)
        self.editor.task(work, done, failed)

    def loaded(self, catalog):
        self.catalog = catalog
        self.results = {}
        self.tree.delete(*self.tree.get_children())
        self.show_destinations()
        if catalog is None:
            set_text(self.status, 'No cached DAT. Download or import the official DAT/ZIP. Wii: Redump = discs; No-Intro = digital titles.')
        else:
            valid = sum(any(r['status'] == 'ready' for r in catalog.destinations(e)) for e in catalog.entries)
            set_text(self.status, '{v0} · {v1} · {v2:,} entries · {v3:,} with valid IDs. No-Intro: import DB Export too if serials are missing.', v0=catalog.provider, v1=catalog.provenance.get('version') or tr('no version'), v2=len(catalog.entries), v3=valid)
            if self.query.get().strip():
                self.search()

    def download(self):
        system, provider = self.system.get(), self.provider.get()
        set_text(self.status, 'Downloading and verifying the official catalogue…')
        self.background(lambda: self.cache.download(system, provider), self.loaded)

    def import_dat(self):
        path = filedialog.askopenfilename(parent=self.window, title=tr('Official Standard DAT or DB Export'),
                                         filetypes=[(tr('DAT/XML/ZIP catalogues'),'*.dat *.xml *.zip')])
        if path:
            system, provider = self.system.get(), self.provider.get()
            self.background(lambda: self.cache.import_file(system, provider, path), self.loaded)

    def open_source(self):
        url = source_url(self.system.get(), self.provider.get())
        webbrowser.open('https://redump.info/downloads' if self.provider.get() == 'redump' else url)

    def search(self):
        if self.busy or self.catalog is None:
            return
        catalog, query = self.catalog, self.query.get()
        self.background(lambda: catalog.search(query), self.show_results)

    def show_results(self, result):
        entries, total = result
        self.tree.delete(*self.tree.get_children())
        self.results = {}
        for index, entry in enumerate(entries):
            key = str(index)
            routes = self.catalog.destinations(entry)
            text = ', '.join(r['serial'] for r in routes) or tr('No identifier')
            self.tree.insert('', 'end', iid=key, text=entry['name'], values=(text, entry.get('version') or ''))
            self.results[key] = entry
        set_text(self.status, '{v0:,} results; showing {v1:,}. Refine the search if your game is missing.', v0=total, v1=len(entries))
        self.show_destinations()

    def selected(self):
        selected = self.tree.selection()
        return self.results.get(selected[0]) if selected else None

    def show_destinations(self):
        for widget in self.destinations.winfo_children():
            widget.destroy()
        self.identifiers = []
        self.create_button.configure(state='disabled')
        entry = self.selected()
        if entry is None or self.catalog is None:
            return
        valid = [r for r in self.catalog.destinations(entry) if r['status'] == 'ready']
        blocked = [r for r in self.catalog.destinations(entry) if r['status'] != 'ready']
        for route in valid:
            value = tk.BooleanVar(value=True)
            ttk.Checkbutton(self.destinations, text=route['serial']+' → '+route['folder'], variable=value).pack(anchor='w')
            self.identifiers.append((route['serial'], value))
        if blocked:
            statuses = {'excluded':'Excluded', 'collision':'Collision', 'invalid':'Invalid'}
            ttk.Label(self.destinations, text=tr('Excluded: ')+', '.join(
                r['serial']+' ('+tr(statuses.get(r['status'],r['status']))+')' for r in blocked), wraplength=1000).pack(anchor='w')
        set_text(self.explanation, 'Full names and DAT provenance are preserved. Existing folders are reused and their artwork is kept.' if valid else 'This entry has no supported identifier: a folder cannot be created for it.')
        if valid and not self.busy:
            self.create_button.configure(state='normal')

    def create(self):
        entry = self.selected()
        if self.busy or entry is None:
            return
        serials = [serial for serial, value in self.identifiers if value.get()]
        if not serials:
            messagebox.showinfo(tr('Choose an identifier'), tr('Select at least one valid destination.'), parent=self.window)
            return
        system, catalog = self.system.get(), self.catalog
        output = self.initial_output if system == self.initial_system else self.editor.store.generated/system
        routes = {r['serial']:r for r in catalog.destinations(entry)}
        text = entry['name']+'\n\n'+ '\n'.join(str(output/routes[s]['folder']) for s in serials)
        if not messagebox.askyesno(tr('Confirm game and destinations'), text, parent=self.window):
            return
        def done(result):
            folder = next((r['folder'] for r in result if r['created']), result[0]['folder'])
            self.editor.pending_game = (output, folder)
            self.editor.console_filter.set('')
            self.editor.query.set('')
            self.editor.refresh_libraries()
            self.close()
        self.background(lambda: self.editor.registration.add(output, catalog, entry['redump_id'], serials), done)
