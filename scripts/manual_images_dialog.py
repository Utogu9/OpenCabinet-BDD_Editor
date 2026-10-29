"""Review an explicit page order before building and importing a WebP CBZ manual."""
from pathlib import Path
from queue import SimpleQueue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageOps, ImageTk
from i18n import tr, localize, localize_title


class ManualImagesDialog:
    def __init__(self, editor):
        self.editor = editor
        self.output, self.serial = editor.current_output, editor.serial
        self.paths = []
        self.busy = False
        self.generation = 0
        self.closed = False
        self.photo = None
        self.progress_timer = None
        self.window = tk.Toplevel(editor.window)
        localize_title(self.window, 'Images to CBZ manual')
        self.window.geometry('940x650')
        self.window.minsize(750, 480)
        self.window.transient(editor.window)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill='both', expand=True)
        localize(ttk.Label(frame, wraplength=860),
            'Pages follow the list order. Add images in batches or one at a time, then use Move up/down to arrange them.').pack(anchor='w')
        localize(ttk.Label(frame, wraplength=860, style='Muted.TLabel'),
            'No margins or cropping. Images fit within 3840 x 2160 px, preserving proportions. Smaller images are not enlarged.').pack(anchor='w', pady=(6, 12))
        content = ttk.Frame(frame)
        content.pack(fill='both', expand=True)
        left = ttk.Frame(content)
        left.pack(side='left', fill='both', expand=True)
        self.pages = tk.Listbox(left, exportselection=False, selectmode='browse',
                                bg='#1e2632', fg='#edf2f7', selectbackground='#345469', width=42)
        scroll = ttk.Scrollbar(left, command=self.pages.yview)
        self.pages.configure(yscrollcommand=scroll.set)
        self.pages.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.pages.bind('<<ListboxSelect>>', lambda _: self.preview())
        right = ttk.Frame(content, padding=(16, 0, 0, 0))
        right.pack(side='left', fill='both', expand=True)
        self.preview_label = localize(ttk.Label(right, anchor='center'), 'No image')
        self.preview_label.pack(fill='both', expand=True)
        self.info = ttk.Label(right, wraplength=390)
        self.info.pack(fill='x', pady=8)
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(12, 0))
        self.buttons = []
        for text, command in [('Add images', self.add_images), ('Move up', lambda: self.move(-1)),
                              ('Move down', lambda: self.move(1)), ('Remove page', self.remove)]:
            button = localize(ttk.Button(actions, command=command), text)
            button.pack(side='left', padx=(0, 5))
            self.buttons.append(button)
        bottom = ttk.Frame(frame)
        bottom.pack(fill='x', pady=(10, 0))
        self.status = localize(ttk.Label(bottom), 'No pages selected.')
        self.status.pack(side='left')
        self.create_button = localize(ttk.Button(bottom, style='Accent.TButton', command=self.create), 'Create and add manual')
        self.create_button.pack(side='right')
        self.close_button = localize(ttk.Button(bottom, command=self.close), 'Close')
        self.close_button.pack(side='right', padx=6)
        self.refresh()
        self.window.after_idle(self.add_images)

    def add_images(self):
        if self.busy or self.closed:
            return
        paths = filedialog.askopenfilenames(parent=self.window, title=tr('Select manual page images'),
            filetypes=[(tr('Images'), '*.png *.jpg *.jpeg *.webp')])
        self.append(paths)

    def append(self, paths):
        if self.busy or not paths:
            return
        if len(self.paths) + len(paths) > 2000:
            messagebox.showerror(tr('Could not complete the action'), tr('Select between 1 and 2000 images.'), parent=self.window)
            return
        first = len(self.paths)
        self.paths.extend(Path(path) for path in paths)
        self.refresh(first)

    def refresh(self, selected=None):
        self.pages.delete(0, 'end')
        for index, path in enumerate(self.paths, 1):
            self.pages.insert('end', f'{index}. {path.name}')
        if self.paths:
            selected = min(len(self.paths)-1, selected if selected is not None else 0)
            self.pages.selection_set(selected)
            self.pages.see(selected)
            localize(self.status, '{v0} pages selected.', values={'v0': len(self.paths)})
        else:
            localize(self.status, 'No pages selected.', values={})
        self.create_button.configure(state='normal' if self.paths and not self.busy else 'disabled')
        self.preview()

    def move(self, delta):
        selected = self.pages.curselection()
        if self.busy or not selected:
            return
        index = selected[0]
        target = index + delta
        if 0 <= target < len(self.paths):
            self.paths[index], self.paths[target] = self.paths[target], self.paths[index]
            self.refresh(target)

    def remove(self):
        selected = self.pages.curselection()
        if not self.busy and selected:
            self.paths.pop(selected[0])
            self.refresh(selected[0])

    def preview(self):
        self.generation += 1
        generation = self.generation
        selected = self.pages.curselection()
        self.photo = None
        self.preview_label.configure(image='')
        self.info.configure(text='')
        if not selected:
            localize(self.preview_label, 'No image', values={})
            return
        path = self.paths[selected[0]]
        localize(self.preview_label, 'Loading…', values={})
        def work():
            if path.stat().st_size > 100*1024**2:
                raise ValueError(tr('The image exceeds 100 MiB'))
            with Image.open(path) as source:
                if source.width * source.height > 40_000_000:
                    raise ValueError(tr('The image exceeds 40 megapixels'))
                image = ImageOps.exif_transpose(source).convert('RGBA')
                size = image.size
                from editor_common import fit_dimensions
                page_size = fit_dimensions(size)
                image.thumbnail((390, 400), Image.Resampling.LANCZOS)
                return image, size, page_size, path.stat().st_size
        def loaded(value):
            if self.closed or generation != self.generation:
                return
            image, size, page_size, length = value
            self.photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.photo, text='')
            self.info.configure(text=f'{path.name}\n{size[0]} x {size[1]} px | {length/1024:.1f} KiB\n' +
                                tr('CBZ page: {v0} x {v1} px', v0=page_size[0], v1=page_size[1]))
        def failed(_):
            if not self.closed and generation == self.generation:
                localize(self.preview_label, 'Unavailable', values={})
        self.editor.task(work, loaded, failed)

    def create(self):
        if self.busy or not self.paths or not self.editor.can_edit() or self.editor.console_mode:
            return
        if (self.editor.current_output, self.editor.serial) != (self.output, self.serial):
            return
        paths = list(self.paths)
        label = self.editor.next_label('manual')
        self.busy = self.editor.busy = True
        for button in [*self.buttons, self.create_button, self.close_button]:
            button.configure(state='disabled')
        self.editor.update_buttons()
        localize(self.status, 'Encoding WebP pages and building CBZ…', values={})
        self.progress = SimpleQueue()
        self.poll_progress()
        def work():
            from cbz_tools import images_to_cbz
            encoded = images_to_cbz(paths, progress=lambda index, total: self.progress.put((index, total)))
            self.editor.store.save(self.output, self.serial, 'manual', label, encoded, create_only=True)
            return encoded
        def done(encoded):
            self.busy = self.editor.busy = False
            localize(self.editor.note, 'Saved {v0}.cbz · {v1} pages · {v2:.1f} → {v3:.1f} KiB',
                values={'v0': label, 'v1': encoded['pages'], 'v2': encoded['compression']['source_bytes']/1024, 'v3': encoded['bytes']/1024})
            self.destroy()
            self.editor.reload_game(self.output, self.serial)
        def failed(exc):
            self.busy = self.editor.busy = False
            for button in [*self.buttons, self.close_button]:
                button.configure(state='normal')
            self.editor.update_buttons()
            self.refresh()
            messagebox.showerror(tr('Could not save'), str(exc), parent=self.window)
        self.editor.task(work, done, failed)

    def poll_progress(self):
        self.progress_timer = None
        if self.closed or not self.busy:
            return
        latest = None
        while not self.progress.empty():
            latest = self.progress.get()
        if latest:
            localize(self.status, 'Encoded page {v0} of {v1}…', values={'v0': latest[0], 'v1': latest[1]})
        self.progress_timer = self.window.after(200, self.poll_progress)

    def close(self):
        if self.busy:
            return
        if self.paths and not messagebox.askyesno(tr('Discard page list'),
                tr('Close without creating the CBZ? The selected images will not be changed.'), parent=self.window):
            return
        self.destroy()

    def destroy(self):
        self.closed = True
        if self.progress_timer:
            self.window.after_cancel(self.progress_timer)
        self.editor.manual_images_dialog = None
        self.window.grab_release()
        self.window.destroy()
