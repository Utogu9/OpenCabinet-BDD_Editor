"""Desktop artwork browser/editor. Run with Run-Editor.cmd."""
from i18n import tr, localize, set_text, localize_title, localize_heading
from i18n import initialize_language, language, set_language, refresh_translations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import unicodedata

from PIL import Image, ImageTk
from editor_store import ArtworkStore, encode_import, inside
from console_artwork import ConsoleArtwork, CONSOLE_KINDS
from editor_common import ROOT, settings_path, write_json

KINDS = {'cover_front': 'Front cover', 'cover_back': 'Back cover', 'cover_full': 'Full cover',
         'inlay': 'Inlay (inside cover)',
         'poster_front': 'Front poster', 'poster_back': 'Back poster',
         'spine': 'Spine', 'disc': 'Disc', 'cartridge': 'Cartridge', 'logo': 'Logo',
         'screenshot': 'Screenshot', 'title_screen': 'Title screen',
         'banner': 'Banner', 'fanart': 'Artwork', 'manual': 'PDF manual'}
BG, PANEL, TEXT, MUTED, ACCENT = '#131820', '#1e2632', '#edf2f7', '#a6b4c5', '#54d6be'


def search_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


def game_titles(game):
    return list(dict.fromkeys(e['name'] for e in game.get('entries', []) if e.get('name')))


