"""Read-only artwork comparison with shared zoom and pan, using bounded viewports."""
from io import BytesIO
from pathlib import Path
import math
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk, ImageOps
from editor_store import inside
from i18n import tr, localize, localize_title


def load_image(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix.lower() == '.svg':
        from svg_tools import svg_info, preview_svg
        width, height = svg_info(raw)
        image = preview_svg(raw, min(4096, max(width, height)))
        return {'image': image, 'raw': raw, 'width': width, 'height': height, 'format': 'SVG', 'bytes': len(raw)}
    with Image.open(BytesIO(raw)) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError(tr('The image exceeds 40 megapixels'))
        image = ImageOps.exif_transpose(source).convert('RGBA')
        return {'image': image, 'raw': None, 'width': image.width, 'height': image.height,
                'format': source.format, 'bytes': len(raw)}


def viewport_image(record, scale, center, viewport):
    """Crop before scaling: even 400% on a large cover only allocates a viewport."""
    image = record['image']
    width, height = record['width'] * scale, record['height'] * scale
    view_w, view_h = viewport
    origin_x, origin_y = width * center[0] - view_w / 2, height * center[1] - view_h / 2
    left, top = max(0, origin_x), max(0, origin_y)
    right, bottom = min(width, origin_x + view_w), min(height, origin_y + view_h)
    if right <= left or bottom <= top:
        return None, (0, 0)
    box = (left / width * image.width, top / height * image.height,
           right / width * image.width, bottom / height * image.height)
    size = (max(1, math.ceil(right-left)), max(1, math.ceil(bottom-top)))
    tile = image.resize(size, Image.Resampling.NEAREST, box=box)
    return tile, (round(left-origin_x), round(top-origin_y))


class ComparisonWindow:
    def __init__(self, editor, images, selected):
        self.editor = editor
        self.paths = {label: inside(editor.current_output/asset['path'], editor.current_output)
                      for label, asset in images.items()
                      if asset.get('format') not in {'PDF', 'CBZ'} and Path(asset['path']).suffix.lower() not in {'.pdf', '.cbz'}}
        self.window = tk.Toplevel(editor.window)
        localize_title(self.window, 'Compare images')
        self.window.geometry('1200x780')
        self.window.minsize(700, 480)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.scale = 1
        self.center = [.5, .5]
        self.records = [None, None]
        self.photos = [None, None]
        self.timer = None
        self.closed = False
        self.drag = None
        controls = ttk.Frame(self.window, padding=8)
        controls.pack(fill='x')
        for label, scale in [('Fit', None), ('100%', 1), ('200%', 2), ('400%', 4)]:
            localize(ttk.Button(controls, command=lambda s=scale: self.zoom(s)), label).pack(side='left', padx=3)
        localize(ttk.Label(controls), 'Shared zoom and pan. Drag to move; scroll to zoom.').pack(side='left', padx=10)
        panels = ttk.Frame(self.window)
        panels.pack(fill='both', expand=True)
        panels.rowconfigure(0, weight=1)
        self.choices, self.canvases, self.details = [], [], []
        labels = list(self.paths)
        others = [label for label in labels if label != selected]
        for side in range(2):
            panels.columnconfigure(side, weight=1, uniform='comparison')
            panel = ttk.Frame(panels, padding=6)
            panel.grid(row=0, column=side, sticky='nsew')
            choice = tk.StringVar(value=selected if side == 0 else others[0])
            selector = ttk.Combobox(panel, values=labels, textvariable=choice, state='readonly')
            selector.pack(fill='x')
            selector.bind('<<ComboboxSelected>>', lambda _, s=side: self.select(s))
            detail = ttk.Label(panel, wraplength=550)
            detail.pack(fill='x', pady=8)
            canvas = tk.Canvas(panel, bg='#10151c', highlightthickness=0)
            canvas.pack(fill='both', expand=True)
            canvas.bind('<Configure>', lambda _: self.schedule())
            canvas.bind('<ButtonPress-1>', lambda event, s=side: self.start_drag(event, s))
            canvas.bind('<B1-Motion>', self.move_drag)
            canvas.bind('<MouseWheel>', lambda e: self.zoom(min(8, max(.05, self.scale * (1.25 if e.delta > 0 else .8)))))
            self.choices.append(choice)
            self.canvases.append(canvas)
            self.details.append(detail)
        self.select(0)
        self.select(1)
        self.window.after_idle(lambda: self.zoom(None) if not self.closed else None)

    def select(self, side):
        try:
            self.records[side] = load_image(self.paths[self.choices[side].get()])
            record = self.records[side]
            self.details[side].configure(text=f"{self.paths[self.choices[side].get()].name}\n"
                f"{record['width']} x {record['height']} px | {record['bytes']/1024:.1f} KiB | {record['format']}")
            self.rasterize(side)
            self.schedule()
        except Exception as exc:
            self.records[side] = None
            self.canvases[side].delete('all')
            self.details[side].configure(text=tr('Unavailable'))
            messagebox.showerror(tr('Could not complete the action'), str(exc), parent=self.window)

    def rasterize(self, side):
        record = self.records[side]
        if record and record['raw']:
            from svg_tools import preview_svg
            record['image'] = preview_svg(record['raw'], min(4096, max(1, math.ceil(max(record['width'], record['height']) * self.scale))))

    def zoom(self, scale):
        if self.closed:
            return
        if scale is None:
            self.window.update_idletasks()
            scale = min((min(max(1, canvas.winfo_width()) / record['width'],
                             max(1, canvas.winfo_height()) / record['height'])
                         for canvas, record in zip(self.canvases, self.records) if record), default=1)
            self.center = [.5, .5]
        self.scale = scale
        for side in range(2):
            self.rasterize(side)
        self.schedule()

    def start_drag(self, event, side):
        self.drag = event.x, event.y, side, tuple(self.center)

    def move_drag(self, event):
        if not self.drag:
            return
        x, y, side, center = self.drag
        record = self.records[side]
        if record:
            self.center = [min(1, max(0, center[0] - (event.x-x)/(record['width']*self.scale))),
                           min(1, max(0, center[1] - (event.y-y)/(record['height']*self.scale)))]
            self.schedule()

    def schedule(self):
        if not self.closed and self.timer is None:
            self.timer = self.window.after_idle(self.draw)

    def draw(self):
        self.timer = None
        for side, (canvas, record) in enumerate(zip(self.canvases, self.records)):
            canvas.delete('all')
            if record:
                tile, position = viewport_image(record, self.scale, self.center,
                                                (max(1, canvas.winfo_width()), max(1, canvas.winfo_height())))
                if tile:
                    self.photos[side] = ImageTk.PhotoImage(tile)
                    canvas.create_image(*position, anchor='nw', image=self.photos[side])

    def close(self):
        self.closed = True
        if self.timer:
            self.window.after_cancel(self.timer)
        self.window.destroy()