class Editor:
    def __init__(self, window, root=ROOT, include_samples=False, library=None, settings=None):
        self.settings_file = Path(settings) if settings is not None else Path(root)/'editor-setting.json'
        initialize_language(self.settings_file)
        if library is None:
            self.store = ArtworkStore(root)
        else:
            from editor_location import LocatedArtworkStore
            self.store = LocatedArtworkStore(library)
        self.window = window
        self.console_store = ConsoleArtwork(self.store)
        from game_registration import GameRegistration
        self.registration = GameRegistration(self.store)
        from metadata_store import MetadataStore
        self.metadata_store = MetadataStore(self.store)
        self.metadata_dialog = None
        self.pending_game = None
        self.console_mode = False
        self.samples = include_samples
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.closed = False
        self.busy = False
        self.current_output = self.catalog = self.serial = None
        self.games, self.rows, self.photos = {}, {}, []
        self.action_buttons = []
        self.filter_timer = None
        self.generation = 0
        localize_title(self.window, 'OpenCabinet · Artwork editor')
        self.window.geometry('1320x860')
        self.window.minsize(1000, 650)
        self.window.configure(bg=BG)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.style()
        self.build()
        self.refresh_libraries()
        self.poll_status()

    def style(self):
        s = ttk.Style(self.window)
        s.theme_use('clam')
        s.configure('.', background=BG, foreground=TEXT, font=('Segoe UI', 10))
        s.configure('TFrame', background=BG)
        s.configure('TLabel', background=BG, foreground=TEXT)
        s.configure('Muted.TLabel', foreground=MUTED)
        s.configure('Heading.TLabel', font=('Segoe UI Semibold', 21))
        s.configure('TEntry', fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT, padding=7)
        s.configure('TCombobox', fieldbackground=PANEL, background=PANEL, foreground=TEXT, padding=6)
        s.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', TEXT)])
        s.configure('TButton', background=PANEL, foreground=TEXT, padding=(12, 8), borderwidth=0)
        s.map('TButton', background=[('active', '#334356')], foreground=[('disabled', '#64748b')])
        s.configure('Accent.TButton', background=ACCENT, foreground='#11221f')
        s.map('Accent.TButton', background=[('active', '#8ee8d6')])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=30, borderwidth=0)
        s.map('Treeview', background=[('selected', '#345469')])
        s.configure('Treeview.Heading', background=BG, foreground=MUTED)

    def build(self):
        top = ttk.Frame(self.window, padding=(22, 18))
        top.pack(fill='x')
        ttk.Label(top, text='OpenCabinet', style='Heading.TLabel').pack(side='left')
        self.language_button = ttk.Button(top, text='ES' if language() == 'en' else 'EN', width=3,
                                         command=self.toggle_language)
        self.language_button.pack(side='left', padx=(10, 4))
        localize(ttk.Label(top, style='Muted.TLabel'), '  /  Artwork library', values={}).pack(side='left', pady=8)
        localize(ttk.Button(top, command=self.refresh_libraries), 'Refresh library', values={}).pack(side='right')
        self.status = tk.StringVar(value=tr('Reading library…'))
        ttk.Label(self.window, textvariable=self.status, style='Muted.TLabel', padding=(24, 0, 24, 12)).pack(fill='x')
        paned = ttk.Panedwindow(self.window, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=20, pady=(0, 18))
        left = ttk.Frame(paned, padding=(0, 0, 16, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=3)
        localize(ttk.Label(left, style='Muted.TLabel'), 'CONSOLE / LIBRARY', values={}).pack(anchor='w', pady=(0, 7))
        self.console_filter = tk.StringVar()
        ttk.Entry(left, textvariable=self.console_filter).pack(fill='x', pady=(0, 8))
        self.console_filter.trace_add('write', lambda *_: self.filter_libraries())
        self.library_name = tk.StringVar()
        self.library_box = ttk.Combobox(left, textvariable=self.library_name, state='readonly', width=40)
        self.library_box.pack(fill='x')
        self.library_box.bind('<<ComboboxSelected>>', lambda _: self.load_library())
        localize(ttk.Button(left, command=self.show_console), 'Console artwork', values={}).pack(fill='x', pady=(8, 0))
        self.new_game_button = localize(ttk.Button(left, command=self.add_game), 'Add game from DAT', values={})
        self.new_game_button.pack(fill='x', pady=(8, 0))
        self.undo_game_button = localize(ttk.Button(left, command=self.undo_game), 'Undo last game registration', values={})
        self.undo_game_button.pack(fill='x', pady=(6, 0))
        localize(ttk.Label(left, style='Muted.TLabel'), 'SEARCH GAME OR SERIAL', values={}).pack(anchor='w', pady=(20, 7))
        self.query = tk.StringVar()
        self.search_entry = ttk.Entry(left, textvariable=self.query)
        self.search_entry.pack(fill='x')
        self.query.trace_add('write', self.schedule_filter)
        self.count = tk.StringVar()
        ttk.Label(left, textvariable=self.count, style='Muted.TLabel').pack(anchor='w', pady=8)
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=('serial',), show='tree headings', selectmode='browse')
        localize_heading(self.tree, '#0', 'Game')
        self.tree.heading('serial', text='ID')
        self.tree.column('#0', width=285)
        self.tree.column('serial', width=115)
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.select_game())
        self.title = localize(ttk.Label(right, style='Heading.TLabel', wraplength=760), 'Choose a game', values={})
        self.title.pack(anchor='w', pady=(0, 6))
        self.details = localize(ttk.Label(right, style='Muted.TLabel', wraplength=760), 'Search by name, region or identifier.', values={})
        self.details.pack(anchor='w', pady=(0, 12))
        self.metadata_button = localize(ttk.Button(right, command=self.edit_metadata), 'Edit metadata', values={})
        self.metadata_button.pack(anchor='w', pady=(0, 10))
        extra = ttk.Frame(right)
        extra.pack(fill='x', pady=(0, 12))
        localize(ttk.Label(extra), 'Add type:', values={}).pack(side='left', padx=(0, 8))
        self.kind = tk.StringVar(value='cover_back')
        self.kind_box = ttk.Combobox(extra, textvariable=self.kind, values=list(KINDS), width=20)
        self.kind_box.pack(side='left')
        self.add_button = localize(ttk.Button(extra, style='Accent.TButton', command=self.import_kind), 'Import image', values={})
        self.add_button.pack(side='left', padx=8)
        self.undo_button = localize(ttk.Button(extra, command=self.undo), 'Undo change', values={})
        self.undo_button.pack(side='right')
        self.window.bind('<Control-f>', lambda _: self.search_entry.focus_set())
        self.window.bind('<Control-o>', lambda _: self.import_kind())
        self.window.bind('<F5>', lambda _: self.refresh_libraries())
        self.note = ttk.Label(right, text='', style='Muted.TLabel', wraplength=760)
        self.note.pack(anchor='w', pady=(0, 10))
        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.cards = ttk.Frame(self.canvas)
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards, anchor='nw')
        self.cards.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.cards_window, width=e.width))
        self.canvas.bind_all('<MouseWheel>', self.wheel)

    def wheel(self, event):
        # Keep list/combobox scrolling independent from the image panel.
        if event.widget == self.canvas or str(event.widget).startswith(str(self.cards)):
            self.canvas.yview_scroll(-int(event.delta/120), 'units')

    def task(self, work, success, error=None):
        future = self.pool.submit(work)
        def check():
            if self.closed:
                return
            if not future.done():
                self.window.after(80, check)
                return
            try:
                value = future.result()
            except Exception as exc:
                if error:
                    error(exc)
                else:
                    messagebox.showerror(tr('Could not complete the action'), str(exc), parent=self.window)
            else:
                success(value)
        self.window.after(80, check)

    def refresh_libraries(self):
        self.task(lambda: self.store.libraries(self.samples), self.libraries_loaded)

    def libraries_loaded(self, libraries):
        self.all_libraries = libraries
        self.filter_libraries()
        if not libraries:
            set_text(self.count, 'No catalogues yet. Refresh when Run-Library has made progress.')

    def filter_libraries(self):
        if not hasattr(self, 'all_libraries'):
            return
        needle = search_key(self.console_filter.get())
        self.library_rows = {f"{r['system']}  ·  {r['revision']}": r for r in self.all_libraries
                             if needle in search_key(r['system'])}
        values = list(self.library_rows)
        old = self.library_name.get()
        if self.pending_game:
            old = next((label for label, row in self.library_rows.items() if row['output'] == self.pending_game[0]), old)
            self.library_name.set(old)
        self.library_box['values'] = values
        if old not in values:
            self.library_name.set(values[0] if values else '')
        if values:
            self.load_library()
        else:
            self.generation += 1
            self.current_output = self.catalog = self.serial = None
            self.games = {}
            self.tree.delete(*self.tree.get_children())
            self.clear_cards()
            set_text(self.count, 'No libraries match this filter')
            localize(self.title, 'Choose a console', values={})
            self.details.configure(text='')
            self.update_buttons()

    def load_library(self):
        row = self.library_rows.get(self.library_name.get())
        if not row:
            return
        self.generation += 1
        generation = self.generation
        output = row['output']
        selected = self.serial if self.current_output == output else None
        if self.pending_game and self.pending_game[0] == output:
            selected = self.pending_game[1]
        console_selected = self.console_mode and self.current_output == output
        set_text(self.count, 'Reading names and folders…')
        def load():
            if self.registration.has_pending(output):
                self.registration.recover(output)
            if self.metadata_store.has_pending(output):
                self.metadata_store.recover(output)
            catalog = self.store.read_catalog(output)
            games = dict(catalog.get('games', {}))
            for folder in output.iterdir():
                if folder.is_dir() and not folder.is_symlink() and folder.name not in games:
                    games[folder.name] = {'serial': folder.name, 'entries': [], 'images': {}}
            return catalog, games
        def done(result):
            if generation != self.generation:
                return
            self.current_output = output
            self.catalog, self.games = result
            self.serial = selected
            if self.pending_game and self.pending_game == (output, selected):
                self.pending_game = None
            self.console_mode = False
            self.filter_games()
            if console_selected:
                self.show_console()
        self.task(load, done)

    def schedule_filter(self, *_):
        if self.filter_timer:
            self.window.after_cancel(self.filter_timer)
        self.filter_timer = self.window.after(180, self.filter_games)

    def filter_games(self):
        self.filter_timer = None
        needle = search_key(self.query.get())
        selected = self.serial
        self.tree.delete(*self.tree.get_children())
        rows = []
        for serial, game in self.games.items():
            titles = game_titles(game)
            title = titles[0] if titles else tr('{v0} · no catalogue yet', v0=serial)
            if all(term in search_key(' '.join([serial, *titles])) for term in needle.split()):
                rows.append((title, serial))
        rows.sort(key=lambda row: search_key(row[0]))
        self.rows = {}
        for i, (title, serial) in enumerate(rows):
            item = str(i)
            self.tree.insert('', 'end', iid=item, text=title, values=(serial,))
            self.rows[item] = serial
            if serial == selected:
                self.tree.selection_set(item)
                self.tree.see(item)
        set_text(self.count, '{v0:,} games / folders', v0=len(rows))
        if rows and not self.tree.selection():
            self.tree.selection_set('0')
        elif not rows:
            self.serial = None
            self.clear_cards()
            localize(self.title, 'No matches', values={})

    def clear_cards(self):
        for child in self.cards.winfo_children():
            child.destroy()
        self.photos.clear()
        self.action_buttons.clear()
        self.current_images = {}

    def select_game(self):
        selection = self.tree.selection()
        if not selection or selection[0] not in self.rows:
            return
        self.console_mode = False
        self.kind_box.configure(values=list(KINDS), state='normal')
        if self.kind.get() not in KINDS:
            self.kind.set('cover_back')
        self.serial = self.rows[selection[0]]
        game = self.games[self.serial]
        titles = game_titles(game)
        self.title.configure(text=titles[0] if titles else self.serial)
        self.details.configure(text=f"{self.serial}\n"+'\n'.join(titles[1:])+f'\n{self.current_output / self.serial}')
        self.clear_cards()
        self.canvas.yview_moveto(0)
        images = dict(game.get('images', {}))
        directory = inside(self.current_output/self.serial, self.current_output)
        if directory.exists():
            for path in directory.iterdir():
                if path.suffix.lower() in {'.webp', '.png', '.jpg', '.jpeg', '.pdf'} and path.stem not in images:
                    from artwork_actions import image_kind
                    images[path.stem] = {'path': f'{self.serial}/{path.name}', 'kind': image_kind(path.stem, {}), 'bytes': path.stat().st_size}
                    if path.suffix.lower() == '.pdf':
                        images[path.stem]['format'] = 'PDF'
        labels = sorted(images, key=lambda label: (list(KINDS).index(images[label]['kind']) if images[label]['kind'] in KINDS else 99, label))
        for kind in ('cover_front', 'cover_back', 'disc', 'screenshot', 'logo', 'title_screen'):
            if not any(asset['kind'] == kind for asset in images.values()):
                labels.append(kind)
        self.render_cards(labels, images)

    def show_console(self):
        if not self.current_output or not self.catalog:
            return
        self.console_mode = True
        self.serial = None
        self.tree.selection_remove(*self.tree.selection())
        self.generation += 1
        generation, output = self.generation, self.current_output
        self.clear_cards()
        self.title.configure(text=self.catalog['system'])
        localize(self.details, 'Console artwork\n{v0}', values={'v0': output})
        self.kind_box.configure(values=list(CONSOLE_KINDS), state='readonly')
        if self.kind.get() not in CONSOLE_KINDS:
            self.kind.set('logo')
        self.update_buttons()
        def done(images):
            if self.console_mode and self.current_output == output and self.generation == generation:
                labels = sorted(images, key=lambda label: (list(CONSOLE_KINDS).index(images[label]['kind']), len(label), label))
                labels.extend(kind for kind in CONSOLE_KINDS if not any(asset['kind'] == kind for asset in images.values()))
                self.render_cards(labels, images)
        self.task(lambda: self.console_store.images(output), done)

    def render_cards(self, labels, images):
        self.current_images = images
        generation, serial, output = self.generation, self.serial, self.current_output
        for index, label in enumerate(labels):
            asset = images.get(label)
            kind = asset['kind'] if asset else label
            is_pdf = kind == 'manual' or bool(asset and asset.get('format') == 'PDF')
            card = tk.Frame(self.cards, bg=PANEL, padx=12, pady=12)
            card.grid(row=index//2, column=index%2, sticky='nsew', padx=(0, 10), pady=(0, 12))
            self.cards.columnconfigure(index%2, weight=1)
            titles = CONSOLE_KINDS if self.console_mode else KINDS
            localize(tk.Label(card, bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 11)), titles.get(kind, kind)).pack(anchor='w')
            tk.Label(card, text=Path(asset['path']).name if asset else label+('.pdf' if is_pdf else '.webp'), bg=PANEL, fg=MUTED).pack(anchor='w', pady=(2, 6))
            preview = localize(tk.Label(card, bg='#10151c', fg=MUTED, width=30, height=10), 'No image' if not asset else 'Loading…', values={})
            preview.pack(fill='both', expand=True)
            if asset and is_pdf:
                path = inside(output/asset['path'], output)
                localize(preview, 'PDF · {v0} pages\n{v1:.1f} KiB\n\nClick to open the manual', values={'v0': asset.get('pages', '?'), 'v1': asset['bytes'] / 1024}, cursor='hand2')
                preview.bind('<Button-1>', lambda _, p=path: self.open_pdf(p))
                original_size = asset.get('compression', {}).get('candidate_bytes', {}).get('original', asset['bytes'])
                localize(tk.Label(card, bg=PANEL, fg=MUTED), 'Original: {v0:.1f} KiB · saved: {v1:.1f} KiB', values={'v0': original_size / 1024, 'v1': asset['bytes'] / 1024}).pack(anchor='w', pady=7)
            elif asset:
                path = inside(output/asset['path'], output)
                def thumbnail(path=path):
                    if path.suffix.lower() == '.svg':
                        from svg_tools import preview_svg
                        im = preview_svg(path.read_bytes(), 400)
                        im.thumbnail((320, 220), Image.Resampling.LANCZOS)
                        return im
                    with Image.open(path) as im:
                        im = im.convert('RGBA')
                        im.thumbnail((320, 220), Image.Resampling.LANCZOS)
                        return im
                def loaded(im, widget=preview, path=path):
                    if generation != self.generation or serial != self.serial or not widget.winfo_exists():
                        return
                    photo = ImageTk.PhotoImage(im)
                    self.photos.append(photo)
                    widget.configure(image=photo, text='', width=0, height=0, cursor='hand2')
                    widget.bind('<Button-1>', lambda _: self.view_image(path))
                def unavailable(exc, widget=preview):
                    if widget.winfo_exists():
                        localize(widget, 'Unavailable · Refresh the library', values={})
                self.task(thumbnail, loaded, unavailable)
                compression = asset.get('compression', {})
                mode = tr('lossless') if compression.get('lossless') else tr('quality 90') if compression else ''
                extra = tr(' · edited') if asset.get('manual') else ''
                tk.Label(card, text=f"{asset.get('width', '?')} × {asset.get('height', '?')} · {asset['bytes']/1024:.1f} KiB · {mode}{extra}",
                         bg=PANEL, fg=MUTED).pack(anchor='w', pady=7)
            actions = ttk.Frame(card)
            actions.pack(fill='x', pady=(6, 0))
            button = localize(ttk.Button(actions, command=lambda k=kind, l=label, a=asset: self.import_image(k, l, create_only=not bool(a))), 'Replace' if asset else 'Import', values={})
            button.pack(side='left')
            self.action_buttons.append(button)
            variant = localize(ttk.Button(actions, command=lambda k=kind: self.import_image(k, self.next_label(k), create_only=True)), '+ Variant', values={})
            variant.pack(side='left', padx=5)
            self.action_buttons.append(variant)
            if asset and asset.get('manual'):
                reset = localize(ttk.Button(actions, command=lambda l=label: self.reset(l)), 'Undo' if self.console_mode else 'Restore', values={})
                reset.pack(side='left')
                self.action_buttons.append(reset)
            if asset:
                more = ttk.Frame(card)
                more.pack(fill='x', pady=(6, 0))
                delete = localize(ttk.Button(more, command=lambda l=label: self.artwork_action(l, 'delete')), 'Delete')
                delete.pack(side='left')
                self.action_buttons.append(delete)
                if label != kind:
                    primary = localize(ttk.Button(more, command=lambda l=label: self.artwork_action(l, 'primary')), 'Make primary')
                    primary.pack(side='left', padx=5)
                    self.action_buttons.append(primary)
                comparable = [key for key, value in images.items() if value.get('format') != 'PDF' and Path(value['path']).suffix.lower() != '.pdf']
                if label in comparable and len(comparable) > 1:
                    compare = localize(ttk.Button(more, command=lambda l=label: self.compare_images(l)), 'Compare')
                    compare.pack(side='left', padx=5)
                    self.action_buttons.append(compare)
        self.update_buttons()

    def artwork_action(self, label, operation):
        if not self.can_edit() or label not in self.current_images:
            return
        asset = self.current_images[label]
        if operation == 'delete' and not messagebox.askyesno(tr('Delete artwork'),
                tr('Delete {v0}? A backup is kept so you can undo this change.', v0=Path(asset['path']).name), parent=self.window):
            return
        output, serial, console = self.current_output, self.serial, self.console_mode
        self.busy = True
        self.update_buttons()
        def work():
            from artwork_actions import change_console, change_game
            if console:
                change_console(self.console_store, output, label, operation, asset.get('sha256'))
            else:
                change_game(self.store, output, serial, label, operation, asset.get('sha256'))
        def done(_):
            self.busy = False
            localize(self.note, 'Artwork deleted. Use Undo change to restore it.' if operation == 'delete' else 'Primary artwork updated; files and credits were kept.', values={})
            self.reload_game(output, serial, console)
        self.task(work, done, self.edit_failed)

    def compare_images(self, label):
        from image_comparison import ComparisonWindow
        return ComparisonWindow(self, self.current_images, label)

    def next_label(self, kind):
        if self.console_mode:
            return self.console_store.next_label(self.current_output, kind)
        images = set(self.games[self.serial].get('images', {}))
        directory = inside(self.current_output/self.serial, self.current_output)
        if directory.exists():
            images.update(path.stem for path in directory.iterdir())
        number = 1
        while (kind if number == 1 else f'{kind}{number}') in images:
            number += 1
        return kind if number == 1 else f'{kind}{number}'

    def import_kind(self):
        kind = self.kind.get().strip()
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', kind):
            messagebox.showerror(tr('Image type'), tr('Use lowercase letters, numbers and underscores, for example cover_back.'), parent=self.window)
            return
        if self.console_mode and kind not in CONSOLE_KINDS:
            messagebox.showerror(tr('Console artwork type'), tr('Choose logo, render or screenshot.'), parent=self.window)
            return
        if self.serial or self.console_mode:
            self.import_image(kind, self.next_label(kind), create_only=True)

    def import_image(self, kind, label, *, create_only=False):
        if not self.can_edit():
            return
        is_pdf = kind == 'manual'
        logo = self.console_mode and kind == 'logo'
        filename = filedialog.askopenfilename(parent=self.window, title=tr('Import {v0}.{v1}', v0=label, v1='pdf' if is_pdf else 'svg / webp' if logo else 'webp'),
            filetypes=[(tr('PDF manuals'), '*.pdf')] if is_pdf else [(tr('Images'), '*.png *.jpg *.jpeg *.webp *.svg' if logo else '*.png *.jpg *.jpeg *.webp'), (tr('All files'), '*.*')])
        if not filename:
            return
        output, serial = self.current_output, self.serial
        console = self.console_mode
        self.busy = True
        localize(self.note, 'Optimizing PDF images and comparing file sizes…' if is_pdf else 'Comparing lossless WebP and quality 90…', values={})
        self.update_buttons()
        def work():
            if logo and Path(filename).suffix.lower() == '.svg':
                from svg_tools import encode_svg
                encoded = encode_svg(filename)
            elif is_pdf:
                from pdf_tools import optimize_pdf
                encoded = optimize_pdf(filename)
            else:
                encoded = encode_import(filename)
            if console:
                self.console_store.save(output, kind, encoded, label, create_only=create_only)
            else:
                self.store.save(output, serial, kind, label, encoded, create_only=create_only)
            return encoded
        def done(encoded):
            self.busy = False
            sizes = encoded['compression']['candidate_bytes']
            if encoded.get('format') == 'SVG':
                localize(self.note, 'Saved original SVG logo.', values={})
            elif is_pdf:
                localize(self.note, 'Saved {v0}.pdf · {v1} pages · {v2:.1f} → {v3:.1f} KiB', values={'v0': label, 'v1': encoded['pages'], 'v2': sizes['original'] / 1024, 'v3': encoded['bytes'] / 1024})
            else:
                localize(self.note, 'Saved {v0}.webp · lossless: {v1:.1f} KiB · quality 90: {v2:.1f} KiB', values={'v0': label, 'v1': sizes['lossless'] / 1024, 'v2': sizes['lossy90'] / 1024})
            self.reload_game(output, serial, console)
        self.task(work, done, self.edit_failed)

    def edit_failed(self, exc):
        self.busy = False
        localize(self.note, 'The change was not saved. Previous backups are preserved.', values={})
        self.update_buttons()
        messagebox.showerror(tr('Could not save'), str(exc), parent=self.window)

    def reload_game(self, output, serial, console=False):
        if self.current_output != output:
            return
        self.catalog = self.store.read_catalog(output)
        if console:
            if self.console_mode:
                self.show_console()
            return
        self.games = dict(self.catalog['games'])
        self.serial = serial
        self.filter_games()

    def reset(self, label):
        if not self.can_edit():
            return
        output, serial = self.current_output, self.serial
        console = self.console_mode
        self.busy = True
        self.update_buttons()
        def done(_):
            self.busy = False
            localize(self.note, 'Last console change undone.' if console else 'Original artwork restored; the manual change remains in history.', values={})
            self.reload_game(output, serial, console)
        self.task(lambda: self.console_store.undo(output, label) if console else self.store.reset(output, serial, label), done, self.edit_failed)

    def can_edit(self):
        return bool(self.catalog and (self.console_mode or self.serial in self.catalog.get('games', {})) and
                    self.catalog.get('status') in {'complete', 'sample_complete'} and
                    self.catalog.get('schema_version') == 2 and not self.busy and not self.store.lock_status())

    def update_buttons(self):
        state = 'normal' if self.can_edit() else 'disabled'
        for button in [self.add_button, *self.action_buttons]:
            button.configure(state=state)
        self.undo_button.configure(state=state)
        self.metadata_button.configure(state=state)
        self.language_button.configure(state='disabled' if self.busy else 'normal')
        available = not self.busy and not self.store.lock_status()
        self.new_game_button.configure(state='normal' if available else 'disabled')
        self.undo_game_button.configure(state='normal' if available and self.current_output and self.registration.can_undo(self.current_output) else 'disabled')

    def edit_metadata(self):
        if self.metadata_dialog and self.metadata_dialog.window.winfo_exists():
            self.metadata_dialog.window.lift()
            return self.metadata_dialog
        if not self.can_edit():
            return
        from metadata_dialog import MetadataDialog
        self.metadata_dialog = MetadataDialog(self)
        return self.metadata_dialog

    def add_game(self):
        if self.busy or self.store.lock_status():
            return
        from game_dialog import AddGameDialog
        return AddGameDialog(self)

    def undo_game(self):
        if self.busy or not self.current_output or self.store.lock_status():
            return
        output = self.current_output
        if not messagebox.askyesno(tr('Undo game registration'), tr('This will undo the last game registration for this console. New games must be empty; existing artwork is preserved.'), parent=self.window):
            return
        self.busy = True
        self.update_buttons()
        def done(_):
            self.busy = False
            self.refresh_libraries()
            self.update_buttons()
        self.task(lambda: self.registration.undo(output), done, self.edit_failed)

    def undo(self):
        if not self.can_edit():
            return
        output, serial = self.current_output, self.serial
        console = self.console_mode
        self.busy = True
        self.update_buttons()
        def done(_):
            self.busy = False
            localize(self.note, 'Last console change undone.' if console else 'Last change to this game undone.', values={})
            self.reload_game(output, serial, console)
        self.task(lambda: self.console_store.undo(output) if console else self.store.undo(output, serial), done, self.edit_failed)

    def poll_status(self):
        if self.closed:
            return
        self.refresh_status()
        self.window.after(1500, self.poll_status)

    def refresh_status(self):
        locked = self.store.lock_status()
        if locked:
            set_text(self.status, 'Read only · {v0}', v0=locked)
        else:
            set_text(self.status, 'Editing available · Backups and history: {v0}', v0=self.store.manual)
        self.update_buttons()

    def toggle_language(self):
        if self.busy:
            return
        try:
            set_language('es' if language() == 'en' else 'en', self.settings_file)
        except OSError as exc:
            messagebox.showerror(tr('Could not save language'), str(exc), parent=self.window)
            return
        refresh_translations()
        self.language_button.configure(text='ES' if language() == 'en' else 'EN')
        # Re-render only the current view; keep the library, filters, selection
        # and image history unchanged.
        if self.console_mode:
            self.show_console()
        elif self.catalog:
            self.filter_games()
            self.select_game()
        self.refresh_status()

    def view_image(self, path):
        is_svg = path.suffix.lower() == '.svg'
        dialog = tk.Toplevel(self.window)
        localize_title(dialog, '{v0} · SVG preview' if is_svg else '{v0} · pixel view', v0=path.name)
        dialog.geometry('960x720')
        controls = ttk.Frame(dialog, padding=8)
        controls.pack(fill='x')
        viewport = ttk.Frame(dialog)
        viewport.pack(fill='both', expand=True)
        canvas = tk.Canvas(viewport, bg='#10151c', highlightthickness=0)
        horizontal = ttk.Scrollbar(viewport, orient='horizontal', command=canvas.xview)
        vertical = ttk.Scrollbar(viewport, orient='vertical', command=canvas.yview)
        canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        canvas.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        if is_svg:
            from svg_tools import preview_svg
            raw = path.read_bytes()
            original = preview_svg(raw)
        else:
            with Image.open(path) as image:
                original = image.convert('RGBA')
        def zoom(scale):
            if scale is None:
                scale = min(max(1, canvas.winfo_width())/original.width, max(1, canvas.winfo_height())/original.height)
            size = (max(1, int(original.width*scale)), max(1, int(original.height*scale)))
            displayed = preview_svg(raw, min(4096, max(size))) if is_svg else original.resize(size, Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(displayed)
            canvas.photo = photo
            canvas.delete('all')
            canvas.create_image(0, 0, image=photo, anchor='nw')
            canvas.configure(scrollregion=(0, 0, *displayed.size))
        for label, scale in [('Fit', None), ('100%', 1), ('200%', 2), ('400%', 4)]:
            localize(ttk.Button(controls, command=lambda s=scale: zoom(s)), label).pack(side='left', padx=4)
        localize(ttk.Label(controls), 'Vector preview; the original SVG is preserved.' if is_svg else 'Nearest-neighbor zoom to inspect pixels', values={}).pack(side='left', padx=16)
        dialog.after(100, lambda: zoom(1))

    def open_pdf(self, path):
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror(tr('Could not open the manual'), str(exc), parent=self.window)

    def close(self):
        if self.busy:
            messagebox.showinfo(tr('Operation in progress'), tr('Wait for the operation to finish before closing.'), parent=self.window)
            return
        if self.metadata_dialog and self.metadata_dialog.window.winfo_exists():
            self.metadata_dialog.close()
            if self.metadata_dialog is not None:
                return
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.window.update_idletasks()
        for callback in self.window.tk.call('after', 'info'):
            self.window.after_cancel(callback)
        self.window.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--samples', action='store_true', help='Include pilot libraries')
    parser.add_argument('--smoke-test', action='store_true', help='Build UI and close automatically')
    parser.add_argument('--self-test', action='store_true', help='Exercise UI against a temporary library')
    parser.add_argument('--self-test-report', type=Path, help='Write the automated test result to a JSON file')
    args = parser.parse_args()
    if args.self_test:
        from check_artwork_editor import run
        result = run()
        if args.self_test_report:
            import sys
            import PIL
            from pdf_tools import pdf_api
            pdf_api()
            write_json(args.self_test_report, {'status': 'passed' if result == 0 else 'failed',
                       'frozen': bool(getattr(sys, 'frozen', False)), 'pillow': PIL.__version__,
                       'pdf': True, 'console_artwork': True})
        return result
    initialize_language(settings_path())
    window = tk.Tk()
    window.withdraw()
    from editor_location import choose_library
    library = choose_library(args.root, settings_path(),
        lambda: filedialog.askdirectory(parent=window, mustexist=True, initialdir=str(args.root),
                                       title=tr('Select your library: the folder containing the consoles')),
        lambda text: messagebox.showerror(tr('Library not found'), text, parent=window), args.samples)
    if library is None:
        window.destroy()
        return 0
    editor = Editor(window, args.root, args.samples, library=library, settings=settings_path())
    if not args.smoke_test:
        window.deiconify()
    if args.smoke_test:
        window.after(2000, editor.close)
    window.mainloop()


if __name__ == '__main__':
    raise SystemExit(main())
